"""Lectura del .MRK de un DJI con RTK. El texto reproduce el formato real."""
import numpy as np
import pytest

from vision_teach import mrk

LINEA = ('{n}\t{tow:.6f}\t[2360]\t    54,N\t   162,E\t    84,V\t'
         '{lat:.8f},Lat\t{lon:.8f},Lon\t{h:.3f},Ellh\t'
         '{sn:.6f}, {se:.6f}, {sv:.6f}\t{q},Q\n')


def orbita(tmp_path, count=24, radio=20., sigma=.05, q=50, nombre='vuelo.MRK'):
    """Orbita completa alrededor de un punto, como el vuelo real analizado."""
    lat0, lon0 = 40.3355, -3.8751
    metro_lat = 1 / 111320.
    metro_lon = metro_lat / np.cos(np.radians(lat0))
    texto = ''
    for i in range(count):
        a = 2 * np.pi * i / count
        texto += LINEA.format(n=i + 1, tow=301666. + i * .55,
                              lat=lat0 + radio * np.cos(a) * metro_lat,
                              lon=lon0 + radio * np.sin(a) * metro_lon,
                              h=716. + .1 * i, sn=sigma, se=sigma * .8,
                              sv=sigma * 1.2, q=q)
    path = tmp_path / nombre
    path.write_text(texto, encoding='utf-8')
    return path


def test_reads_every_shot(tmp_path):
    shots = mrk.read_mrk(orbita(tmp_path))
    assert len(shots) == 24
    assert shots[0]['shot'] == 1 and shots[-1]['shot'] == 24
    assert shots[0]['week'] == 2360
    assert shots[0]['flag'] == 50


def test_reads_the_accuracy_of_each_shot(tmp_path):
    shots = mrk.read_mrk(orbita(tmp_path, sigma=.05))
    assert shots[0]['sigma'] == pytest.approx((.05, .04, .06))
    assert mrk.sigmas(shots).shape == (24, 3)


def test_reads_the_lever_arm(tmp_path):
    """La correccion antena-camara viene en milimetros."""
    assert mrk.read_mrk(orbita(tmp_path))[0]['lever_mm'] == (54., 162., 84.)


def test_lever_arm_is_not_applied_by_default(tmp_path):
    """Son 15 cm, del orden de la precision: aplicarlo sin confirmar seria peor
    que no aplicarlo, asi que hay que pedirlo explicitamente."""
    shots = mrk.read_mrk(orbita(tmp_path))
    sin = mrk.positions(shots)
    con = mrk.positions(shots, apply_lever_arm=True)
    assert not np.allclose(sin, con)
    assert np.allclose(con[:, 1] - sin[:, 1], .054)        # norte, 54 mm
    assert np.allclose(con[:, 0] - sin[:, 0], .162)        # este, 162 mm


def test_a_line_that_is_not_a_shot_is_ignored(tmp_path):
    path = orbita(tmp_path)
    path.write_text('cabecera cualquiera\n\n' + path.read_text(encoding='utf-8') +
                    'basura\tcorta\n', encoding='utf-8')
    assert len(mrk.read_mrk(path)) == 24


def test_an_orbit_sweeps_the_whole_azimuth(tmp_path):
    points = mrk.positions(mrk.read_mrk(orbita(tmp_path)))
    counts, filled = mrk.azimuth_coverage(points)
    assert filled == 1.0, 'una orbita completa debe llenar los doce sectores'
    assert counts.sum() == 24


def test_a_straight_line_does_not(tmp_path):
    """Una pasada recta llena dos sectores opuestos y poco mas."""
    lat0, lon0 = 40.3355, -3.8751
    texto = ''.join(LINEA.format(n=i + 1, tow=301666. + i, lat=lat0 + i * .00002,
                                 lon=lon0, h=716., sn=.05, se=.04, sv=.06, q=50)
                    for i in range(24))
    path = tmp_path / 'recta.MRK'
    path.write_text(texto, encoding='utf-8')
    _, filled = mrk.azimuth_coverage(mrk.positions(mrk.read_mrk(path)))
    assert filled < .3


def test_summary_of_a_good_flight(tmp_path):
    report = mrk.summary(mrk.read_mrk(orbita(tmp_path)))
    assert report['usable'], report['reason']
    assert report['spread'] > 90.
    assert report['azimuth_filled'] == 1.0
    assert report['flags'] == {50: 24}
    assert report['sigma_median'][0] == pytest.approx(.05)


def test_a_hovering_flight_is_refused(tmp_path):
    report = mrk.summary(mrk.read_mrk(orbita(tmp_path, radio=.0001)))
    assert not report['usable']
    assert 'paralaje' in report['reason'] or 'grados' in report['reason']


def test_missing_shots_are_counted(tmp_path):
    path = orbita(tmp_path)
    lineas = path.read_text(encoding='utf-8').splitlines()
    del lineas[5]                                          # un disparo sin foto
    path.write_text('\n'.join(lineas) + '\n', encoding='utf-8')
    report = mrk.summary(mrk.read_mrk(path))
    assert report['shots'] == 23 and report['missing'] == 1


def test_photos_are_matched_by_shot_number(tmp_path):
    """Emparejar por posicion en la lista fallaria en cuanto falte un disparo."""
    shots = mrk.read_mrk(orbita(tmp_path, count=5))
    nombres = ['DJI_20250402134730_0001_V.JPG', 'DJI_20250402134731_0002_V.JPG',
               'DJI_20250402134731_0004_V.JPG', 'DJI_20250402134732_0005_V.JPG']
    pares = dict((s['shot'], n) for s, n in mrk.match_photos(shots, nombres))
    assert pares[1].endswith('0001_V.JPG')
    assert pares[4].endswith('0004_V.JPG')
    assert pares[3] is None, 'el disparo sin foto debe quedar sin emparejar'


def test_an_empty_file_says_so(tmp_path):
    path = tmp_path / 'vacio.MRK'
    path.write_text('', encoding='utf-8')
    assert mrk.summary(mrk.read_mrk(path))['shots'] == 0
