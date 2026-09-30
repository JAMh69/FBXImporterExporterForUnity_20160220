import numpy as np
import pytest

from scan2rvt import levels, muros, sintetico
from scan2rvt.cloud import Nube
from scan2rvt.config import Settings


@pytest.fixture(scope="module")
def detectados(demo):
    a = Settings()
    r = levels.detectar_niveles(demo.escaner, a.niveles)
    m, av = muros.detectar_muros(demo.escaner, r, a.muros, a.niveles)
    return m, av


def test_ocho_muros_con_medidas_reales(detectados):
    m, _ = detectados
    assert len(m) == 8
    for k, altura, z in ((0, 3.0, 100.0), (1, 2.7, 103.3)):
        de_planta = [x for x in m if x.nivel_idx == k]
        assert len(de_planta) == 4
        largos = sorted(round(float(np.hypot(x.p1[0] - x.p0[0], x.p1[1] - x.p0[1])), 1) for x in de_planta)
        assert largos == [12.0, 12.0, 20.0, 20.0]
        assert all(abs(x.altura - altura) < 0.03 and abs(x.z_base - z) < 0.03 for x in de_planta)


def test_esquinas_cerradas(detectados):
    """Los extremos de cada planta coinciden por parejas: perímetro cerrado de 20 × 12 m."""
    m, _ = detectados
    bx, by = sintetico.X0 + 20, sintetico.Y0 + 20
    for k in (0, 1):
        esquinas = sorted({(round(p[0] - bx, 1), round(p[1] - by, 1))
                           for x in m if x.nivel_idx == k for p in (x.p0, x.p1)})
        assert esquinas == [(0.0, 0.0), (0.0, 12.0), (20.0, 0.0), (20.0, 12.0)]


def test_la_mesa_no_es_muro(detectados):
    m, _ = detectados
    bx, by = sintetico.X0 + 20, sintetico.Y0 + 20
    # La mesa está en x 10-12, y 5-6: ningún muro atraviesa esa zona.
    for x in m:
        medio = (np.array(x.p0) + np.array(x.p1)) / 2 - [bx, by]
        assert not (9 < medio[0] < 13 and 4 < medio[1] < 7)


def test_muro_con_poca_cobertura_baja_la_confianza(demo):
    """Un muro al que le falta la mitad de los puntos sigue detectándose, con menos confianza."""
    a = Settings()
    xyz = demo.escaner.xyz
    bx, by = sintetico.X0 + 20, sintetico.Y0 + 20
    en_muro_sur = (np.abs(xyz[:, 1] - by) < 0.02) & (xyz[:, 2] > 100.3) & (xyz[:, 2] < 102.7)
    mitad = en_muro_sur & (np.arange(len(xyz)) % 2 == 0)
    nube = Nube(xyz[~mitad], origen=None, info={})
    r = levels.detectar_niveles(nube, a.niveles)
    m, _ = muros.detectar_muros(nube, r, a.muros, a.niveles)
    sur = [x for x in m if x.nivel_idx == 0 and abs(x.p0[1] - by) < 0.1 and abs(x.p1[1] - by) < 0.1]
    otros = [x for x in m if x.nivel_idx == 0 and x not in sur]
    assert len(sur) == 1
    assert sur[0].confianza < 0.8 * min(x.confianza for x in otros)


def test_sin_muros_en_ruido(ajustes):
    rng = np.random.default_rng(1)
    nube = Nube(rng.random((5000, 3)) * [30, 30, 8])
    r = levels.detectar_niveles(nube, ajustes.niveles)
    m, av = muros.detectar_muros(nube, r, ajustes.muros, ajustes.niveles)
    assert m == [] and av
