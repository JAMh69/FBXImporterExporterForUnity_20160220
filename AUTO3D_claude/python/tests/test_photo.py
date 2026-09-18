"""Pose de camara a partir del EXIF y el XMP de una foto de dron DJI.

El XMP de ejemplo reproduce el de una foto real (DJI Mini 3 Pro, toma cenital).
"""
import io
import struct

import numpy as np
import pytest
from PIL import Image

from vision_teach import photo

XMP = '''<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description rdf:about="" xmlns:drone-dji="http://www.dji.com/drone-dji/1.0/"
drone-dji:GpsStatus="Invalid" drone-dji:GpsLatitude="+40.857202170"
drone-dji:GpsLongitude="-4.133570191" drone-dji:AbsoluteAltitude="+1101.840"
drone-dji:RelativeAltitude="+78.000" drone-dji:GimbalRollDegree="+0.00"
drone-dji:GimbalYawDegree="{yaw}" drone-dji:GimbalPitchDegree="{pitch}"
drone-dji:DroneModel="Mini 3 Pro"/></rdf:RDF></x:xmpmeta>'''


# Una octava parte de los 8064 x 6048 reales: mismo encuadre y mismas
# proporciones, pero sin reservar 146 MB en cada prueba. La focal en pixeles
# escala igual, asi que la huella en el suelo sale identica a la real.
ANCHO, ALTO = 1008, 756
FOCAL_HORIZONTAL = ANCHO * 24 / 36.


def make_photo(tmp_path, name='DJI_TEST.JPG', yaw='+67.50', pitch='-90.00',
               width=ANCHO, height=ALTO, equivalent=24):
    """JPEG con el EXIF y un APP1 de XMP, como los de DJI.

    El tamaño que cuenta es el de la imagen decodificada, no el que declare el
    EXIF: una foto recortada conserva el tamaño original en sus etiquetas.
    """
    image = Image.new('RGB', (width, height), (128, 128, 128))
    exif = Image.Exif()
    exif[0xA002], exif[0xA003] = width, height          # Exif Image Width / Height
    ifd = {0x920A: 6.72, 0xA405: equivalent}            # FocalLength, FocalLengthIn35mmFilm
    exif[0x8769] = ifd
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', exif=exif)
    data = buffer.getvalue()
    payload = XMP.format(yaw=yaw, pitch=pitch).encode()
    segment = (b'\xff\xe1' + struct.pack('>H', len(payload) + 2 + 29) +
               b'http://ns.adobe.com/xap/1.0/\x00' + payload)
    path = tmp_path / name
    path.write_bytes(data[:2] + segment + data[2:])
    return path


# ---------------------------------------------------------------- rotacion
def test_nadir_looks_straight_down():
    rotation = photo.rotation_from_gimbal(67.5, -90.)
    assert np.allclose(rotation[2], [0., 0., -1.], atol=1e-9)


def test_horizontal_camera_looks_along_its_heading():
    assert np.allclose(photo.rotation_from_gimbal(0., 0.)[2], [0., 1., 0.], atol=1e-9)    # norte
    assert np.allclose(photo.rotation_from_gimbal(90., 0.)[2], [1., 0., 0.], atol=1e-9)   # este
    assert np.allclose(photo.rotation_from_gimbal(180., 0.)[2], [0., -1., 0.], atol=1e-9)


def test_right_axis_is_to_the_right():
    """Mirando al norte, la derecha de la imagen es el este."""
    assert np.allclose(photo.rotation_from_gimbal(0., 0.)[0], [1., 0., 0.], atol=1e-9)


def test_down_axis_points_down_when_horizontal():
    assert np.allclose(photo.rotation_from_gimbal(0., 0.)[1], [0., 0., -1.], atol=1e-9)


@pytest.mark.parametrize('yaw,pitch,roll', [(0., 0., 0.), (67.5, -90., 0.),
                                            (123., -35., 12.), (-40., -90., -7.)])
def test_rotation_is_a_proper_rotation(yaw, pitch, roll):
    rotation = photo.rotation_from_gimbal(yaw, pitch, roll)
    assert np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-9)
    assert np.linalg.det(rotation) == pytest.approx(1., abs=1e-9)


def test_roll_turns_the_image_around_the_optical_axis():
    sin_roll = photo.rotation_from_gimbal(0., 0., 0.)
    con_roll = photo.rotation_from_gimbal(0., 0., 30.)
    assert np.allclose(sin_roll[2], con_roll[2], atol=1e-9)        # el eje no se mueve
    assert not np.allclose(sin_roll[0], con_roll[0], atol=1e-3)    # pero la derecha si


# ---------------------------------------------------------------- focal
def test_both_focal_conventions_and_their_gap(tmp_path):
    exif = photo.read_exif(make_photo(tmp_path))
    horizontal = photo.focal_in_pixels(exif, convention='horizontal')
    diagonal = photo.focal_in_pixels(exif, convention='diagonal')
    assert horizontal == pytest.approx(FOCAL_HORIZONTAL, abs=.5)
    assert diagonal == pytest.approx(FOCAL_HORIZONTAL * 1.04, abs=1.)
    # el 4% que una sola foto no permite decidir: queda documentado en una prueba
    assert abs(diagonal - horizontal) / horizontal == pytest.approx(.04, abs=.005)


def test_an_unknown_convention_is_refused(tmp_path):
    exif = photo.read_exif(make_photo(tmp_path))
    with pytest.raises(ValueError, match='convencion'):
        photo.focal_in_pixels(exif, convention='inventada')


# ---------------------------------------------------------------- lectura
def test_reads_a_dji_photo(tmp_path):
    camera, info = photo.read_photo(make_photo(tmp_path))
    assert info['model'] == 'Mini 3 Pro'
    assert info['height'] == 78.
    assert info['gimbal'] == (67.5, -90., 0.)
    assert info['gps_status'] == 'Invalid'
    assert camera.size == (ANCHO, ALTO)
    assert np.allclose(camera.principal, [ANCHO / 2., ALTO / 2.])


def test_the_camera_sits_at_its_flight_height(tmp_path):
    camera, _ = photo.read_photo(make_photo(tmp_path))
    assert np.allclose(camera.centre, [0., 0., 78.], atol=1e-6)


def test_the_point_under_the_drone_lands_in_the_centre(tmp_path):
    camera, _ = photo.read_photo(make_photo(tmp_path))
    pixel, ahead = camera.project([0., 0., 0.])
    assert ahead[0]
    assert np.allclose(pixel[0], camera.principal, atol=1e-6)


def test_ground_distance_matches_the_sampling_distance(tmp_path):
    """Veinte metros en el suelo deben ser 20 / GSD pixeles, mire donde mire."""
    camera, _ = photo.read_photo(make_photo(tmp_path))
    gsd = photo.ground_sampling(camera, 78.)
    centre = camera.project([0., 0., 0.])[0][0]
    diagonal = 20. / np.sqrt(2.)      # exactamente 20 m, no 19.997
    for offset in ([20., 0., 0.], [0., 20., 0.], [-diagonal, diagonal, 0.]):
        pixel = camera.project(offset)[0][0]
        assert np.linalg.norm(pixel - centre) == pytest.approx(20. / gsd, rel=1e-6)


def test_nadir_footprint(tmp_path):
    camera, _ = photo.read_photo(make_photo(tmp_path))
    ancho, alto = photo.nadir_footprint(camera, 78.)
    assert ancho == pytest.approx(117., abs=.5)
    assert alto == pytest.approx(87.8, abs=.5)


def test_several_photos_share_one_local_origin(tmp_path):
    uno = make_photo(tmp_path, 'A.JPG')
    otro = make_photo(tmp_path, 'B.JPG', yaw='+0.00', pitch='-45.00')
    camaras, datos = photo.read_folder([uno, otro])
    assert len(camaras) == 2
    assert np.allclose(camaras[0].centre, camaras[1].centre, atol=1e-6)   # misma posicion GPS
    assert datos[1]['gimbal'][1] == -45.


def test_a_recompressed_copy_is_refused(tmp_path):
    """Las copias que pasan por un chat pierden el XMP: hay que decirlo claro."""
    plain = tmp_path / 'sin_xmp.jpg'
    Image.new('RGB', (64, 48)).save(plain, 'JPEG')
    with pytest.raises(ValueError, match='original'):
        photo.read_photo(plain)


def test_triangulation_between_two_real_style_poses(tmp_path):
    """Dos tomas oblicuas opuestas sobre un mismo punto deben cortarse en el."""
    from vision_teach import multiview as mv
    camera_a, _ = photo.read_photo(make_photo(tmp_path, 'A.JPG', yaw='+0.00', pitch='-45.00'))
    camera_b, _ = photo.read_photo(make_photo(tmp_path, 'B.JPG', yaw='+180.00', pitch='-45.00'))
    # se separan a mano, porque las dos fotos de prueba comparten GPS
    camera_a.translation = -camera_a.rotation @ np.array([0., -40., 78.])
    camera_b.translation = -camera_b.rotation @ np.array([0., 40., 78.])
    truth = np.array([3., 2., 6.])
    marks = [c.project(truth)[0][0] for c in (camera_a, camera_b)]
    assert np.linalg.norm(mv.triangulate([camera_a, camera_b], marks) - truth) < 1e-6
