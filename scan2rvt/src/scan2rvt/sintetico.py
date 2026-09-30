"""Nube sintética de un edificio sencillo, para pruebas y para la demo de la app.

Edificio de 20 × 12 m con dos plantas sobre un terreno en pendiente:
- Nivel 0 (solera) a 100,00; techo planta baja a 103,00.
- Forjado de 0,30 m → Nivel 1 a 103,30, con hueco de escalera de 2 × 3 m.
- Techo planta 1 a 106,00; cubierta (cara superior) a 106,30 vista por el dron.
Coordenadas tipo UTM para probar el desplazamiento de origen.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .cloud import DRON, ESCANER, Nube

X0, Y0 = 440_000.0, 4_474_000.0      # ~ Madrid, ETRS89 / UTM 30N
ANCHO, FONDO = 20.0, 12.0
COTAS = {"suelo0": 100.00, "techo0": 103.00, "suelo1": 103.30, "techo1": 106.00, "cubierta": 106.30}
ESCALERA = (2.0, 2.0, 4.0, 5.0)      # hueco en el forjado 1: x0, y0, x1, y1 (relativo)


@dataclass
class Demo:
    escaner: Nube
    dron: Nube


def _rejilla(x0, x1, y0, y1, paso):
    xs = np.arange(x0, x1, paso)
    ys = np.arange(y0, y1, paso)
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    return gx.ravel(), gy.ravel()


def _terreno_z(x, y):
    return 99.6 + 0.04 * (x - X0) + 0.02 * (y - Y0) + 0.15 * np.sin((x - X0) / 7.0)


def generar(paso_escaner: float = 0.05, paso_dron: float = 0.25, ruido: float = 0.003, seed: int = 0) -> Demo:
    rng = np.random.default_rng(seed)
    bx0, by0 = X0 + 20.0, Y0 + 20.0
    partes = []

    def horizontal(z, hueco=None):
        x, y = _rejilla(bx0, bx0 + ANCHO, by0, by0 + FONDO, paso_escaner)
        if hueco is not None:
            hx0, hy0, hx1, hy1 = hueco
            fuera = ~((x >= bx0 + hx0) & (x <= bx0 + hx1) & (y >= by0 + hy0) & (y <= by0 + hy1))
            x, y = x[fuera], y[fuera]
        partes.append(np.column_stack([x, y, np.full(x.shape, z)]))

    def muros(z0, z1):
        zs = np.arange(z0, z1, paso_escaner)
        for (xa, ya, xb, yb) in [(0, 0, ANCHO, 0), (ANCHO, 0, ANCHO, FONDO), (ANCHO, FONDO, 0, FONDO), (0, FONDO, 0, 0)]:
            L = np.hypot(xb - xa, yb - ya)
            t = np.arange(0, L, paso_escaner) / L
            T, Z = np.meshgrid(t, zs, indexing="ij")
            X = bx0 + xa + (xb - xa) * T
            Y = by0 + ya + (yb - ya) * T
            partes.append(np.column_stack([X.ravel(), Y.ravel(), Z.ravel()]))

    horizontal(COTAS["suelo0"])
    horizontal(COTAS["techo0"], ESCALERA)
    horizontal(COTAS["suelo1"], ESCALERA)
    horizontal(COTAS["techo1"])
    muros(COTAS["suelo0"], COTAS["techo0"])
    muros(COTAS["suelo1"], COTAS["techo1"])
    # Una mesa (debe ignorarse).
    x, y = _rejilla(bx0 + 10, bx0 + 12, by0 + 5, by0 + 6, paso_escaner)
    partes.append(np.column_stack([x, y, np.full(x.shape, COTAS["suelo0"] + 0.75)]))

    esc = np.concatenate(partes)
    esc += rng.normal(0, ruido, esc.shape)
    escaner = Nube(esc, origen=np.full(len(esc), 0, np.uint8), info={"archivo": "demo_escaner", "tipo": ESCANER})

    # Dron: terreno alrededor + cubierta del edificio.
    x, y = _rejilla(X0, X0 + 60, Y0 + 0, Y0 + 52, paso_dron)
    dentro = (x >= bx0) & (x <= bx0 + ANCHO) & (y >= by0) & (y <= by0 + FONDO)
    z = np.where(dentro, COTAS["cubierta"], _terreno_z(x, y))
    # Un árbol (vegetación, no es suelo).
    arbol = (np.hypot(x - (X0 + 50), y - (Y0 + 10)) < 2.0)
    z = np.where(arbol, z + 4.0, z)
    dr = np.column_stack([x, y, z]) + rng.normal(0, ruido * 5, (len(x), 3))
    dron = Nube(dr, origen=np.full(len(dr), 1, np.uint8), info={"archivo": "demo_dron", "tipo": DRON})
    return Demo(escaner, dron)
