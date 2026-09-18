"""Analisis de una campaña a partir del CSV de metadatos."""
import numpy as np
import pytest

from vision_teach import flights

CABECERA = ('archivo,carpeta,fecha,mb,DroneModel,ImageSource,GpsStatus,AltitudeType,'
            'GpsLatitude,GpsLongitude,RelativeAltitude,AbsoluteAltitude,'
            'GimbalPitchDegree,GimbalYawDegree,GimbalRollDegree,'
            'FlightPitchDegree,FlightYawDegree,FlightRollDegree,'
            'RtkFlag,RtkStdLon,RtkStdLat,RtkStdHgt,SurveyingMode,'
            'CameraSerialNumber,DroneSerialNumber\n')


def fila(nombre, carpeta, minuto, segundo, lat, lon, pitch, yaw, alt=80., rtk=''):
    return (f'{nombre},{carpeta},2025-04-02 13:{minuto:02d}:{segundo:02d},21.4,'
            f'Matrice 4E,Wide,RTK,RtkAlt,{lat:.8f},{lon:.8f},{alt},1100.0,'
            f'{pitch},{yaw},0.0,-0.3,{yaw},0.7,50,{rtk},{rtk},{rtk},0,SN1,SN2\n')


def campana(tmp_path, vuelos):
    texto = CABECERA
    for carpeta, datos in vuelos.items():
        texto += ''.join(datos)
    path = tmp_path / 'metadatos.csv'
    path.write_text(texto, encoding='utf-8')
    return path


def orbita(carpeta, n=24, minuto=47, pitch=-45., radio=20e-5, rtk=''):
    return [fila(f'DJI_{i:04d}_V.JPG', carpeta, minuto + i // 60, i % 60,
                 40.3355 + radio * np.cos(2 * np.pi * i / n),
                 -3.8751 + radio * np.sin(2 * np.pi * i / n),
                 pitch, (360 * i / n) - 180, rtk=rtk) for i in range(n)]


def test_reads_and_splits_by_folder(tmp_path):
    path = campana(tmp_path, {'a': orbita('vuelo_A'), 'b': orbita('vuelo_B', minuto=50)})
    vuelos = flights.split_flights(flights.read_csv(path))
    assert len(vuelos) == 2
    assert {v[0]['carpeta'] for v in vuelos} == {'vuelo_A', 'vuelo_B'}


def test_splits_two_sorties_in_one_folder(tmp_path):
    """Una misma carpeta puede guardar dos salidas: el corte por tiempo lo ve."""
    manana = orbita('misma', n=6, minuto=10)
    tarde = orbita('misma', n=6, minuto=55)
    path = campana(tmp_path, {'x': manana + tarde})
    assert len(flights.split_flights(flights.read_csv(path), gap_minutes=20.)) == 2


def test_a_nadir_grid_is_recognised_and_warned(tmp_path):
    path = campana(tmp_path, {'a': orbita('malla', pitch=-90.)})
    informe = flights.report(flights.split_flights(flights.read_csv(path))[0])
    assert 'cenital' in informe['kind']
    assert any('fachadas' in w for w in informe['warnings'])


def test_an_oblique_flight_is_recognised(tmp_path):
    path = campana(tmp_path, {'a': orbita('oblicuo', pitch=-45.)})
    informe = flights.report(flights.split_flights(flights.read_csv(path))[0])
    assert 'fachadas' in informe['kind']
    assert informe['nadir_fraction'] == 0.


def test_sky_photos_are_flagged(tmp_path):
    datos = orbita('mixto', n=20, pitch=-45.)
    datos += [fila(f'CIELO_{i}.JPG', 'mixto', 48, i, 40.3355, -3.8751, +10., 0.)
              for i in range(4)]
    path = campana(tmp_path, {'a': datos})
    informe = flights.report(flights.split_flights(flights.read_csv(path))[0])
    assert informe['sky_photos'] == 4
    assert informe['usable_photos'] == 20
    assert any('cielo' in w for w in informe['warnings'])


def test_the_azimuth_tells_an_orbit_from_a_straight_pass(tmp_path):
    """El angulo barrido NO basta: medido, una recta larga barre 35 grados y
    una orbita cerrada 31, y sin embargo la recta ve el edificio siempre desde
    el mismo lado. Lo que los distingue es el acimut cubierto."""
    recta = [fila(f'R{i}.JPG', 'recta', 47, i, 40.3355 + i * 2e-5, -3.8751, -45., 0.)
             for i in range(24)]
    path = campana(tmp_path, {'a': orbita('orbita'), 'b': recta})
    informes = {r['folder']: r for r in
                [flights.report(v) for v in flights.split_flights(flights.read_csv(path))]}
    assert informes['orbita']['azimuth_filled'] == 1.0
    assert informes['recta']['azimuth_filled'] < .3
    assert any('acimut' in w for w in informes['recta']['warnings'])
    assert not any('acimut' in w for w in informes['orbita']['warnings'])


def test_a_stationary_flight_is_warned(tmp_path):
    quieto = [fila(f'Q{i}.JPG', 'quieto', 47, i, 40.3355, -3.8751, -45., 0.)
              for i in range(10)]
    path = campana(tmp_path, {'a': quieto})
    informe = flights.report(flights.split_flights(flights.read_csv(path))[0])
    assert any('paralaje' in w for w in informe['warnings'])


def test_rtk_accuracy_is_reported(tmp_path):
    path = campana(tmp_path, {'a': orbita('con_rtk', rtk='0.03')})
    informe = flights.report(flights.split_flights(flights.read_csv(path))[0])
    assert informe['rtk'] == pytest.approx(.03)
    assert not any('RTK' in w for w in informe['warnings'])


def test_flights_without_rtk_are_warned(tmp_path):
    datos = [f.replace(',RTK,', ',Invalid,') for f in orbita('sin_rtk')]
    path = campana(tmp_path, {'a': datos})
    informe = flights.report(flights.split_flights(flights.read_csv(path))[0])
    assert informe['rtk'] is None
    assert any('RTK' in w for w in informe['warnings'])


def test_the_report_puts_facade_flights_first(tmp_path):
    path = campana(tmp_path, {'a': orbita('malla', pitch=-90.),
                              'b': orbita('oblicuo', minuto=50, pitch=-45.)})
    informes = flights.summarise(path)
    assert informes[0]['folder'] == 'oblicuo'
    texto = flights.as_text(informes)
    assert 'oblicuo' in texto and 'grados' in texto
