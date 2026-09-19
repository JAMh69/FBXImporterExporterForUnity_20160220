"""Telemetria de vuelo DJI: archivos .SRT que acompañan al video.

Un video de dron pierde el EXIF, pero al lado queda un .SRT con una entrada
por fotograma. Es el equivalente del EXIF para video y trae lo que hace falta
para reconstruir: posicion, altura y focal.

Lo que este formato NO trae son los angulos del gimbal. No es fatal -la
fotogrametria calcula la orientacion por si misma- pero conviene saberlo antes
de contar con ellos.
"""
import re
from datetime import datetime

import numpy as np

EARTH = 6378137.0
GROUP = re.compile(r'\[([^\]]*)\]')
# DJI mete varios campos en un mismo corchete -"[rel_alt: 93.8 abs_alt: 1048.9]"-
# asi que primero se aisla cada grupo y despues se leen todos sus pares.
# Buscar pares sobre la linea entera no vale: la marca de tiempo 23:04:58.522
# se leeria como un campo mas.
PAIR = re.compile(r'([a-zA-Z_]+)\s*:\s*([^\s,\]]+)')
TIMESTAMP = re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[.,]\d+)')
NUMERIC = ('iso', 'ev', 'ct', 'focal_len', 'dzoom_ratio', 'latitude', 'longitude',
           'rel_alt', 'abs_alt', 'fnum', 'gb_yaw', 'gb_pitch', 'gb_roll')


def read_srt(path):
    """Lee un .SRT de DJI. Devuelve una entrada por fotograma.

    Tolerante con el formato: DJI ha cambiado los campos entre modelos y
    firmwares, asi que se recoge lo que haya en vez de exigir un esquema.
    """
    text = open(path, encoding='utf-8', errors='replace').read()
    frames = []
    for block in re.split(r'\n\s*\n', text):
        if not block.strip():
            continue
        record = {}
        for group in GROUP.findall(block):
            for key, value in PAIR.findall(group):
                if key in NUMERIC:
                    try:
                        record[key] = float(value)
                    except ValueError:
                        record[key] = value
                else:
                    record[key] = value
        if 'latitude' not in record:
            continue
        index = re.search(r'SrtCnt\s*:\s*(\d+)', block)
        record['frame'] = int(index.group(1)) - 1 if index else len(frames)
        stamp = TIMESTAMP.search(block)
        if stamp:
            record['time'] = datetime.fromisoformat(stamp.group(1).replace(',', '.'))
        frames.append(record)
    return frames


def local_xy(frames):
    """Coordenadas locales en metros (este, norte) desde el primer punto.

    Proyeccion plana suficiente para un vuelo: a escala de cientos de metros
    la curvatura no llega al milimetro.
    """
    if not frames:
        return np.empty((0, 2))
    latitude = np.array([f['latitude'] for f in frames])
    longitude = np.array([f['longitude'] for f in frames])
    reference = np.radians(latitude.mean())
    east = np.radians(longitude - longitude[0]) * EARTH * np.cos(reference)
    north = np.radians(latitude - latitude[0]) * EARTH
    return np.column_stack([east, north])


def positions(frames):
    """Posicion 3D local (este, norte, altura relativa) de cada fotograma."""
    plane = local_xy(frames)
    height = np.array([f.get('rel_alt', 0.) for f in frames])
    return np.column_stack([plane, height])


def focal_pixels(frames, width, sensor_width_35mm=36.0):
    """Focal en pixeles a partir de `focal_len` del SRT.

    DJI escribe ese campo multiplicado por diez, y **se interpreta aqui como
    equivalente a 35 mm**, que es lo habitual: 240 -> 24.0 mm. Conviene
    confirmarlo contra el EXIF de una foto del mismo equipo, donde aparecen
    por separado `FocalLength` y `FocalLengthIn35mmFilm`. Si resultara ser la
    focal real y no la equivalente, este valor estaria mal y con el toda la
    escala.
    """
    values = {f['focal_len'] for f in frames if 'focal_len' in f}
    if not values:
        return None
    if len(values) > 1:
        raise ValueError(f'la focal cambia durante el vuelo: {sorted(values)}')
    millimetres = values.pop() / 10.
    return width * millimetres / sensor_width_35mm


def summary(frames, fps=None):
    """Resumen del vuelo y si sirve para reconstruir.

    El criterio que importa no es la duracion sino el **recorrido**: un dron
    parado graba fotogramas identicos y no hay nada que triangular, por muchos
    minutos que dure.
    """
    if not frames:
        return {'frames': 0, 'usable': False, 'reason': 'archivo vacio'}
    xyz = positions(frames)
    step = np.linalg.norm(np.diff(xyz, axis=0), axis=1) if len(xyz) > 1 else np.zeros(0)
    span = float(np.linalg.norm(xyz[-1] - xyz[0]))
    travelled = float(step.sum())
    height = np.array([f.get('rel_alt', 0.) for f in frames])
    distinct = len({(f['latitude'], f['longitude']) for f in frames})
    if fps is None and len(frames) > 1 and 'time' in frames[0] and 'time' in frames[-1]:
        seconds = (frames[-1]['time'] - frames[0]['time']).total_seconds()
        fps = (len(frames) - 1) / seconds if seconds > 0 else None
    out = {'frames': len(frames), 'fps': fps,
           'seconds': len(frames) / fps if fps else None,
           'span': span, 'travelled': travelled,
           'distinct_positions': distinct,
           'height_min': float(height.min()), 'height_max': float(height.max()),
           'usable': True, 'reason': ''}
    if travelled < 2.:
        out['usable'] = False
        out['reason'] = ('el dron esta practicamente parado: sin desplazamiento no hay '
                         'paralaje y no se puede reconstruir nada')
    elif distinct < 5:
        out['usable'] = False
        out['reason'] = 'el GPS apenas se actualiza: muy pocas posiciones distintas'
    return out


def select_frames(frames, separation=3.0):
    """Fotogramas a extraer para reconstruir, separados por distancia recorrida.

    Extraer los 30 fotogramas de cada segundo no aporta nada: entre ellos el
    dron se ha movido centimetros y la triangulacion con base corta es mala
    (medido: dos vistas a 2 grados dan 35 veces mas error que a 90). Se
    selecciona por metros recorridos, no por tiempo.
    """
    xyz = positions(frames)
    chosen, last = [], None
    for index in range(len(frames)):
        if last is None or np.linalg.norm(xyz[index] - xyz[last]) >= separation:
            chosen.append(frames[index].get('frame', index))
            last = index
    return chosen


def angular_spread(frames, target=None):
    """Angulo barrido alrededor de un punto del suelo, en grados.

    Es la magnitud que gobierna la calidad de la triangulacion, mas que el
    numero de fotogramas. **El valor depende de donde se suponga el suelo.**
    Aqui las alturas son `rel_alt`, es decir sobre el punto de despegue, asi
    que el suelo esta en cero; en el `.MRK`, que da altura elipsoidal, no lo
    esta, y por eso `mrk.angular_spread` usa la cota mas baja del vuelo.

    La cobertura de acimut no depende de esta suposicion y es el indicador
    robusto para distinguir una orbita de una pasada recta.
    """
    xyz = positions(frames)
    if len(xyz) < 2:
        return 0.
    if target is None:
        target = np.r_[xyz[:, :2].mean(axis=0), 0.]
    vectors = xyz - np.asarray(target, float)
    norms = np.linalg.norm(vectors, axis=1)
    good = norms > 1e-6
    if good.sum() < 2:
        return 0.
    unit = vectors[good] / norms[good, None]
    cosines = np.clip(unit @ unit.T, -1., 1.)
    return float(np.degrees(np.arccos(cosines).max()))
