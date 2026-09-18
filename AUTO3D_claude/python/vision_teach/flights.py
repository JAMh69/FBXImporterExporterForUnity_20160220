"""Analisis de una campaña de vuelos a partir de los metadatos de las fotos.

Entrada: el CSV que produce `AUTO3D_metadatos.ps1` recorriendo una carpeta.
Salida: que vuelos hay, de que tipo es cada uno, cuales sirven para fachadas,
cuales estan malgastados y que fotos conviene procesar.

Pesa unos pocos KB frente a los gigas de las imagenes, asi que permite decidir
que procesar **antes** de mover un solo archivo grande.
"""
import csv
from datetime import datetime

import numpy as np

EARTH = 6378137.0

# Un vuelo cenital no ve fachadas (ver apartado 16 del cuaderno): el escorzo de
# una pared vertical es el seno del angulo respecto a la vertical, y justo bajo
# el dron ese angulo es cero.
NADIR_LIMIT = -75.     # por debajo de esto se considera toma cenital
SKY_LIMIT = -10.       # por encima de esto la camara mira al cielo o al horizonte


def read_csv(path):
    """Lee el CSV del extractor. Convierte a numero lo que lo sea."""
    numeric = ('GpsLatitude', 'GpsLongitude', 'RelativeAltitude', 'AbsoluteAltitude',
               'GimbalPitchDegree', 'GimbalYawDegree', 'GimbalRollDegree',
               'FlightPitchDegree', 'FlightYawDegree', 'FlightRollDegree',
               'RtkStdLon', 'RtkStdLat', 'RtkStdHgt', 'mb')
    rows = []
    with open(path, encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            for key in numeric:
                value = (row.get(key) or '').strip()
                row[key] = float(value) if value not in ('', 'nan') else None
            stamp = (row.get('fecha') or '').strip()
            row['when'] = datetime.fromisoformat(stamp) if stamp else None
            if row.get('GpsLatitude') is not None:
                rows.append(row)
    return rows


def split_flights(rows, gap_minutes=20.):
    """Agrupa las fotos en vuelos por carpeta y por saltos en el tiempo.

    El nombre de carpeta suele bastar, pero no siempre: una misma carpeta puede
    guardar dos salidas del mismo dia. El corte por tiempo lo resuelve.
    """
    ordered = sorted([r for r in rows if r['when']],
                     key=lambda r: (r.get('carpeta', ''), r['when']))
    flights, current = [], []
    for row in ordered:
        if current:
            previous = current[-1]
            same = row.get('carpeta', '') == previous.get('carpeta', '')
            close = (row['when'] - previous['when']).total_seconds() <= gap_minutes * 60
            if not (same and close):
                flights.append(current)
                current = []
        current.append(row)
    if current:
        flights.append(current)
    return flights


def _positions(flight):
    latitude = np.array([r['GpsLatitude'] for r in flight])
    longitude = np.array([r['GpsLongitude'] for r in flight])
    height = np.array([r['RelativeAltitude'] or 0. for r in flight])
    scale = np.cos(np.radians(latitude.mean()))
    east = np.radians(longitude - longitude[0]) * EARTH * scale
    north = np.radians(latitude - latitude[0]) * EARTH
    return np.column_stack([east, north, height])


def angular_spread(positions, target=None):
    """Angulo maximo barrido alrededor de un punto del suelo, en grados.

    Es la magnitud que gobierna la calidad de la triangulacion, por encima del
    numero de fotos: medido, dos tomas a 90 grados dan 35 veces menos error que
    a 2 grados.
    """
    if len(positions) < 2:
        return 0.
    if target is None:
        target = np.r_[positions[:, :2].mean(axis=0), 0.]
    vectors = positions - np.asarray(target, float)
    norms = np.linalg.norm(vectors, axis=1)
    good = norms > 1e-6
    if good.sum() < 2:
        return 0.
    unit = vectors[good] / norms[good, None]
    return float(np.degrees(np.arccos(np.clip(unit @ unit.T, -1., 1.)).max()))


def azimuth_coverage(positions, sectors=12):
    """Reparto de las tomas por sectores de acimut alrededor del centro.

    Hace falta **ademas** del angulo barrido, no en su lugar: una pasada recta
    larga puede barrer mas angulo que una orbita cerrada -medido: 35 grados
    frente a 31- y sin embargo ve el edificio siempre desde el mismo lado. El
    angulo dice cuanta base hay; el acimut dice si esa base rodea al objeto.
    """
    if len(positions) < 2:
        return np.zeros(sectors, int), 0.
    centre = positions[:, :2].mean(axis=0)
    angles = np.degrees(np.arctan2(positions[:, 1] - centre[1],
                                   positions[:, 0] - centre[0]))
    counts, _ = np.histogram(angles, bins=sectors, range=(-180., 180.))
    return counts, float((counts > 0).mean())


def classify(pitches):
    """Tipo de vuelo segun como se reparten los angulos del gimbal."""
    pitches = np.asarray([p for p in pitches if p is not None])
    if not len(pitches):
        return 'sin datos de gimbal'
    nadir = (pitches <= NADIR_LIMIT).mean()
    sky = (pitches >= SKY_LIMIT).mean()
    oblique = ((pitches > NADIR_LIMIT) & (pitches < SKY_LIMIT)).mean()
    if nadir > .85:
        return 'malla cenital: cubiertas y huellas, sin fachadas'
    if oblique > .85:
        return 'oblicuo: bueno para fachadas'
    if nadir > .2 and oblique > .2:
        return 'mixto: cenital mas oblicuo, lo ideal'
    if sky > .5:
        return 'apunta al cielo: poco aprovechable'
    return 'irregular'


def report(flight):
    """Resumen de un vuelo, con lo que hace falta para decidir si procesarlo."""
    positions = _positions(flight)
    steps = np.linalg.norm(np.diff(positions, axis=0), axis=1) if len(positions) > 1 else np.zeros(0)
    sectors, filled = azimuth_coverage(positions)
    pitches = np.array([r['GimbalPitchDegree'] for r in flight
                        if r['GimbalPitchDegree'] is not None])
    heights = np.array([r['RelativeAltitude'] for r in flight
                        if r['RelativeAltitude'] is not None])
    rtk = [r['RtkStdLon'] for r in flight if r.get('RtkStdLon') is not None]
    usable = int(((pitches < SKY_LIMIT)).sum()) if len(pitches) else 0
    out = {
        'folder': flight[0].get('carpeta', ''),
        'first': flight[0].get('archivo', ''),
        'when': flight[0]['when'],
        'photos': len(flight),
        'model': flight[0].get('DroneModel', ''),
        'gigabytes': round(sum(r['mb'] or 0. for r in flight) / 1024., 2),
        'travelled': float(steps.sum()),
        'span': float(np.linalg.norm(positions[-1] - positions[0])),
        'spread': angular_spread(positions),
        'azimuth_filled': filled,
        'azimuth_sectors': sectors.tolist(),
        'height_min': float(heights.min()) if len(heights) else None,
        'height_max': float(heights.max()) if len(heights) else None,
        'pitch_min': float(pitches.min()) if len(pitches) else None,
        'pitch_max': float(pitches.max()) if len(pitches) else None,
        'nadir_fraction': float((pitches <= NADIR_LIMIT).mean()) if len(pitches) else None,
        'sky_photos': int((pitches >= SKY_LIMIT).sum()) if len(pitches) else 0,
        'usable_photos': usable,
        'kind': classify(pitches),
        'rtk': float(np.median(rtk)) if rtk else None,
        'gps_status': flight[0].get('GpsStatus', ''),
    }
    out['warnings'] = warnings(out)
    return out


def warnings(summary):
    """Avisos concretos, con su motivo. Un vuelo se descarta por razones, no
    por intuicion."""
    out = []
    if summary['travelled'] < 5.:
        out.append('el dron apenas se mueve: sin paralaje no hay reconstruccion')
    if summary['spread'] < 15.:
        out.append(f"solo {summary['spread']:.0f} grados barridos: triangulacion debil")
    if summary['azimuth_filled'] < .5:
        out.append(f"solo se cubre el {summary['azimuth_filled'] * 100:.0f} % del acimut: "
                   'el edificio se ve siempre desde el mismo lado, faltaran caras')
    if summary['sky_photos']:
        out.append(f"{summary['sky_photos']} fotos apuntando al cielo o al horizonte: "
                   'conviene apartarlas antes de procesar')
    if summary['nadir_fraction'] is not None and summary['nadir_fraction'] > .85:
        out.append('todo cenital: dara cubiertas y huellas, no fachadas')
    if summary['rtk'] is None and summary['gps_status'] not in ('Normal', 'RTK'):
        out.append(f"sin datos de precision RTK (GpsStatus={summary['gps_status'] or 'vacio'}): "
                   'la posicion absoluta puede tener metros de error')
    return out


def summarise(path, gap_minutes=20.):
    """Informe completo de una campaña, de mejor a peor vuelo."""
    flights = split_flights(read_csv(path), gap_minutes)
    reports = [report(f) for f in flights]
    # los que ven fachadas y barren angulo, primero
    reports.sort(key=lambda r: (-(r['nadir_fraction'] is not None and r['nadir_fraction'] < .85),
                                -r['azimuth_filled'], -r['spread']))
    return reports


def as_text(reports):
    lines = [f'{len(reports)} vuelos.', '']
    for index, r in enumerate(reports, 1):
        lines.append(f"{index}. {r['folder'] or '(raiz)'}  [{r['first']}]")
        lines.append(f"   {r['photos']} fotos ({r['gigabytes']} GB)  {r['model']}  "
                     f"{r['when']:%Y-%m-%d %H:%M}" if r['when'] else '')
        lines.append(f"   {r['kind']}")
        if r['pitch_min'] is not None:
            lines.append(f"   gimbal de {r['pitch_min']:.0f} a {r['pitch_max']:.0f} grados   "
                         f"altura de {r['height_min']:.0f} a {r['height_max']:.0f} m")
        lines.append(f"   recorrido {r['travelled']:.0f} m   angulo barrido {r['spread']:.0f} grados"
                     f"   acimut {r['azimuth_filled'] * 100:.0f} %"
                     + (f"   RTK {r['rtk'] * 100:.1f} cm" if r['rtk'] else ''))
        for warning in r['warnings']:
            lines.append(f"   aviso: {warning}")
        lines.append('')
    return '\n'.join(lines)
