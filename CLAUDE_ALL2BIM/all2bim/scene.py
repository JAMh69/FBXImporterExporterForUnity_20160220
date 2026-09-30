"""Construccion de mallas PyVista a partir del modelo interno (sin dependencia de Qt)."""
from __future__ import annotations

import math

import numpy as np
import pyvista as pv

from .model import BimModel


def wall_mesh(w, elevation: float) -> pv.PolyData:
    dx, dy = w.end[0] - w.start[0], w.end[1] - w.start[1]
    length = math.hypot(dx, dy)
    box = pv.Box(bounds=(0, length, -w.thickness / 2, w.thickness / 2, 0, w.height))
    box.rotate_z(math.degrees(math.atan2(dy, dx)), inplace=True)
    box.translate((w.start[0], w.start[1], elevation), inplace=True)
    return box


def prism_mesh(outline, z0: float, thickness: float) -> pv.PolyData:
    """Prisma extruido desde un contorno XY cerrado (z0 = cara inferior)."""
    pts = np.array([(x, y, z0) for x, y in outline], dtype=float)
    n = len(pts)
    face = np.hstack([[n], np.arange(n)])
    poly = pv.PolyData(pts, faces=face)
    return poly.extrude((0, 0, thickness), capping=True).clean()


def model_meshes(model: BimModel, review_below: float = 0.5) -> list[tuple[str, int, pv.PolyData, str]]:
    """Devuelve (tipo, indice, malla, color). Los muros de baja confianza salen en naranja."""
    elev = {s.name: s.elevation for s in model.storeys}
    out = []
    for i, w in enumerate(model.walls):
        color = "orange" if w.confidence < review_below else "lightgray"
        out.append(("muro", i, wall_mesh(w, elev.get(w.storey, 0.0)), color))
    for i, s in enumerate(model.slabs):
        out.append(("suelo", i, prism_mesh(s.outline, elev.get(s.storey, 0.0) - s.thickness, s.thickness), "tan"))
    for i, r in enumerate(model.roofs):
        out.append(("cubierta", i, prism_mesh(r.outline, r.elevation, r.thickness), "indianred"))
    return out


def cloud_mesh(pts: np.ndarray, max_points: int = 500_000) -> pv.PolyData:
    if len(pts) > max_points:
        pts = pts[np.random.default_rng(0).choice(len(pts), max_points, replace=False)]
    cloud = pv.PolyData(pts.astype(np.float32))
    cloud["z"] = pts[:, 2]
    return cloud
