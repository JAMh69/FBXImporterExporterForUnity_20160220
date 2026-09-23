"""Lectura de nubes de puntos.

Formatos: .las/.laz (dron DJI Terra, exportaciones de Cyclone/ReCap), .e57
(estándar de escáneres; es la forma de usar un .rcp: ReCap → Exportar → E57),
.ply, .pts, .xyz.

Los archivos se leen por bloques y se submuestrean por vóxel mientras se leen,
así una nube de muchos GB no necesita caber entera en memoria.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np

from ..cloud import Nube, merge, voxel_reduce

EXTENSIONES = (".las", ".laz", ".e57", ".ply", ".pts", ".xyz")
NO_SOPORTADAS = {
    ".rcp": "Los .rcp/.rcs son formato cerrado de Autodesk. Ábrelo en ReCap y usa Exportar → E57.",
    ".rcs": "Los .rcp/.rcs son formato cerrado de Autodesk. Ábrelo en ReCap y usa Exportar → E57.",
}

Progreso = Callable[[str], None]

_BLOQUE = 5_000_000


def buscar_nubes(rutas: list[str | Path]) -> tuple[list[Path], list[str]]:
    """Expande carpetas (recursivo) y devuelve (nubes válidas, avisos)."""
    encontrados: list[Path] = []
    avisos: list[str] = []
    for r in rutas:
        p = Path(r)
        candidatos = sorted(p.rglob("*")) if p.is_dir() else [p]
        for c in candidatos:
            ext = c.suffix.lower()
            if not c.is_file():
                continue
            if ext in EXTENSIONES:
                if c not in encontrados:
                    encontrados.append(c)
            elif ext in NO_SOPORTADAS:
                avisos.append(f"{c.name}: {NO_SOPORTADAS[ext]}")
    return encontrados, avisos


def leer_nube(ruta: str | Path, voxel: float, origen: int, progreso: Progreso | None = None) -> Nube:
    ruta = Path(ruta)
    ext = ruta.suffix.lower()
    log = progreso or (lambda _m: None)
    if ext in (".las", ".laz"):
        nube = _leer_las(ruta, voxel, log)
    elif ext == ".e57":
        nube = _leer_e57(ruta, voxel, log)
    elif ext in (".ply", ".pts", ".xyz"):
        nube = _leer_otros(ruta, voxel)
    elif ext in NO_SOPORTADAS:
        raise ValueError(NO_SOPORTADAS[ext])
    else:
        raise ValueError(f"Formato no soportado: {ruta.name}")
    nube.origen = np.full(len(nube), origen, dtype=np.uint8)
    nube.info.update({"archivo": str(ruta), "puntos": len(nube)})
    return nube


def _leer_las(ruta: Path, voxel: float, log: Progreso) -> Nube:
    import laspy

    with laspy.open(ruta) as f:
        h = f.header
        total = int(h.point_count)
        origin = np.floor(np.asarray(h.mins, dtype=np.float64))
        dims = set(h.point_format.dimension_names)
        tiene_color = {"red", "green", "blue"} <= dims
        partes: list[Nube] = []
        leidos = 0
        for chunk in f.chunk_iterator(_BLOQUE):
            xyz = np.column_stack([np.asarray(chunk.x), np.asarray(chunk.y), np.asarray(chunk.z)]).astype(np.float64)
            rgb = None
            if tiene_color:
                rgb16 = np.column_stack([np.asarray(chunk.red), np.asarray(chunk.green), np.asarray(chunk.blue)])
                # LAS guarda el color en 16 bits; algunos programas lo escriben en 8 bits.
                rgb = (rgb16 >> 8).astype(np.uint8) if rgb16.max(initial=0) > 255 else rgb16.astype(np.uint8)
            inten = np.asarray(chunk.intensity, dtype=np.float32) if "intensity" in dims else None
            clase = np.asarray(chunk.classification, dtype=np.uint8) if "classification" in dims else None
            partes.append(voxel_reduce(Nube(xyz, rgb, inten, clase), voxel, origin))
            leidos += len(xyz)
            log(f"  {ruta.name}: {leidos:,} / {total:,} puntos leídos".replace(",", "."))
    nube = voxel_reduce(merge(partes), voxel, origin) if len(partes) > 1 else (partes[0] if partes else Nube(np.zeros((0, 3))))
    crs = None
    try:
        crs = h.parse_crs()
    except Exception:  # noqa: BLE001 - el CRS es opcional
        crs = None
    nube.info["crs"] = crs.to_string() if crs is not None else ""
    return nube


def _leer_e57(ruta: Path, voxel: float, log: Progreso) -> Nube:
    import pye57

    e57 = pye57.E57(str(ruta))
    partes: list[Nube] = []
    try:
        for i in range(e57.scan_count):
            d = e57.read_scan(i, intensity=True, colors=True, ignore_missing_fields=True, transform=True)
            xyz = np.column_stack([d["cartesianX"], d["cartesianY"], d["cartesianZ"]]).astype(np.float64)
            valid = np.isfinite(xyz).all(axis=1)
            if "cartesianInvalidState" in d:
                valid &= np.asarray(d["cartesianInvalidState"]) == 0
            rgb = None
            if all(k in d for k in ("colorRed", "colorGreen", "colorBlue")):
                rgb = np.column_stack([d["colorRed"], d["colorGreen"], d["colorBlue"]])
                rgb = np.clip(rgb, 0, 255).astype(np.uint8) if rgb.max(initial=0) <= 255 else (rgb >> 8).astype(np.uint8)
            inten = np.asarray(d["intensity"], dtype=np.float32) if "intensity" in d else None
            n = Nube(xyz, rgb, inten).subset(valid)
            partes.append(voxel_reduce(n, voxel))
            log(f"  {ruta.name}: estación {i + 1} de {e57.scan_count}")
    finally:
        e57.close()
    return voxel_reduce(merge(partes), voxel) if partes else Nube(np.zeros((0, 3)))


def _leer_otros(ruta: Path, voxel: float) -> Nube:
    """PLY (con trimesh) y formatos de texto .pts / .xyz: x y z [intensidad] [r g b]."""
    if ruta.suffix.lower() == ".ply":
        import trimesh

        pc = trimesh.load(ruta, process=False)
        xyz = np.asarray(pc.vertices, dtype=np.float64)
        rgb = None
        colores = getattr(getattr(pc, "visual", None), "vertex_colors", None)
        if colores is None:
            colores = getattr(pc, "colors", None)
        if colores is not None and len(colores) == len(xyz):
            rgb = np.asarray(colores)[:, :3].astype(np.uint8)
        return voxel_reduce(Nube(xyz, rgb), voxel)
    if ruta.suffix.lower() == ".pcd":
        raise ValueError("El formato .pcd no está soportado; expórtalo como .las, .e57 o .ply.")

    partes = []
    with open(ruta, "r", encoding="utf-8", errors="replace") as f:
        primera = f.readline().split()
        if len(primera) >= 3:                      # .xyz sin cabecera
            f.seek(0)
        while True:
            lineas = f.readlines(64 * 1024 * 1024)
            if not lineas:
                break
            datos = np.loadtxt(lineas, ndmin=2, comments="#")
            if datos.shape[1] < 3:
                continue
            xyz = datos[:, :3].astype(np.float64)
            rgb = datos[:, -3:].clip(0, 255).astype(np.uint8) if datos.shape[1] >= 6 else None
            inten = datos[:, 3].astype(np.float32) if datos.shape[1] in (4, 7) else None
            partes.append(voxel_reduce(Nube(xyz, rgb, inten), voxel, np.zeros(3)))
    if not partes:
        return Nube(np.zeros((0, 3)))
    return voxel_reduce(merge(partes), voxel, np.zeros(3)) if len(partes) > 1 else partes[0]
