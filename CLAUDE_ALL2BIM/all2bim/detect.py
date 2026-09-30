"""Deteccion geometrica basica sobre una nube de puntos (numpy, sin dependencias pesadas).

Heuristicas simples (MVP): plantas/forjados por histograma en Z y muros por
RANSAC de planos verticales. Los resultados requieren revision manual.
"""
from __future__ import annotations

import laspy
import numpy as np

from .model import BimModel, Roof, Slab, Storey, Wall


def load_las(path: str, voxel: float = 0.05) -> np.ndarray:
    las = laspy.read(path)
    pts = np.column_stack([las.x, las.y, las.z]).astype(np.float64)
    if voxel > 0:
        keys = np.floor(pts / voxel).astype(np.int64)
        _, idx = np.unique(keys, axis=0, return_index=True)
        pts = pts[np.sort(idx)]
    return pts


def _floor_levels(z: np.ndarray, bin_size: float = 0.05, min_frac: float = 0.05) -> list[float]:
    """Picos horizontales de densidad en Z (suelos). Toma el pico mas bajo de cada grupo."""
    edges = np.arange(z.min(), z.max() + bin_size, bin_size)
    hist, edges = np.histogram(z, bins=edges)
    thr = hist.max() * min_frac
    peaks = [i for i in range(len(hist))
             if hist[i] >= thr and hist[i] >= (hist[i - 1] if i else 0) and hist[i] >= (hist[i + 1] if i + 1 < len(hist) else 0)]
    levels: list[float] = []
    for i in peaks:
        c = float((edges[i] + edges[i + 1]) / 2)
        if not levels or c - levels[-1] > 0.5:
            levels.append(c)
    return levels


def _ransac_vertical_lines(xy: np.ndarray, tol: float = 0.03, iters: int = 400,
                           min_inliers: int = 200, max_lines: int = 20, seed: int = 0):
    """Lineas 2D (planos verticales vistos en planta) por RANSAC secuencial."""
    rng = np.random.default_rng(seed)
    remaining = xy.copy()
    out = []
    for _ in range(max_lines):
        if len(remaining) < min_inliers:
            break
        best = None
        for _ in range(iters):
            a, b = remaining[rng.choice(len(remaining), 2, replace=False)]
            d = b - a
            n = np.hypot(*d)
            if n < 1e-6:
                continue
            normal = np.array([-d[1], d[0]]) / n
            dist = np.abs((remaining - a) @ normal)
            mask = dist < tol
            if best is None or mask.sum() > best[0].sum():
                best = (mask, a, d / n)
        if best is None or best[0].sum() < min_inliers:
            break
        mask, a, u = best
        inl = remaining[mask]
        t = (inl - a) @ u
        out.append((a + u * t.min(), a + u * t.max(), int(mask.sum())))
        remaining = remaining[~mask]
    return out


def points_to_model(pts: np.ndarray, wall_thickness: float = 0.2, slab_thickness: float = 0.2) -> BimModel:
    """Con >=2 niveles horizontales, el mas alto es la cubierta y el resto son plantas."""
    model = BimModel()
    levels = _floor_levels(pts[:, 2])
    if not levels:
        return model
    if len(levels) >= 2:
        roof_z, floors = levels[-1], levels[:-1]
    else:
        roof_z, floors = float(pts[:, 2].max()), levels
    tops = floors[1:] + [roof_z]
    for k, (z0, z1) in enumerate(zip(floors, tops)):
        name = f"Planta {k}"
        model.storeys.append(Storey(name, z0))
        band = pts[(pts[:, 2] > z0 + 0.3) & (pts[:, 2] < z1 - 0.3)]  # excluye suelo y techo
        if len(band) == 0:
            continue
        lo, hi = band[:, :2].min(0), band[:, :2].max(0)
        outline = [(float(lo[0]), float(lo[1])), (float(hi[0]), float(lo[1])),
                   (float(hi[0]), float(hi[1])), (float(lo[0]), float(hi[1]))]
        model.slabs.append(Slab(name, outline, slab_thickness))
        if k == len(floors) - 1 and len(levels) >= 2:
            model.roofs.append(Roof(outline, float(z1), slab_thickness))
        for p0, p1, n in _ransac_vertical_lines(band[:, :2]):
            model.walls.append(Wall(name, (float(p0[0]), float(p0[1])), (float(p1[0]), float(p1[1])),
                                    float(z1 - z0), wall_thickness, confidence=min(1.0, n / 2000)))
    return model
