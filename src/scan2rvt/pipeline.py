"""Proceso completo: leer nubes → limpiar → terreno → niveles/forjados → exportar."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from shapely.affinity import translate
from shapely.geometry import Polygon, mapping

from . import __version__, levels, report, terrain
from .cloud import merge, remove_outliers
from .config import Settings
from .io import buscar_nubes, leer_nube
from .model import Forjado, Modelo, Nivel, Terreno
from .paths import ProjectPaths

SALIDAS = ("rvt", "ifc", "obj", "glb", "stl", "las")

Progreso = Callable[[str, float], None]


class Cancelado(Exception):
    pass


@dataclass
class Trabajo:
    nombre: str
    escaner: list[str] = field(default_factory=list)
    dron: list[str] = field(default_factory=list)
    salidas: list[str] = field(default_factory=lambda: ["rvt", "ifc", "obj", "glb"])
    plantilla_rte: str = ""
    epsg: str = ""
    alineadas: bool = True
    carpeta_proyectos: str = ""       # vacío = <raíz>/proyectos
    demo: bool = False


@dataclass
class Resultado:
    modelo: Modelo
    archivos: list[Path]
    avisos: list[str]
    carpeta: Path
    informe: Path | None = None


def _anillo_local(coords, ox, oy) -> list[list[float]]:
    pts = [[round(x - ox, 4), round(y - oy, 4)] for x, y in list(coords)[:-1]]
    return pts


def ejecutar(trabajo: Trabajo, ajustes: Settings, progreso: Progreso | None = None,
             cancelado: Callable[[], bool] | None = None) -> Resultado:
    t0 = time.time()
    avisos: list[str] = []

    def paso(msg: str, pct: float):
        if cancelado and cancelado():
            raise Cancelado()
        if progreso:
            progreso(msg, pct)

    base = Path(trabajo.carpeta_proyectos) if trabajo.carpeta_proyectos else None
    pp = ProjectPaths(trabajo.nombre, base).create()

    # 1. Lectura ---------------------------------------------------------------
    paso("Buscando nubes de puntos…", 0.01)
    if trabajo.demo:
        from . import sintetico

        d = sintetico.generar()
        esc_nubes, dron_nubes = [d.escaner], [d.dron]
        trabajo.epsg = trabajo.epsg or "25830"
    else:
        esc_rutas, av1 = buscar_nubes(trabajo.escaner)
        dron_rutas, av2 = buscar_nubes(trabajo.dron)
        avisos += av1 + av2
        if not esc_rutas and not dron_rutas:
            raise ValueError("No hay nubes de puntos que procesar (.las, .laz, .e57, .ply, .pts, .xyz).")
        total = len(esc_rutas) + len(dron_rutas)
        esc_nubes, dron_nubes = [], []
        for k, (ruta, org) in enumerate([(r, 0) for r in esc_rutas] + [(r, 1) for r in dron_rutas]):
            paso(f"Leyendo {ruta.name} ({k + 1}/{total})…", 0.02 + 0.3 * k / total)
            n = leer_nube(ruta, ajustes.voxel_m, org, progreso=lambda m, p=0.02 + 0.3 * k / total: paso(m, p))
            (esc_nubes if org == 0 else dron_nubes).append(n)
            crs = n.info.get("crs", "")
            if crs and not trabajo.epsg and "EPSG" in crs.upper():
                avisos.append(f"{ruta.name}: sistema de coordenadas detectado {crs}.")

    if not trabajo.alineadas and esc_nubes and dron_nubes:
        avisos.append("Has indicado que escáner y dron NO están alineados. Esta versión aún no los alinea: "
                      "el terreno sale del dron y los niveles del escáner, cada uno en sus coordenadas.")

    # 2. Limpieza --------------------------------------------------------------
    escaner = merge(esc_nubes)
    dron = merge(dron_nubes)
    if ajustes.quitar_ruido:
        paso("Quitando ruido…", 0.34)
        escaner = remove_outliers(escaner) if len(escaner) else escaner
        dron = remove_outliers(dron) if len(dron) else dron

    # 3. Terreno ---------------------------------------------------------------
    res_terreno = None
    if len(dron):
        paso("Detectando el terreno…", 0.45)
        res_terreno = terrain.detectar_terreno(dron, ajustes.terreno)
        if res_terreno is None:
            avisos.append("No se ha podido detectar el terreno en la nube del dron.")
    else:
        avisos.append("Sin nube de dron: no se genera terreno.")

    # 4. Niveles y forjados ----------------------------------------------------
    res_niveles = None
    if len(escaner):
        paso("Detectando niveles y forjados…", 0.6)
        res_niveles = levels.detectar_niveles(escaner, ajustes.niveles)
        avisos += res_niveles.avisos
    else:
        avisos.append("Sin nube de escáner: no se detectan niveles ni forjados.")

    # 5. Modelo en coordenadas locales -----------------------------------------
    paso("Construyendo el modelo…", 0.75)
    todas = np.concatenate([n.xyz for n in (escaner, dron) if len(n)])
    centro = (todas[:, :2].min(axis=0) + todas[:, :2].max(axis=0)) / 2
    ox, oy = float(np.round(centro[0])), float(np.round(centro[1]))
    if res_niveles and res_niveles.niveles:
        oz = float(np.round(res_niveles.niveles[0][1], 3))
    else:
        oz = float(np.floor(todas[:, 2].min()))
    modelo = Modelo(offset=[ox, oy, oz], epsg=trabajo.epsg)

    if res_niveles:
        for i, (nombre, cota) in enumerate(res_niveles.niveles):
            modelo.niveles.append(Nivel(id=f"N{i}", nombre=nombre, cota=round(cota - oz, 4) + 0.0))
        k = 0
        for i_nivel, fd in res_niveles.forjados:
            for poly in fd.poligonos:
                p: Polygon = translate(poly, -ox, -oy).buffer(0)
                if p.is_empty or p.geom_type != "Polygon":
                    continue
                p = Polygon(p.exterior.coords, [h.coords for h in p.interiors])
                modelo.forjados.append(Forjado(
                    id=f"F{k}",
                    nivel_id=f"N{i_nivel}",
                    cota_superior=round(fd.z_superior - oz, 4) + 0.0,
                    espesor=round(fd.z_superior - fd.z_inferior, 4),
                    contorno=_anillo_local(mapping(p)["coordinates"][0], 0, 0),
                    huecos=[_anillo_local(h, 0, 0) for h in mapping(p)["coordinates"][1:]],
                    area_m2=round(p.area, 2),
                    espesor_medido=fd.medido,
                ))
                k += 1

    if res_terreno:
        loc = np.column_stack([res_terreno.rejilla_xy - [ox, oy], res_terreno.rejilla_z - oz])
        modelo.terreno = Terreno(
            puntos=np.round(loc, 4).tolist(),
            vertices=np.round(loc, 4).tolist(),
            caras=res_terreno.caras.tolist(),
            paso_m=res_terreno.paso,
        )
        avisos.append(f"Terreno: {res_terreno.metodo}, {len(loc)} puntos, malla de {res_terreno.paso:.2f} m.")
    modelo.avisos = avisos

    # 6. Exportación -----------------------------------------------------------
    archivos: list[Path] = []
    nombre = pp.root.name
    json_path = modelo.save(pp.resultados / "modelo.json")
    archivos.append(json_path)

    from .export import ifc as exp_ifc
    from .export import las as exp_las
    from .export import mallas as exp_mallas

    if "ifc" in trabajo.salidas:
        paso("Exportando IFC…", 0.8)
        archivos.append(exp_ifc.exportar(modelo, pp.resultados / f"{nombre}.ifc", nombre))
    formatos = [f for f in ("obj", "glb", "stl") if f in trabajo.salidas]
    if formatos:
        paso("Exportando mallas 3D…", 0.84)
        archivos += exp_mallas.exportar(modelo, pp.resultados, nombre, formatos)
    if "las" in trabajo.salidas:
        paso("Guardando nubes limpias…", 0.87)
        if len(dron):
            archivos.append(exp_las.exportar(dron, pp.resultados / f"{nombre}_dron_limpio.laz",
                                             res_terreno.es_suelo if res_terreno else None))
        if len(escaner):
            archivos.append(exp_las.exportar(escaner, pp.resultados / f"{nombre}_escaner_limpio.laz"))

    rvt_estado = ""
    if "rvt" in trabajo.salidas:
        paso("Generando .rvt con Revit…", 0.9)
        from . import revit_bridge

        try:
            rvt = revit_bridge.generar_rvt(json_path, pp.resultados / f"{nombre}.rvt", ajustes,
                                           trabajo.plantilla_rte or ajustes.plantilla_rte, pp,
                                           progreso=lambda m: paso(m, 0.93))
            archivos.append(rvt)
            rvt_estado = "ok"
        except revit_bridge.RevitNoDisponible as e:
            avisos.append(f"RVT no generado: {e}")
            rvt_estado = str(e)

    # 7. Informe -----------------------------------------------------------------
    paso("Redactando el informe…", 0.97)
    info = {
        "version": __version__,
        "segundos": round(time.time() - t0, 1),
        "puntos_escaner": len(escaner),
        "puntos_dron": len(dron),
        "archivos": [str(a) for a in archivos],
        "rvt": rvt_estado,
    }
    (pp.cache / "ultimo_proceso.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    informe = report.escribir(pp.informe / "informe.html", trabajo.nombre, modelo, info, res_niveles)
    paso("Terminado.", 1.0)
    return Resultado(modelo=modelo, archivos=archivos, avisos=avisos, carpeta=pp.root, informe=informe)
