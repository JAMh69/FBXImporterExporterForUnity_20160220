"""Detección de muros: superficies verticales vistas en planta como líneas (RANSAC).

Para cada planta (entre el suelo terminado y la cara inferior del forjado superior):
1. Se quedan los puntos de superficies verticales (normal casi horizontal).
2. Se buscan líneas en planta por RANSAC secuencial; los puntos de cada línea se
   parten en tramos donde haya huecos mayores de ``hueco_max_m``.
3. Un tramo es muro si es largo, tiene puntos suficientes y cubre parte de la altura libre
   (así una mesa o una estantería no cuentan).

Limitaciones (v1): el eje del muro es la **cara vista**, no el eje real; el espesor es un
supuesto; no se detectan huecos (puertas y ventanas) ni muros curvos.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .cloud import Nube, normales, voxel_reduce
from .config import LevelSettings, WallSettings
from .levels import ResultadoNiveles


@dataclass
class MuroDetectado:
    nivel_idx: int
    p0: tuple[float, float]      # coordenadas absolutas
    p1: tuple[float, float]
    z_base: float
    altura: float
    espesor: float
    confianza: float


def _mejor_linea(xy: np.ndarray, s: WallSettings, rng: np.random.Generator):
    n = len(xy)
    sub = xy if n <= s.muestra_max else xy[rng.choice(n, s.muestra_max, replace=False)]
    mejor = None
    for _ in range(s.iteraciones):
        i, j = rng.choice(len(sub), 2, replace=False)
        a, d = sub[i], sub[j] - sub[i]
        largo = float(np.hypot(*d))
        if largo < s.longitud_min_m:
            continue
        normal = np.array([-d[1], d[0]]) / largo
        cuenta = int((np.abs((sub - a) @ normal) < s.tol_m).sum())
        if mejor is None or cuenta > mejor[0]:
            mejor = (cuenta, a, d / largo)
    return mejor


def _lineas_planta(xy: np.ndarray, z: np.ndarray, z0: float, altura: float, s: WallSettings,
                   rng: np.random.Generator):
    """Devuelve [(p0, p1, confianza)] para una planta."""
    restantes = np.arange(len(xy))
    out = []
    for _ in range(s.max_por_nivel):
        if len(restantes) < s.puntos_min:
            break
        m = _mejor_linea(xy[restantes], s, rng)
        if m is None:
            break
        _, a, u = m
        normal = np.array([-u[1], u[0]])
        inl = restantes[np.abs((xy[restantes] - a) @ normal) < s.tol_m]
        if len(inl) < s.puntos_min:
            break
        # Ajuste fino por mínimos cuadrados (PCA) y nuevo recuento.
        c = xy[inl].mean(axis=0)
        u = np.linalg.svd(xy[inl] - c, full_matrices=False)[2][0]
        normal = np.array([-u[1], u[0]])
        inl = restantes[np.abs((xy[restantes] - c) @ normal) < s.tol_m]
        restantes = np.setdiff1d(restantes, inl, assume_unique=True)

        t = (xy[inl] - c) @ u
        orden = np.argsort(t)
        t, zi = t[orden], z[inl][orden]
        cortes = np.flatnonzero(np.diff(t) > s.hueco_max_m) + 1
        for tramo_t, tramo_z in zip(np.split(t, cortes), np.split(zi, cortes)):
            largo = float(tramo_t[-1] - tramo_t[0])
            if len(tramo_t) < s.puntos_min or largo < s.longitud_min_m:
                continue
            if (tramo_z.max() - tramo_z.min()) < s.cobertura_z_min * altura:
                continue
            esperados = largo * altura / (s.voxel_m ** 2)
            conf = float(min(1.0, len(tramo_t) / max(1.0, esperados)))
            out.append((tuple(c + u * tramo_t[0]), tuple(c + u * tramo_t[-1]), conf))
    return out


def _cortar(a0, a1, b0, b1):
    """Intersección de las rectas a0-a1 y b0-b1 (None si son casi paralelas)."""
    da = np.subtract(a1, a0)
    db = np.subtract(b1, b0)
    den = da[0] * db[1] - da[1] * db[0]
    if abs(den) < 1e-6 * np.hypot(*da) * np.hypot(*db):
        return None
    t = ((b0[0] - a0[0]) * db[1] - (b0[1] - a0[1]) * db[0]) / den
    return np.asarray(a0) + t * da


def ajustar_esquinas(muros: list[MuroDetectado], radio_m: float = 0.30) -> None:
    """Une los extremos de muros que casi se encuentran en la intersección de sus rectas."""
    for a in range(len(muros)):
        for b in range(a + 1, len(muros)):
            ma, mb = muros[a], muros[b]
            if ma.nivel_idx != mb.nivel_idx:
                continue
            p = _cortar(ma.p0, ma.p1, mb.p0, mb.p1)
            if p is None:
                continue
            ea = min(("p0", "p1"), key=lambda e: np.hypot(*(np.subtract(getattr(ma, e), p))))
            eb = min(("p0", "p1"), key=lambda e: np.hypot(*(np.subtract(getattr(mb, e), p))))
            if (np.hypot(*np.subtract(getattr(ma, ea), p)) <= radio_m
                    and np.hypot(*np.subtract(getattr(mb, eb), p)) <= radio_m):
                setattr(ma, ea, (float(p[0]), float(p[1])))
                setattr(mb, eb, (float(p[0]), float(p[1])))


def detectar_muros(nube: Nube, res: ResultadoNiveles, s: WallSettings,
                   niv: LevelSettings) -> tuple[list[MuroDetectado], list[str]]:
    avisos: list[str] = []
    if len(res.niveles) < 2:
        return [], ["Sin al menos dos niveles no se pueden detectar muros."]
    forj = {i: f for i, f in res.forjados}
    red = voxel_reduce(nube, s.voxel_m)
    verticales = red.xyz[np.abs(normales(red.xyz)[:, 2]) < 0.3]
    rng = np.random.default_rng(0)
    muros: list[MuroDetectado] = []

    for k in range(len(res.niveles) - 1):
        z0, z1 = forj[k].z_superior, forj[k + 1].z_inferior
        altura = z1 - z0
        if altura < niv.altura_libre_min_m:
            avisos.append(f"{res.niveles[k][0]}: altura libre {altura:.2f} m demasiado pequeña, sin muros.")
            continue
        m = (verticales[:, 2] > z0 + s.margen_z_m) & (verticales[:, 2] < z1 - s.margen_z_m)
        pts = verticales[m]
        for p0, p1, conf in _lineas_planta(pts[:, :2], pts[:, 2], z0, altura, s, rng):
            muros.append(MuroDetectado(k, p0, p1, z0, altura, s.espesor_defecto_m, conf))

    ajustar_esquinas(muros)
    if muros:
        avisos.append(f"Muros: {len(muros)} detectados. El eje es la cara vista por el escáner y el espesor "
                      f"({s.espesor_defecto_m:.2f} m) es un supuesto; sin puertas ni ventanas todavía.")
        bajos = sum(1 for m in muros if m.confianza < 0.3)
        if bajos:
            avisos.append(f"{bajos} muros con poca cobertura de puntos (confianza < 0,3): revisar.")
    else:
        avisos.append("No se han detectado muros.")
    return muros, avisos
