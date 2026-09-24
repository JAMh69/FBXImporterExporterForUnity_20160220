"""Nube limpia (sin ruido, submuestreada) en LAS/LAZ, con el terreno clasificado (clase 2)."""

from __future__ import annotations

from pathlib import Path

import laspy
import numpy as np

from ..cloud import Nube

CLASE_NO_CLASIFICADO = 1
CLASE_SUELO = 2


def exportar(nube: Nube, ruta: Path, es_suelo: np.ndarray | None = None) -> Path:
    header = laspy.LasHeader(point_format=3 if nube.rgb is not None else 1, version="1.4")
    header.offsets = np.floor(nube.xyz.min(axis=0))
    header.scales = np.array([0.001, 0.001, 0.001])
    las = laspy.LasData(header)
    las.x, las.y, las.z = nube.xyz[:, 0], nube.xyz[:, 1], nube.xyz[:, 2]
    clase = np.full(len(nube), CLASE_NO_CLASIFICADO, dtype=np.uint8)
    if nube.clase is not None:
        clase = nube.clase.copy()
    if es_suelo is not None:
        clase[es_suelo] = CLASE_SUELO
    las.classification = clase
    if nube.intensidad is not None:
        las.intensity = np.clip(nube.intensidad, 0, 65535).astype(np.uint16)
    if nube.rgb is not None:
        rgb16 = nube.rgb.astype(np.uint16) * 257
        las.red, las.green, las.blue = rgb16[:, 0], rgb16[:, 1], rgb16[:, 2]
    las.write(ruta)
    return ruta
