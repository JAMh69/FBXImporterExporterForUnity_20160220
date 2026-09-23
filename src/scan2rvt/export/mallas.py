"""Mallas del modelo (terreno + forjados) en OBJ, GLB y STL, en coordenadas locales."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import Polygon

from ..model import Forjado, Modelo

FORMATOS = {"obj": ".obj", "glb": ".glb", "stl": ".stl"}


def forjado_malla(f: Forjado) -> trimesh.Trimesh:
    poly = Polygon(f.contorno, f.huecos)
    m = trimesh.creation.extrude_polygon(poly, f.espesor, engine="earcut")
    m.apply_translation([0, 0, f.cota_superior - f.espesor])
    return m


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
