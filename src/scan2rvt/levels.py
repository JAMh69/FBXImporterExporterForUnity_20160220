"""Detección de niveles y forjados a partir de las superficies horizontales.

1. Se estiman normales y se quedan los puntos de superficies horizontales.
2. Para cada franja de altura se mide la **superficie en planta ocupada**
   (celdas XY distintas, no nº de puntos: la densidad del escáner cambia con la
   distancia y falsearía el resultado).
3. Los picos de superficie son suelos o techos.
4. Un techo con un suelo justo encima (a un espesor razonable y solapados en
   planta) es un forjado: su cara superior define un nivel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage
from shapely.geometry import Polygon, box
from shapely.affinity import scale, translate
from shapely.ops import unary_union

from .cloud import Nube, normales, voxel_reduce
from .config import LevelSettings

ESPESOR_DEFECTO = 0.30
HUECO_MIN_M2 = 1.0


@dataclass
class Superficie:
    z: float
    area_m2: float
    celdas: set = field(repr=False)   # celdas XY (i, j) ocupadas


@dataclass
class ForjadoDetectado:
    z_inferior: float
    z_superior: float
    poligonos: list[Polygon]
    medido: bool


@dataclass
class ResultadoNiveles:
    niveles: list[tuple[str, float]]         # (nombre, cota absoluta)
    forjados: list[tuple[int, ForjadoDetectado]]  # (índice de nivel, forjado)
    superficies: list[Superficie]
    avisos: list[str]


def puntos_horizontales(nube: Nube, s: LevelSettings) -> np.ndarray:
    red = voxel_reduce(nube, s.voxel_m)
    nz = np.abs(normales(red.xyz)[:, 2])
    return red.xyz[nz > 0.95]


def detectar_superficies(xyz: np.ndarray, s: LevelSettings) -> list[Superficie]:
    if len(xyz) == 0:
        return []
    z0 = xyz[:, 2].min()
    zb = np.floor((xyz[:, 2] - z0) / s.bin_m).astype(np.int64)
    celda = np.floor(xyz[:, :2] / s.celda_area_m).astype(np.int64)
    cmin = celda.min(axis=0)
    celda -= cmin
    ncy = int(celda[:, 1].max()) + 1
    ckey = celda[:, 0] * ncy + celda[:, 1]
    nb = int(zb.max()) + 3

    # Superficie ocupada en una ventana de ±1 franja (absorbe el ruido de medida).
    bins = np.concatenate([zb - 1, zb, zb + 1]) + 1
    keys = np.concatenate([ckey, ckey, ckey])
    par = np.unique(bins * (ckey.max() + 1) + keys)
    area = np.bincount(par // (ckey.max() + 1), minlength=nb).astype(float) * s.celda_area_m**2

    # Picos: máximos locales en ±0,10 m.
    r = max(1, int(round(0.10 / s.bin_m)))
    maxf = ndimage.maximum_filter1d(area, size=2 * r + 1, mode="constant")
    umbral = max(s.area_min_m2, s.area_rel_min * area.max())
    picos = np.flatnonzero((area == maxf) & (area >= umbral))
    # Mesetas de igual valor: quedarse con un pico por meseta.
    picos = [p for i, p in enumerate(picos) if i == 0 or p - picos[i - 1] > r]

    sup: list[Superficie] = []
    for p in picos:
        zc = z0 + (p - 1 + 0.5) * s.bin_m
        sel = np.abs(xyz[:, 2] - zc) <= 0.04
        if sel.sum() < 10:
            continue
        zr = float(np.median(xyz[sel, 2]))
        sel = np.abs(xyz[:, 2] - zr) <= 0.03
        c = celda[sel] + cmin
        celdas = set(map(tuple, np.unique(c, axis=0).tolist()))
        sup.append(Superficie(zr, len(celdas) * s.celda_area_m**2, celdas))
    return sup


def _solape(a: Superficie, b: Superficie) -> float:
    inter = len(a.celdas & b.celdas)
    return inter / max(1, min(len(a.celdas), len(b.celdas)))


def _poligonos(xy: np.ndarray, celda_m: float) -> list[Polygon]:
    """Puntos de una superficie → polígonos con huecos.

    Se rasteriza a ``celda_m``, se cierran los vacíos por oclusión (muebles,
    personas) de hasta ~0,5 m y se obtiene el contorno de las celdas llenas,
    corregido media celda hacia dentro (error típico ≤ media celda).
    """
    if len(xy) < 10:
        return []
    pad = max(1, int(round(0.25 / celda_m))) + 2
    ij = np.floor(xy / celda_m).astype(np.int64)
    cmin = ij.min(axis=0) - pad
    ij -= cmin
    nx, ny = ij.max(axis=0) + pad + 1
    img = np.zeros((ny, nx), dtype=bool)          # filas = y, columnas = x
    img[ij[:, 1], ij[:, 0]] = True
    cuadrado = np.ones((3, 3), dtype=bool)          # conserva las esquinas en ángulo recto
    img = ndimage.binary_closing(img, structure=cuadrado, iterations=pad - 2)
    img = ndimage.binary_opening(img, structure=cuadrado, iterations=1)   # quita salientes de una celda (ruido)
    lleno = ndimage.binary_fill_holes(img)
    lab, n = ndimage.label(lleno & ~img)
    if n:
        tam = ndimage.sum_labels(np.ones_like(lab), lab, index=np.arange(1, n + 1)) * celda_m**2
        pequenos = np.flatnonzero(tam < HUECO_MIN_M2) + 1
        img |= np.isin(lab, pequenos)
    # Polígono exacto de las celdas llenas (una caja por tramo continuo de cada fila).
    # Se construye en unidades enteras de celda para que las cajas encajen sin rendijas.
    cajas = []
    for fila in range(ny):
        v = np.flatnonzero(np.diff(np.r_[0, img[fila].astype(np.int8), 0]))
        for a, b in zip(v[::2], v[1::2]):
            cajas.append(box(int(a), fila, int(b), fila + 1))
    # Las celdas del borde sobresalen de los puntos media celda de media: se compensa.
    geom = unary_union(cajas).buffer(-0.5, join_style="mitre").simplify(1.0, preserve_topology=True)
    geom = scale(geom, celda_m, celda_m, origin=(0, 0))
    geom = translate(geom, cmin[0] * celda_m, cmin[1] * celda_m)
    polys = [g for g in ([geom] if isinstance(geom, Polygon) else list(getattr(geom, "geoms", []))) if g.area >= 1.0]
    return polys


def _xy_superficie(nube: Nube, z: float) -> np.ndarray:
    return nube.xyz[np.abs(nube.xyz[:, 2] - z) <= 0.03, :2]


def detectar_niveles(nube: Nube, s: LevelSettings) -> ResultadoNiveles:
    avisos: list[str] = []
    xyz = puntos_horizontales(nube, s)
    sup = sorted(detectar_superficies(xyz, s), key=lambda t: t.z)
    if not sup:
        return ResultadoNiveles([], [], [], ["No se han encontrado superficies horizontales suficientes."])

    niveles: list[tuple[str, float]] = []
    forjados: list[tuple[int, ForjadoDetectado]] = []
    usados: set[int] = set()

    def pareja(i: int) -> int | None:
        for j in range(i + 1, len(sup)):
            dz = sup[j].z - sup[i].z
            if dz > s.forjado_max_m:
                break
            if dz >= s.forjado_min_m and _solape(sup[i], sup[j]) >= 0.3:
                return j
        return None

    # Suelo más bajo = Nivel 0 (solera: sólo se ve la cara superior).
    suelo = 0
    niveles.append(("Nivel 0", sup[0].z))
    forjados.append((0, ForjadoDetectado(sup[0].z - ESPESOR_DEFECTO, sup[0].z,
                                         _poligonos(_xy_superficie(nube, sup[0].z), s.celda_contorno_m), medido=False)))
    usados.add(0)

    i = 1
    while i < len(sup):
        if i in usados:
            i += 1
            continue
        altura = sup[i].z - sup[suelo].z
        j = pareja(i)
        if altura < s.altura_libre_min_m and j is None:
            avisos.append(f"Superficie horizontal a {altura:.2f} m sobre {niveles[-1][0]} ignorada (¿mueble, altillo, escalón?).")
            i += 1
            continue
        if j is not None:
            xy = np.concatenate([_xy_superficie(nube, sup[i].z), _xy_superficie(nube, sup[j].z)])
            f = ForjadoDetectado(sup[i].z, sup[j].z, _poligonos(xy, s.celda_contorno_m), medido=True)
            usados.update({i, j})
            suelo = j
            i = j + 1
        else:
            # Techo sin suelo encima (p. ej. último forjado visto sólo desde abajo).
            f = ForjadoDetectado(sup[i].z, sup[i].z + ESPESOR_DEFECTO, _poligonos(_xy_superficie(nube, sup[i].z), s.celda_contorno_m), medido=False)
            avisos.append(f"Forjado a {sup[i].z:.2f} m visto sólo por una cara: espesor supuesto {ESPESOR_DEFECTO:.2f} m.")
            usados.add(i)
            suelo = i
            i += 1
        niveles.append((f"Nivel {len(niveles)}", f.z_superior))
        forjados.append((len(niveles) - 1, f))

    return ResultadoNiveles(niveles, forjados, sup, avisos)
