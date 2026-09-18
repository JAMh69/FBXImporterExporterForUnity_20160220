"""Lectura del formato de COLMAP / OpenDroneMap.

Se genera un modelo en el formato real, se vuelve a leer y se comprueba que
las camaras reconstruidas proyectan igual que las originales. Si el convenio
del cuaternion estuviera invertido, todo lo demas seria correcto y el
resultado, basura.
"""
import numpy as np
import pytest

from vision_teach import colmap
from tests import multiview_scene as ms


def matrix_to_quaternion(R):
    """Inversa de colmap.quaternion_to_matrix, solo para escribir el fichero."""
    trace = R[0, 0] + R[1, 1] + R[2, 2]
    if trace > 0:
        s = np.sqrt(trace + 1.) * 2
        w, x, y, z = .25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = np.sqrt(1. + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        w, x, y, z = (R[2, 1] - R[1, 2]) / s, .25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = np.sqrt(1. + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        w, x, y, z = (R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, .25 * s, (R[1, 2] + R[2, 1]) / s
    else:
        s = np.sqrt(1. + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        w, x, y, z = (R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, .25 * s
    return np.array([w, x, y, z])


@pytest.fixture
def model(tmp_path):
    cameras = ms.orbit(count=4)
    (tmp_path / 'cameras.txt').write_text(
        '# Camera list\n'
        f'1 PINHOLE {int(ms.WIDTH)} {int(ms.HEIGHT)} {ms.FOCAL} {ms.FOCAL} '
        f'{ms.WIDTH / 2} {ms.HEIGHT / 2}\n', encoding='utf-8')
    lines = ['# Image list']
    for index, camera in enumerate(cameras, start=1):
        q = matrix_to_quaternion(camera.rotation)
        t = camera.translation
        lines.append(f'{index} {q[0]} {q[1]} {q[2]} {q[3]} {t[0]} {t[1]} {t[2]} 1 {camera.name}')
        lines.append('100.0 200.0 -1 300.0 400.0 -1')      # fila de puntos 2D, se descarta
    (tmp_path / 'images.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return tmp_path, cameras


def test_reads_poses_that_project_identically(model):
    directory, truth = model
    loaded = colmap.read_model(directory)
    assert len(loaded) == len(truth)
    for original, read in zip(truth, loaded):
        assert read.name == original.name
        assert read.size == (int(ms.WIDTH), int(ms.HEIGHT))
        assert np.allclose(read.centre, original.centre, atol=1e-6)
        for point in np.vstack([ms.FOOTPRINT, ms.ROOF_SLOPE]):
            assert np.allclose(read.project(point)[0], original.project(point)[0], atol=1e-4)


def test_triangulation_works_on_the_loaded_model(model):
    directory, _ = model
    loaded = colmap.read_model(directory)
    from vision_teach import multiview as mv
    for truth in ms.ROOF_SLOPE:
        marks = [c.project(truth)[0][0] for c in loaded]
        assert np.linalg.norm(mv.triangulate(loaded, marks) - truth) < 1e-4


def test_simple_pinhole_and_radial_share_one_focal(tmp_path):
    (tmp_path / 'cameras.txt').write_text(
        '1 SIMPLE_PINHOLE 4000 3000 2800 2000 1500\n'
        '2 SIMPLE_RADIAL 4000 3000 2750 2000 1500 -0.02\n', encoding='utf-8')
    cameras = colmap.read_cameras(tmp_path / 'cameras.txt')
    assert cameras[1]['focal'] == (2800., 2800.)
    assert cameras[2]['focal'] == (2750., 2750.)
    assert cameras[2]['principal'] == (2000., 1500.)


def test_unknown_camera_model_is_refused(tmp_path):
    (tmp_path / 'cameras.txt').write_text('1 INVENTADA 100 100 1 2 3\n', encoding='utf-8')
    with pytest.raises(ValueError, match='modelo de camara'):
        colmap.read_cameras(tmp_path / 'cameras.txt')
