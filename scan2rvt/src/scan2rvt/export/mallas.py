"""Mallas del modelo (terreno, forjados, muros y cubiertas) en OBJ, GLB y STL, en coordenadas locales."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import LineString, Polygon

from ..model import Cubierta, Forjado, Modelo, Muro

FORMATOS = {"obj": ".obj", "glb": ".glb", "stl": ".stl"}


def forjado_malla(f: Forjado) -> trimesh.Trimesh:
    poly = Polygon(f.contorno, f.huecos)
    m = trimesh.creation.extrude_polygon(poly, f.espesor, engine="earcut")
    m.apply_translation([0, 0, f.cota_superior - f.espesor])
    return m


def muro_malla(m: Muro, z_base: float) -> trimesh.Trimesh:
    """Muro centrado en su eje (igual que en IFC y Revit)."""
    poly = LineString([m.inicio, m.fin]).buffer(m.espesor / 2, cap_style="flat")
    malla = trimesh.creation.extrude_polygon(poly, m.altura, engine="earcut")
    malla.apply_translation([0, 0, z_base])
    return malla


def cubierta_malla(c: Cubierta) -> trimesh.Trimesh:
    malla = trimesh.creation.extrude_polygon(Polygon(c.contorno, c.huecos), c.espesor, engine="earcut")
    malla.apply_translation([0, 0, c.cota_inferior])
    return malla


def escena(modelo: Modelo) -> trimesh.Scene:
    sc = trimesh.Scene()
    if modelo.terreno is not None and modelo.terreno.caras:
        t = trimesh.Trimesh(np.asarray(modelo.terreno.vertices), np.asarray(modelo.terreno.caras), process=False)
        t.visual.face_colors = [120, 160, 90, 255]
        sc.add_geometry(t, node_name="Terreno", geom_name="Terreno")
    for f in modelo.forjados:
        m = forjado_malla(f)
        m.visual.face_colors = [200, 200, 200, 255] if f.espesor_medido else [230, 170, 120, 255]
        sc.add_geometry(m, node_name=f.id, geom_name=f.id)
    cotas = {n.id: n.cota for n in modelo.niveles}
    for m in modelo.muros:
        malla = muro_malla(m, cotas.get(m.nivel_id, 0.0))
        malla.visual.face_colors = [235, 235, 225, 255] if m.confianza >= 0.3 else [240, 150, 90, 255]
        sc.add_geometry(malla, node_name=m.id, geom_name=m.id)
    for c in modelo.cubiertas:
        malla = cubierta_malla(c)
        malla.visual.face_colors = [190, 90, 80, 255]
        sc.add_geometry(malla, node_name=c.id, geom_name=c.id)
    return sc


def exportar(modelo: Modelo, carpeta: Path, nombre: str, formatos: list[str]) -> list[Path]:
    sc = escena(modelo)
    salidas = []
    if not sc.geometry:
        return salidas
    for fmt in formatos:
        ext = FORMATOS[fmt]
        ruta = carpeta / f"{nombre}{ext}"
        if fmt == "stl":
            sc.to_mesh().export(ruta)   # STL no admite varios objetos
        else:
            sc.export(ruta)
        salidas.append(ruta)
    return salidas
