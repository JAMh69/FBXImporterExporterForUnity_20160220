"""Detección del terreno y modelo digital del terreno (MDT).

Método: filtro morfológico progresivo (Zhang et al., 2003, "A progressive
morphological filter for removing nonground measurements from airborne LIDAR
data", IEEE TGRS 41(4)). Si la nube ya viene clasificada (clase LAS 2 = suelo,
p. ej. desde DJI Terra), se usa esa clasificación.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage
from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
from scipy.spatial import Delaunay

from .cloud import Nube
from .config import TerrainSettings

CLASE_SUELO = 2


@dataclass
class ResultadoTerreno:
    es_suelo: np.ndarray       # (N,) bool sobre la nube de entrada
    rejilla_xy: np.ndarray     # (M, 2) nodos del MDT (absolutos)
    rejilla_z: np.ndarray      # (M,)
    caras: np.ndarray          # (F, 3) triángulos sobre los nodos
    paso: float
    metodo: str


def clasificar_suelo(nube: Nube, s: TerrainSettings) -> tuple[np.ndarray, str]:
    n = len(nube)
    if nube.clase is not None:
        suelo = nube.clase == CLASE_SUELO
        if suelo.sum() >= max(1000, 0.05 * n):
            return suelo, "clasificación LAS existente (clase 2)"
    return _pmf(nube.xyz, s), "filtro morfológico progresivo"


def _grid_index(xy: np.ndarray, origin: np.ndarray, celda: float) -> np.ndarray:
    return np.floor((xy - origin) / celda).astype(np.int64)


def _pmf(xyz: np.ndarray, s: TerrainSettings) -> np.ndarray:
    celda = s.celda_m
    origin = xyz[:, :2].min(axis=0)
    ij = _grid_index(xyz[:, :2], origin, celda)
    nx, ny = ij.max(axis=0) + 1
    flat = ij[:, 0] * ny + ij[:, 1]
    zmin = np.full(nx * ny, np.inf)
    np.minimum.at(zmin, flat, xyz[:, 2])
    zmin = zmin.reshape(nx, ny)
    vacio = ~np.isfinite(zmin)
    if vacio.all():
        return np.zeros(len(xyz), dtype=bool)
    # Rellenar celdas vacías con la celda ocupada más cercana.
    _, (ii, jj) = ndimage.distance_transform_edt(vacio, return_indices=True)
    z0 = zmin[ii, jj]

    z = z0.copy()
    no_suelo = np.zeros_like(z, dtype=bool)
    dh0, dh_max = 0.3, 3.0
    w_prev = 1
    k = 1
    while True:
        w = 2 * (2 ** (k - 1)) + 1          # 3, 5, 9, 17, 33...
        if (w - 1) * celda > s.ventana_max_m:
            break
        zo = ndimage.grey_opening(z, size=(w, w))
        dh = min(dh0 + s.pendiente * (w - w_prev) * celda, dh_max)
        no_suelo |= (z - zo) > dh
        z = zo
        w_prev = w
        k += 1

    suelo_celda = ~no_suelo & ~vacio
    if suelo_celda.sum() < 3:
        return np.zeros(len(xyz), dtype=bool)
    ci, cj = np.nonzero(suelo_celda)
    centros = origin + (np.column_stack([ci, cj]) + 0.5) * celda
    superficie = _interpolador(centros, zmin[ci, cj])
    zsup = superficie(xyz[:, :2])
    return np.abs(xyz[:, 2] - zsup) <= s.tolerancia_m


def _interpolador(xy: np.ndarray, z: np.ndarray):
    lineal = LinearNDInterpolator(xy, z) if len(xy) >= 3 else None
    cercano = NearestNDInterpolator(xy, z)

    def f(q: np.ndarray) -> np.ndarray:
        out = lineal(q) if lineal is not None else np.full(len(q), np.nan)
        falta = ~np.isfinite(out)
        if falta.any():
            out[falta] = cercano(q[falta])
        return out

    return f


def modelo_digital(xyz_suelo: np.ndarray, s: TerrainSettings) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Rejilla regular del terreno dentro de la envolvente de los puntos de suelo."""
    paso = s.malla_m
    xy = xyz_suelo[:, :2]
    lo = xy.min(axis=0)
    hi = xy.max(axis=0)
    while True:
        nx = int(np.floor((hi[0] - lo[0]) / paso)) + 1
        ny = int(np.floor((hi[1] - lo[1]) / paso)) + 1
        if nx * ny <= s.max_puntos_revit * 1.3 or paso > 50:
            break
        paso *= 1.25

    # Mediana de z por celda: reduce el ruido y el peso de las zonas muy densas.
    ij = _grid_index(xy, lo, paso)
    key = ij[:, 0] * (ny + 1) + ij[:, 1]
    orden = np.argsort(key, kind="stable")
    key_s = key[orden]
    z_s = xyz_suelo[orden, 2]
    cortes = np.flatnonzero(np.diff(key_s)) + 1
    grupos_z = np.split(z_s, cortes)
    claves = key_s[np.r_[0, cortes]]
    zmed = np.array([np.median(g) for g in grupos_z])
    ci, cj = claves // (ny + 1), claves % (ny + 1)
    muestras = lo + (np.column_stack([ci, cj]) + 0.5) * paso
    interp = _interpolador(muestras, zmed)

    gx, gy = np.meshgrid(lo[0] + np.arange(nx) * paso, lo[1] + np.arange(ny) * paso, indexing="ij")
    nodos = np.column_stack([gx.ravel(), gy.ravel()])
    dentro = Delaunay(muestras).find_simplex(nodos) >= 0 if len(muestras) >= 3 else np.zeros(len(nodos), bool)
    z = np.full(len(nodos), np.nan)
    z[dentro] = interp(nodos[dentro])
    valido = np.isfinite(z).reshape(nx, ny)

    # Triángulos: dos por cada cuadrado con sus 4 nodos válidos.
    idx = np.full(nx * ny, -1, dtype=np.int64)
    idx[valido.ravel()] = np.arange(int(valido.sum()))
    idx = idx.reshape(nx, ny)
    a, b, c, d = idx[:-1, :-1], idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:]
    ok = (a >= 0) & (b >= 0) & (c >= 0) & (d >= 0)
    caras = np.concatenate([
        np.column_stack([a[ok], b[ok], c[ok]]),
        np.column_stack([a[ok], c[ok], d[ok]]),
    ])
    return nodos[valido.ravel()], z[valido.ravel()], caras, paso


def detectar_terreno(nube: Nube, s: TerrainSettings) -> ResultadoTerreno | None:
    if len(nube) < 100:
        return None
    es_suelo, metodo = clasificar_suelo(nube, s)
    if es_suelo.sum() < 50:
        return None
    xy, z, caras, paso = modelo_digital(nube.xyz[es_suelo], s)
    if len(z) < 3:
        return None
    return ResultadoTerreno(es_suelo, xy, z, caras, paso, metodo)
