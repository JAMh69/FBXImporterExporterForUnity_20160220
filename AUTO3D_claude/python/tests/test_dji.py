"""Lectura de telemetria .SRT de DJI.

El texto de ejemplo reproduce el formato real, incluido el detalle que rompio
la primera version: DJI mete `rel_alt` y `abs_alt` dentro del mismo corchete.
"""
import numpy as np
import pytest

from vision_teach import dji

CABECERA = ('[iso : 110] [shutter : 1/320.0] [fnum : 170] [ev : 0] [ct : 5141] '
            '[color_md : default] [focal_len : 240] [dzoom_ratio: 10000, delta:0],')


def bloque(indice, latitude, longitude, altura, segundo):
    return (f'{indice}\n'
            f'00:00:{segundo:02d},000 --> 00:00:{segundo + 1:02d},000\n'
            f'<font size="28">SrtCnt : {indice}, DiffTime : 33ms\n'
            f'2024-10-20 23:04:{58 + segundo % 2:02d}.{(indice * 33) % 1000:03d}\n'
            f'{CABECERA}[latitude: {latitude:.6f}] [longitude: {longitude:.6f}] '
            f'[rel_alt: {altura:.3f} abs_alt: {955.0 + altura:.3f}] </font>\n')


def vuelo(tmp_path, count=20, step=0.00003, drop=0.):
    texto = '\n'.join(bloque(i + 1, 41.1324 + i * step, -3.8143, 93.8 - i * drop, i // 30)
                      for i in range(count))
    path = tmp_path / 'DJI_TEST.SRT'
    path.write_text(texto + '\n', encoding='utf-8')
    return path


def test_reads_every_frame(tmp_path):
    frames = dji.read_srt(vuelo(tmp_path))
    assert len(frames) == 20
    assert frames[0]['frame'] == 0 and frames[-1]['frame'] == 19


def test_both_altitudes_in_one_bracket(tmp_path):
    """El fallo real: `[rel_alt: 93.800 abs_alt: 1048.861]` son dos campos."""
    frames = dji.read_srt(vuelo(tmp_path))
    assert frames[0]['rel_alt'] == pytest.approx(93.8)
    assert frames[0]['abs_alt'] == pytest.approx(1048.8)
    assert isinstance(frames[0]['rel_alt'], float)


def test_reads_the_rest_of_the_fields(tmp_path):
    first = dji.read_srt(vuelo(tmp_path))[0]
    assert first['iso'] == 110
    assert first['shutter'] == '1/320.0'          # no es numerico y no debe romper
    assert first['focal_len'] == 240
    assert first['color_md'] == 'default'
    assert first['time'].year == 2024


def test_timestamp_is_not_read_as_a_field(tmp_path):
    """23:04:58.522 no debe convertirse en un campo llamado '23'."""
    first = dji.read_srt(vuelo(tmp_path))[0]
    assert not any(key.isdigit() for key in first)


def test_local_coordinates_are_metric(tmp_path):
    frames = dji.read_srt(vuelo(tmp_path, count=2, step=0.001))
    plane = dji.local_xy(frames)
    assert plane[0] == pytest.approx([0., 0.], abs=1e-9)
    assert plane[1][1] == pytest.approx(111.3, abs=1.)     # 0.001 grados de latitud
    assert abs(plane[1][0]) < 1e-6                         # sin cambio de longitud


def test_focal_in_pixels(tmp_path):
    frames = dji.read_srt(vuelo(tmp_path))
    # 240 -> 24.0 mm equivalentes; en 3840 px de ancho son 2560 px
    assert dji.focal_pixels(frames, 3840) == pytest.approx(2560., abs=1.)


def test_a_hovering_flight_is_refused(tmp_path):
    """Dos segundos parado no sirven por muchos fotogramas que tengan."""
    frames = dji.read_srt(vuelo(tmp_path, count=60, step=0.))
    report = dji.summary(frames)
    assert report['frames'] == 60
    assert not report['usable']
    assert 'parado' in report['reason']


def test_a_moving_flight_is_accepted(tmp_path):
    frames = dji.read_srt(vuelo(tmp_path, count=100, step=0.00003, drop=.3))
    report = dji.summary(frames)
    assert report['usable'], report['reason']
    assert report['travelled'] > 30.
    assert report['height_max'] - report['height_min'] > 25.


def test_frames_are_chosen_by_distance_not_by_time(tmp_path):
    """Extraer los 30 fotogramas de cada segundo no aporta nada: entre ellos
    el dron se ha movido centimetros."""
    # 0.000005 grados por fotograma son unos 0.56 m: cien fotogramas cubren 56 m
    frames = dji.read_srt(vuelo(tmp_path, count=100, step=0.000005))
    todos = dji.select_frames(frames, separation=0.)
    cada5 = dji.select_frames(frames, separation=5.)
    assert len(todos) == 100
    assert 8 <= len(cada5) <= 14, f'{len(cada5)} fotogramas para 56 m cada 5 m'
    posiciones = dji.positions(frames)
    saltos = [np.linalg.norm(posiciones[b] - posiciones[a])
              for a, b in zip(cada5[:-1], cada5[1:])]
    assert min(saltos) >= 5.


def test_angular_spread_grows_with_the_flight(tmp_path):
    (tmp_path / 'a').mkdir(); (tmp_path / 'b').mkdir()
    poco = dji.read_srt(vuelo(tmp_path / 'a', count=30, step=0.000005))
    mucho = dji.read_srt(vuelo(tmp_path / 'b', count=30, step=0.00005))
    assert dji.angular_spread(mucho) > dji.angular_spread(poco)


def test_a_changing_focal_is_refused(tmp_path):
    texto = bloque(1, 41.1, -3.8, 90., 0) + '\n' + bloque(2, 41.1, -3.8, 90., 0).replace('focal_len : 240', 'focal_len : 480')
    path = tmp_path / 'zoom.SRT'
    path.write_text(texto, encoding='utf-8')
    with pytest.raises(ValueError, match='focal cambia'):
        dji.focal_pixels(dji.read_srt(path), 3840)


def test_an_empty_file_says_so(tmp_path):
    path = tmp_path / 'vacio.SRT'
    path.write_text('', encoding='utf-8')
    report = dji.summary(dji.read_srt(path))
    assert report['frames'] == 0 and not report['usable']
