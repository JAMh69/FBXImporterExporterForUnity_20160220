"""Verificacion de geometria y seguimiento contra una escena de verdad conocida."""
import numpy as np
import pytest

from vision_teach import geometry, tracking
from tests import scene


@pytest.fixture(scope='module')
def frame():
    return scene.render()


@pytest.fixture(scope='module')
def detected(frame):
    segs, edges = geometry.segments(frame, 60, 150)
    found = geometry.vanishing_points(segs)
    return segs, edges, found


def test_segments_are_straight_and_long(detected):
    segs, _, _ = detected
    assert len(segs) >= 20
    lengths = np.linalg.norm(segs[:, 2:] - segs[:, :2], axis=1)
    assert lengths.min() >= 26.


def test_finds_at_least_two_vanishing_points(detected):
    _, _, found = detected
    assert len(found) >= 2
    assert found[0]['weight'] >= found[-1]['weight']       # ordenados por peso


@pytest.mark.parametrize('yaw', [20., 24., 28., 32., 36., 40.])
def test_focal_from_several_viewpoints(yaw):
    """Medido sobre seis puntos de vista: entre 0.6 % y 2.5 % de error.

    El margen de 4 % deja holgura para el ruido de la escena sin dejar pasar
    una regresion real. La version JavaScript equivalente daba un 8 %: la
    diferencia esta en el Canny y el trazado de contornos de OpenCV, que
    producen segmentos mas limpios para el RANSAC.
    """
    segs, _ = geometry.segments(scene.render(yaw_deg=yaw), 60, 150)
    calibration = geometry.calibrate(geometry.vanishing_points(segs),
                                     scene.WIDTH, scene.HEIGHT)
    assert calibration is not None, 'no se ha podido calibrar'
    assert abs(calibration['focal'] - scene.FOCAL) / scene.FOCAL < .04


def test_horizon_close_to_truth(detected):
    _, _, found = detected
    calibration = geometry.calibrate(found, scene.WIDTH, scene.HEIGHT)
    y = geometry.horizon_y(geometry.horizon(found, calibration), scene.WIDTH)
    truth = scene.HEIGHT / 2 + scene.FOCAL * np.tan(scene.PITCH)
    # medido sobre seis puntos de vista: 1.9 a 8.1 px, media 5.1. El error ya
    # no viene de la focal (0.6-2.5 %) sino de la direccion vertical estimada.
    # Forzar el horizonte a pasar por el punto de fuga horizontal no mejora
    # nada: se comprobo, y resulta ser la misma recta por construccion
    assert abs(y - truth) < 10.


def test_plane_candidates_are_supported_by_edges(detected):
    segs, edges, found = detected
    group = geometry.labels(segs, found)
    candidates = geometry.plane_candidates(segs, group, edges)
    assert candidates, 'no se ha propuesto ningun plano'
    assert all(c['score'] >= .42 for c in candidates)
    assert candidates[0]['corners'].shape == (4, 2)


def test_facade_reconstruction_is_exact():
    """Con calibracion exacta la fachada de 12 x 11 m debe salir a 12 x 11 m."""
    calibration = scene.truth_calibration()
    result = geometry.reconstruct(scene.project(scene.FACADE),
                                  geometry.VERTICAL, calibration, 1.6)
    assert 'error' not in result, result.get('error')
    sides = scene.side_lengths(result['points'])
    assert sides[0] == pytest.approx(12., abs=.01)
    assert sides[1] == pytest.approx(11., abs=.01)
    assert sides[2] == pytest.approx(12., abs=.01)
    assert sides[3] == pytest.approx(11., abs=.01)


def test_ground_reconstruction_is_exact():
    calibration = scene.truth_calibration()
    result = geometry.reconstruct(scene.project(scene.GROUND_PATCH),
                                  geometry.HORIZONTAL, calibration, 1.6)
    assert 'error' not in result, result.get('error')
    sides = scene.side_lengths(result['points'])
    assert sides[0] == pytest.approx(12., abs=.01)
    assert sides[1] == pytest.approx(12., abs=.01)
    # el suelo esta a la altura de camara por debajo del origen
    assert result['points'] @ calibration['up'] == pytest.approx(-1.6, abs=1e-6)


def test_world_coordinates_keep_the_vertical():
    calibration = scene.truth_calibration()
    result = geometry.reconstruct(scene.project(scene.FACADE),
                                  geometry.VERTICAL, calibration, 1.6)
    world = geometry.to_world(calibration, result['points'])
    assert world[:, 1].min() == pytest.approx(-1.6, abs=.01)     # base en el suelo
    assert world[:, 1].max() == pytest.approx(9.4, abs=.01)      # 11 m mas arriba


def test_reconstruction_refuses_sky():
    """Un poligono sobre el horizonte no se apoya en el suelo: debe decirlo."""
    calibration = scene.truth_calibration()
    sky = np.array([[100., 20.], [300., 20.], [300., 60.], [100., 60.]])
    result = geometry.reconstruct(sky, geometry.HORIZONTAL, calibration, 1.6)
    assert 'error' in result and 'horizonte' in result['error']


def test_reconstruction_without_calibration_explains_itself():
    result = geometry.reconstruct(scene.project(scene.FACADE), geometry.VERTICAL, None, 1.6)
    assert 'error' in result and 'calibracion' in result['error']


def test_free_axis_warns():
    calibration = scene.truth_calibration()
    result = geometry.reconstruct(scene.project(scene.FACADE),
                                  geometry.FREE, calibration, 1.6)
    assert result.get('warning')


def test_tracking_follows_a_known_shift():
    import cv2
    first = cv2.cvtColor(scene.render(), cv2.COLOR_BGR2GRAY)
    second = cv2.cvtColor(scene.render(shift=7.), cv2.COLOR_BGR2GRAY)
    points = scene.project([[0, 0, 8], [12, 0, 8], [12, 11, 8], [0, 11, 8]])
    moved, good = tracking.track(first, second, points)
    assert good.any(), 'no ha sobrevivido ningun vertice'
    shift = (moved[good] - points[good])[:, 0]
    assert np.allclose(shift, 7., atol=1.)


def test_tracking_discards_a_lost_point():
    """Contra un fotograma en negro no hay correspondencia posible."""
    import cv2
    first = cv2.cvtColor(scene.render(), cv2.COLOR_BGR2GRAY)
    black = np.zeros_like(first)
    points = scene.project(scene.FACADE)
    assert tracking.track_annotation(first, black, points) is None


def test_interpolation_between_keyframes():
    keys = {0: [[0., 0.], [10., 0.]], 10: [[10., 0.], [20., 0.]]}
    assert np.allclose(tracking.interpolate(keys, 5), [[5., 0.], [15., 0.]])
    assert np.allclose(tracking.interpolate(keys, 0), keys[0])
    assert np.allclose(tracking.interpolate(keys, 99), keys[10])
    assert tracking.interpolate({}, 3) is None


# --------------------------------------------------------------------------
# Puente con la aplicacion
# --------------------------------------------------------------------------
def test_overlay_analyses_and_draws(frame):
    from vision_teach import geometry_overlay as overlay
    analysis = overlay.analyse(frame, {'low': 60, 'high': 150, 'tolerance': 25})
    assert len(analysis['segments']) >= 20
    assert analysis['calibration'] is not None
    painted = overlay.draw(frame, analysis)
    assert painted.shape == frame.shape
    assert (painted != frame).any(), 'el dibujo no ha pintado nada'
    text = overlay.summary(analysis)
    assert 'aristas rectas' in text and 'focal' in text


def test_overlay_measures_a_facade(frame):
    from vision_teach import geometry_overlay as overlay
    analysis = overlay.analyse(frame, {'low': 60, 'high': 150, 'tolerance': 25})
    analysis['calibration'] = scene.truth_calibration()      # medir la medicion, no la calibracion
    measured = overlay.measure(analysis, scene.project(scene.FACADE), geometry.VERTICAL)
    assert 'error' not in measured
    assert measured['height'] == pytest.approx(11., abs=.01)
    assert sorted(measured['sides'])[-1] == pytest.approx(12., abs=.01)


def test_overlay_explains_a_failure(frame):
    from vision_teach import geometry_overlay as overlay
    analysis = overlay.analyse(frame, {'low': 60, 'high': 150, 'tolerance': 25})
    sky = np.array([[100., 20.], [300., 20.], [300., 60.], [100., 60.]])
    assert 'error' in overlay.measure(analysis, sky, geometry.HORIZONTAL)
