import numpy as np
from shapely.geometry import box

from scan2rvt import levels, sintetico, terrain


def test_niveles_y_forjados(demo, ajustes):
    r = levels.detectar_niveles(demo.escaner, ajustes.niveles)
    cotas = [z for _, z in r.niveles]
    assert np.allclose(cotas, [100.00, 103.30, 106.30], atol=0.02)

    (_, solera), (_, f1), (_, f2) = r.forjados
    assert not solera.medido
    assert f1.medido and abs((f1.z_superior - f1.z_inferior) - 0.30) < 0.02
    assert not f2.medido            # techo visto sólo desde abajo

    # La mesa a 0,75 m (2 m²) no genera ni superficie ni nivel.
    assert all(abs(s.z - 100.75) > 0.1 for s in r.superficies)


def test_contorno_forjado_con_hueco(demo, ajustes):
    r = levels.detectar_niveles(demo.escaner, ajustes.niveles)
    _, f1 = r.forjados[1]
    assert len(f1.poligonos) == 1
    p = f1.poligonos[0]
    bx0, by0 = sintetico.X0 + 20, sintetico.Y0 + 20
    hx0, hy0, hx1, hy1 = sintetico.ESCALERA
    real = box(bx0, by0, bx0 + sintetico.ANCHO, by0 + sintetico.FONDO).difference(
        box(bx0 + hx0, by0 + hy0, bx0 + hx1, by0 + hy1))
    assert len(p.interiors) == 1
    # Límite: resolución de la nube de demo (5 cm) + celda de contorno.
    assert p.hausdorff_distance(real) < 0.12
    assert abs(p.area - real.area) / real.area < 0.01


def test_terreno(demo, ajustes):
    r = terrain.detectar_terreno(demo.dron, ajustes.terreno)
    assert r is not None
    x, y, z = demo.dron.xyz.T
    suelo_real = np.abs(z - sintetico._terreno_z(x, y)) < 0.1
    assert (r.es_suelo == suelo_real).mean() > 0.98
    err = np.abs(r.rejilla_z - sintetico._terreno_z(r.rejilla_xy[:, 0], r.rejilla_xy[:, 1]))
    # Fuera de la huella del edificio el MDT debe cumplir la tolerancia de 2 cm en el 95 %.
    bx = (r.rejilla_xy[:, 0] - sintetico.X0 > 18) & (r.rejilla_xy[:, 0] - sintetico.X0 < 42)
    by = (r.rejilla_xy[:, 1] - sintetico.Y0 > 18) & (r.rejilla_xy[:, 1] - sintetico.Y0 < 34)
    fuera = ~(bx & by)
    assert np.percentile(err[fuera], 95) < 0.02
    assert len(r.caras) > 0


def test_terreno_usa_clasificacion_las(demo, ajustes):
    nube = demo.dron.subset(slice(None))
    x, y, z = nube.xyz.T
    nube.clase = np.where(np.abs(z - sintetico._terreno_z(x, y)) < 0.1, 2, 1).astype(np.uint8)
    r = terrain.detectar_terreno(nube, ajustes.terreno)
    assert "clase 2" in r.metodo
    assert (r.es_suelo == (nube.clase == 2)).all()


def test_sin_superficies(ajustes):
    from scan2rvt.cloud import Nube

    rng = np.random.default_rng(1)
    r = levels.detectar_niveles(Nube(rng.random((500, 3)) * 50), ajustes.niveles)
    assert r.niveles == [] and r.avisos
