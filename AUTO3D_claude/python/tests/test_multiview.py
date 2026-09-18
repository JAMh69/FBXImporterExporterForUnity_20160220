"""Triangulacion, propagacion y ajuste de planos con poses conocidas."""
import numpy as np
import pytest

from vision_teach import multiview as mv
from tests import multiview_scene as ms


@pytest.fixture(scope='module')
def cameras():
    return ms.orbit()


def test_camera_centre_and_projection_agree(cameras):
    for camera in cameras:
        pixels, ahead = camera.project(camera.centre + camera.rotation[2] * 10.)
        assert ahead[0], 'un punto delante del objetivo debe dar profundidad positiva'
        assert np.allclose(pixels[0], camera.principal, atol=1e-6)


def test_ray_is_the_inverse_of_project(cameras):
    camera = cameras[0]
    point = np.array([3., -2., 6.])
    pixel = camera.project(point)[0][0]
    direction = camera.ray(pixel)
    distance = np.linalg.norm(point - camera.centre)
    assert np.allclose(camera.centre + direction * distance, point, atol=1e-6)


def test_triangulation_is_exact_without_noise(cameras):
    for truth in ms.ROOF_SLOPE:
        marks = [c.project(truth)[0][0] for c in cameras]
        point = mv.triangulate(cameras, marks)
        assert np.linalg.norm(point - truth) < 1e-6


def test_triangulation_with_pixel_noise(cameras):
    """Con marcas humanas el error no es cero: se mide cuanto cuesta.

    Dos pixeles de error al marcar es realista con el raton sobre una foto de
    4000 px. Lo que importa es que el error en metros sea pequeño frente a lo
    que se quiere medir (un edificio de 20 m).
    """
    rng = np.random.default_rng(0)
    errors = []
    for truth in np.vstack([ms.FOOTPRINT, ms.ROOF_SLOPE]):
        marks = [c.project(truth)[0][0] + rng.normal(0, 2., 2) for c in cameras]
        errors.append(np.linalg.norm(mv.triangulate(cameras, marks) - truth))
    errors = np.asarray(errors)
    assert errors.mean() < .05, f'error medio {errors.mean():.3f} m'
    assert errors.max() < .15, f'error maximo {errors.max():.3f} m'


def test_two_views_are_enough(cameras):
    truth = ms.ROOF_SLOPE[2]
    pair = [cameras[0], cameras[2]]
    marks = [c.project(truth)[0][0] for c in pair]
    assert np.linalg.norm(mv.triangulate(pair, marks) - truth) < 1e-6


def test_a_short_baseline_is_worse_than_a_long_one():
    """Dos tomas casi desde el mismo sitio no triangulan bien, y conviene que
    la interfaz lo sepa para pedirle al usuario que marque en una foto lejana."""
    truth = np.array([4., 2., 9.])
    rng = np.random.default_rng(1)
    def error(sweep):
        pair = ms.orbit(count=2, sweep=sweep)
        marks = [c.project(truth)[0][0] + rng.normal(0, 2., 2) for c in pair]
        return np.linalg.norm(mv.triangulate(pair, marks) - truth)
    corto = np.median([error(2.) for _ in range(20)])
    largo = np.median([error(90.) for _ in range(20)])
    assert largo < corto / 5, f'base corta {corto:.3f} m, base larga {largo:.3f} m'


def test_reprojection_error_flags_a_bad_mark(cameras):
    truth = ms.ROOF_SLOPE[0]
    marks = [c.project(truth)[0][0] for c in cameras]
    marks[3] = marks[3] + np.array([250., -180.])         # una marca puesta mal
    point = mv.triangulate(cameras, marks)
    errors = mv.reprojection_error(cameras, marks, point)
    assert errors[3] == errors.max()
    assert errors[3] > 20., 'una marca claramente mal debe destacar'


def test_polygon_triangulates_and_reports_error(cameras):
    polygons = [[c.project(p)[0][0] for p in ms.ROOF_SLOPE] for c in cameras]
    points, errors = mv.triangulate_polygon(cameras, polygons)
    assert points.shape == (4, 3)
    assert np.allclose(points, ms.ROOF_SLOPE, atol=1e-6)
    assert errors.max() < 1e-3


def test_polygon_rejects_mismatched_vertices(cameras):
    polygons = [[c.project(p)[0][0] for p in ms.ROOF_SLOPE] for c in cameras]
    polygons[1] = polygons[1][:3]
    with pytest.raises(ValueError, match='vertices'):
        mv.triangulate_polygon(cameras, polygons)


def test_propagation_lands_where_it_should(cameras):
    """Marcar una vez y que aparezca en las demas fotos: lo que sustituye al
    seguimiento fotograma a fotograma."""
    spread = mv.propagate(ms.ROOF_SLOPE, cameras)
    assert len(spread) >= 4, 'el tejado deberia verse desde varias tomas'
    for camera in cameras:
        if camera.name not in spread:
            continue
        truth = np.array([camera.project(p)[0][0] for p in ms.ROOF_SLOPE])
        assert np.allclose(spread[camera.name], truth, atol=1e-6)


def test_propagation_skips_cameras_that_do_not_see_it():
    lejos = ms.look_at((500., 500., 40.), (500., 520., 0.), name='LEJOS.JPG')
    cerca = ms.orbit(count=3)
    spread = mv.propagate(ms.FOOTPRINT, cerca + [lejos])
    assert 'LEJOS.JPG' not in spread


def test_plane_fits_a_roof_slope():
    rng = np.random.default_rng(2)
    # muestrear el faldon y añadir 2 cm de ruido, como una nube de puntos real
    us = rng.uniform(0, 1, 200)[:, None]
    vs = rng.uniform(0, 1, 200)[:, None]
    a, b, c = ms.ROOF_SLOPE[0], ms.ROOF_SLOPE[1], ms.ROOF_SLOPE[3]
    points = a + us * (b - a) + vs * (c - a) + rng.normal(0, .02, (200, 3))
    normal, offset, residuals, inliers = mv.fit_plane(points, threshold=.08)
    assert inliers.mean() > .9
    assert np.abs(residuals[inliers]).max() < .1
    # el faldon sube 3 m en 5 m de vuelo -> 30.96 grados
    assert mv.plane_angle(normal) == pytest.approx(np.degrees(np.arctan2(3., 5.)), abs=1.)


def test_plane_angle_names_the_obvious_cases():
    assert mv.plane_angle([0., 0., 1.]) == pytest.approx(0., abs=1e-6)    # horizontal
    assert mv.plane_angle([1., 0., 0.]) == pytest.approx(90., abs=1e-6)   # vertical
    assert mv.plane_angle([0., -1., 0.]) == pytest.approx(90., abs=1e-6)


def test_plane_ignores_outliers():
    rng = np.random.default_rng(3)
    points = np.column_stack([rng.uniform(-5, 5, 120), rng.uniform(-5, 5, 120),
                              np.full(120, 3.)]) + rng.normal(0, .01, (120, 3))
    points[:20, 2] += 6.                                   # 20 puntos de una chimenea
    normal, offset, _, inliers = mv.fit_plane(points, threshold=.1)
    assert inliers.sum() == 100
    assert mv.plane_angle(normal) == pytest.approx(0., abs=.5)
