"""Nube de puntos en memoria y operaciones básicas (submuestreo, ruido, unión)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Origen de las nubes (para saber qué sirve para terreno y qué para interiores).
ESCANER = "escaner"
DRON = "dron"

_BITS = 21
_MASK = (1 << _BITS) - 1


@dataclass
class Nube:
    xyz: np.ndarray                          # (N, 3) float64, coordenadas absolutas en metros
    rgb: np.ndarray | None = None            # (N, 3) uint8
    intensidad: np.ndarray | None = None     # (N,) float32
    clase: np.ndarray | None = None          # (N,) uint8, clasificación LAS
    origen: np.ndarray | None = None         # (N,) uint8: 0 = escáner, 1 = dron
    info: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return int(self.xyz.shape[0])

    def subset(self, mask_or_idx) -> "Nube":
        def pick(a):
            return None if a is None else a[mask_or_idx]

        return Nube(
            xyz=self.xyz[mask_or_idx],
            rgb=pick(self.rgb),
            intensidad=pick(self.intensidad),
            clase=pick(self.clase),
            origen=pick(self.origen),
            info=dict(self.info),
        )

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return self.xyz.min(axis=0), self.xyz.max(axis=0)

    def to_o3d(self):
        import open3d as o3d

        pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(self.xyz))
        if self.rgb is not None:
            pc.colors = o3d.utility.Vector3dVector(self.rgb.astype(np.float64) / 255.0)
        return pc


def _voxel_keys(xyz: np.ndarray, voxel: float, origin: np.ndarray) -> np.ndarray:
    k = np.floor((xyz - origin) / voxel).astype(np.int64)
    if k.min() < 0 or k.max() > _MASK:
        raise ValueError("La nube es demasiado grande para el tamaño de vóxel elegido")
    return k[:, 0] | (k[:, 1] << _BITS) | (k[:, 2] << (2 * _BITS))


def voxel_reduce(nube: Nube, voxel: float, origin: np.ndarray | None = None) -> Nube:
    """Un punto por vóxel: el centroide (más preciso que quedarse con uno cualquiera)."""
    if len(nube) == 0 or voxel <= 0:
        return nube
    if origin is None:
        origin = np.floor(nube.xyz.min(axis=0))
    keys = _voxel_keys(nube.xyz, voxel, origin)
    uniq, first, inv, counts = np.unique(keys, return_index=True, return_inverse=True, return_counts=True)
    n = uniq.shape[0]
    xyz = np.empty((n, 3), dtype=np.float64)
    for c in range(3):
        xyz[:, c] = np.bincount(inv, weights=nube.xyz[:, c], minlength=n) / counts
    rgb = None
    if nube.rgb is not None:
        rgb = np.empty((n, 3), dtype=np.uint8)
        for c in range(3):
            rgb[:, c] = np.round(np.bincount(inv, weights=nube.rgb[:, c], minlength=n) / counts).astype(np.uint8)
    inten = None
    if nube.intensidad is not None:
        inten = (np.bincount(inv, weights=nube.intensidad, minlength=n) / counts).astype(np.float32)
    return Nube(
        xyz=xyz,
        rgb=rgb,
        intensidad=inten,
        clase=None if nube.clase is None else nube.clase[first],
        origen=None if nube.origen is None else nube.origen[first],
        info=dict(nube.info),
    )


def merge(nubes: list[Nube]) -> Nube:
    nubes = [n for n in nubes if n is not None and len(n) > 0]
    if not nubes:
        return Nube(xyz=np.zeros((0, 3)))

    def cat(attr, dtype, width=None):
        if all(getattr(n, attr) is None for n in nubes):
            return None
        parts = []
        for n in nubes:
            a = getattr(n, attr)
            if a is None:
                shape = (len(n), width) if width else (len(n),)
                a = np.zeros(shape, dtype=dtype)
            parts.append(a.astype(dtype, copy=False))
        return np.concatenate(parts)

    return Nube(
        xyz=np.concatenate([n.xyz for n in nubes]),
        rgb=cat("rgb", np.uint8, 3),
        intensidad=cat("intensidad", np.float32),
        clase=cat("clase", np.uint8),
        origen=cat("origen", np.uint8),
        info={"fuentes": [n.info for n in nubes]},
    )


def remove_outliers(nube: Nube, vecinos: int = 16, sigma: float = 2.5) -> Nube:
    """Filtro estadístico: quita puntos aislados (ruido del escáner, reflejos, pájaros...)."""
    if len(nube) < vecinos * 2:
        return nube
    _, idx = nube.to_o3d().remove_statistical_outlier(nb_neighbors=vecinos, std_ratio=sigma)
    return nube.subset(np.asarray(idx, dtype=np.int64))
