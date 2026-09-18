"""Lectura del archivo .MRK de los drones DJI con RTK.

Por cada disparo, la posicion del receptor en el instante exacto de la
exposicion, con su desviacion tipica. Es mucho mas precisa que la latitud y
longitud del EXIF, que viene redondeada y sin correccion diferencial.

Formato de cada linea, separada por tabuladores:

    1  301666.905683  [2360]  54,N  162,E  84,V
       40.33554262,Lat  -3.87508693,Lon  716.819,Ellh
       0.118401, 0.105962, 0.212182  50,Q

    numero de disparo, segundo de la semana GPS, [semana GPS],
    correccion de brazo de antena en milimetros (norte, este, vertical),
    latitud, longitud, altura elipsoidal,
    desviacion tipica en metros (norte, este, vertical),
    indicador de la solucion de posicionamiento.
"""
import numpy as np

EARTH = 6378137.0


def read_mrk(path):
    """Lee un .MRK. Devuelve una lista de disparos."""
    shots = []
    for line in open(path, encoding='utf-8', errors='replace'):
        parts = line.strip().split('\t')
        if len(parts) < 11:
            continue
        try:
            north, east, vertical = (float(parts[i].split(',')[0]) for i in (3, 4, 5))
            deviations = [float(v) for v in parts[9].split(',')]
            shots.append({
                'shot': int(parts[0]),
                'tow': float(parts[1]),
                'week': int(parts[2].strip('[]')),
                'lever_mm': (north, east, vertical),
                'latitude': float(parts[6].split(',')[0]),
                'longitude': float(parts[7].split(',')[0]),
                'height': float(parts[8].split(',')[0]),
                'sigma': tuple(deviations),
                'flag': int(parts[10].split(',')[0]),
            })
        except (ValueError, IndexError):
            continue
    return shots


def positions(shots, reference=None, apply_lever_arm=False):
    """Posiciones locales (este, norte, altura elipsoidal) en metros.

    `apply_lever_arm` suma la correccion de brazo de antena que trae el propio
    archivo. **Esta desactivada a proposito.** Son unos 15 cm, del mismo orden
    que la precision, asi que aplicarla dos veces o no aplicarla cuando toca
    cambia el resultado de forma apreciable, y no esta confirmado si DJI ya
    entrega la posicion corregida. Se resuelve comparando una linea del .MRK
    con la latitud y longitud del XMP de esa misma foto: si difieren en el
    brazo, es que el .MRK da la posicion de la antena y hay que corregirla.
    """
    if not shots:
        return np.empty((0, 3))
    latitude = np.array([s['latitude'] for s in shots])
    longitude = np.array([s['longitude'] for s in shots])
    height = np.array([s['height'] for s in shots])
    reference = reference or (latitude[0], longitude[0])
    scale = np.cos(np.radians(np.mean(latitude)))
    east = np.radians(longitude - reference[1]) * EARTH * scale
    north = np.radians(latitude - reference[0]) * EARTH
    if apply_lever_arm:
        lever = np.array([s['lever_mm'] for s in shots]) / 1000.
        north = north + lever[:, 0]
        east = east + lever[:, 1]
        height = height + lever[:, 2]
    return np.column_stack([east, north, height])


def sigmas(shots):
    """Desviaciones tipicas (norte, este, vertical) en metros."""
    return np.array([s['sigma'] for s in shots])


def angular_spread(points, target=None):
    """Angulo maximo barrido alrededor de un punto, en grados."""
    if len(points) < 2:
        return 0.
    if target is None:
        target = np.r_[points[:, :2].mean(axis=0), points[:, 2].min()]
    vectors = points - np.asarray(target, float)
    norms = np.linalg.norm(vectors, axis=1)
    good = norms > 1e-6
    if good.sum() < 2:
        return 0.
    unit = vectors[good] / norms[good, None]
    return float(np.degrees(np.arccos(np.clip(unit @ unit.T, -1., 1.)).max()))


def azimuth_coverage(points, sectors=12):
    """Reparto de las tomas por sectores de acimut alrededor del centro.

    Una orbita completa llena los doce sectores; una pasada en linea recta
    llena dos o tres. Es la forma rapida de distinguir un vuelo que sirve para
    reconstruir un edificio de uno que no.
    """
    if len(points) < 2:
        return np.zeros(sectors, int), 0.
    centre = points[:, :2].mean(axis=0)
    angles = np.degrees(np.arctan2(points[:, 1] - centre[1], points[:, 0] - centre[0]))
    counts, _ = np.histogram(angles, bins=sectors, range=(-180., 180.))
    return counts, float((counts > 0).mean())


def summary(shots):
    """Resumen del vuelo, con el criterio de si sirve para reconstruir."""
    if not shots:
        return {'shots': 0, 'usable': False, 'reason': 'archivo vacio'}
    points = positions(shots)
    deviations = sigmas(shots)
    steps = np.linalg.norm(np.diff(points, axis=0), axis=1)
    counts, filled = azimuth_coverage(points)
    numbers = np.array([s['shot'] for s in shots])
    spread = angular_spread(points)
    out = {
        'shots': len(shots),
        'missing': int(numbers.max() - numbers.min() + 1 - len(numbers)),
        'seconds': float(shots[-1]['tow'] - shots[0]['tow']),
        'interval': float(np.median(np.diff([s['tow'] for s in shots]))),
        'travelled': float(steps.sum()),
        'extent': tuple(float(np.ptp(points[:, i])) for i in range(3)),
        'spread': spread,
        'azimuth_filled': filled,
        'sigma_median': tuple(np.median(deviations, axis=0)),
        'sigma_max': tuple(deviations.max(axis=0)),
        'flags': {int(k): int(v) for k, v in zip(*np.unique([s['flag'] for s in shots],
                                                            return_counts=True))},
        'usable': True, 'reason': '',
    }
    if out['travelled'] < 5.:
        out['usable'], out['reason'] = False, 'el dron apenas se mueve: sin paralaje'
    elif spread < 20.:
        out['usable'], out['reason'] = False, f'solo {spread:.0f} grados barridos'
    return out


def match_photos(shots, names):
    """Empareja disparos con nombres de foto por orden.

    El .MRK numera los disparos y las fotos llevan su indice en el nombre, pero
    un disparo puede quedarse sin imagen -en este vuelo falta uno-, asi que el
    emparejamiento por posicion en la lista es fragil. Se empareja por el
    numero de disparo, que es el unico dato comun fiable.
    """
    by_number = {}
    for name in names:
        digits = [p for p in name.replace('.', '_').split('_') if p.isdigit()]
        if digits:
            by_number[int(digits[-1] if len(digits[-1]) <= 5 else digits[-2])] = name
    out = []
    for shot in shots:
        out.append((shot, by_number.get(shot['shot'])))
    return out
