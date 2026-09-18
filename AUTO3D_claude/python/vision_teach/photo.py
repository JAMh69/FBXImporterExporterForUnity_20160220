"""De una foto de dron DJI a una camara con pose, sin fotogrametria.

Una foto suelta trae en su EXIF y su XMP todo lo que hace falta: posicion GPS,
altura sobre el despegue y los tres angulos del gimbal. Con dos fotos asi de
un mismo edificio ya se puede triangular, sin pasar por COLMAP.

Es una pose *aproximada*: la limita la precision del GPS, del orden de metros
sin RTK. Sirve para arrancar, para descartar tomas inutiles y para dar medidas
con su incertidumbre; la fotogrametria despues la refina.

El video no vale para esto: su .SRT trae posicion y altura pero **no los
angulos del gimbal**. Por eso las fotos son mejores que el video.
"""
import re
from datetime import datetime

import numpy as np

from .multiview import Camera

EARTH = 6378137.0
XMP = re.compile(r'(?:drone-dji|tiff|exif):(\w+)\s*=\s*"([^"]*)"')
XMP_TAG = re.compile(r'<(?:drone-dji|tiff|exif):(\w+)>([^<]*)</')
SENSOR_35MM_WIDTH = 36.0
SENSOR_35MM_DIAGONAL = 43.266615


def read_xmp(path):
    """Bloque XMP de un JPEG, como diccionario. {} si no lo lleva."""
    data = open(path, 'rb').read()
    start = data.find(b'<x:xmpmeta')
    if start < 0:
        return {}
    end = data.find(b'</x:xmpmeta>')
    text = data[start:end + 12].decode('utf-8', 'replace')
    out = {}
    for pattern in (XMP, XMP_TAG):
        for key, value in pattern.findall(text):
            out[key] = value.strip()
    return out


def read_exif(path):
    from PIL import Image
    from PIL.ExifTags import TAGS
    image = Image.open(path)
    exif = image.getexif()
    out = {'width': image.size[0], 'height': image.size[1]}
    for table in (exif, exif.get_ifd(0x8769)):
        for key, value in table.items():
            out[TAGS.get(key, key)] = value
    return out


def focal_in_pixels(exif, xmp=None, convention='horizontal'):
    """Focal en pixeles a partir del EXIF.

    `FocalLengthIn35mmFilm` se refiere, segun el fabricante, al **ancho** de un
    fotograma de 35 mm o a su **diagonal**. Entre las dos convenciones hay un
    4 % en este equipo, y una foto suelta no permite decidir cual es: hace
    falta una distancia conocida en el terreno, o dejar que la fotogrametria
    ajuste la focal a partir de muchas imagenes. Por eso la convencion es un
    parametro explicito y no una suposicion escondida.
    """
    width, height = exif['width'], exif['height']
    equivalent = exif.get('FocalLengthIn35mmFilm')
    if equivalent:
        if convention == 'horizontal':
            return float(width) * float(equivalent) / SENSOR_35MM_WIDTH
        if convention == 'diagonal':
            return float(np.hypot(width, height)) * float(equivalent) / SENSOR_35MM_DIAGONAL
        raise ValueError("convencion debe ser 'horizontal' o 'diagonal'")
    raise ValueError('el EXIF no trae FocalLengthIn35mmFilm')


def rotation_from_gimbal(yaw_deg, pitch_deg, roll_deg=0.):
    """Rotacion mundo -> camara a partir de los angulos del gimbal de DJI.

    Mundo en ENU (este, norte, arriba). Camara con x a la derecha, y hacia
    abajo y z hacia delante, que es el convenio de OpenCV y de COLMAP.

    DJI mide el guiñado desde el norte en sentido horario, y el cabeceo con
    0 en la horizontal y -90 mirando al suelo.
    """
    yaw, pitch, roll = np.radians([yaw_deg, pitch_deg, roll_deg])
    forward = np.array([np.cos(pitch) * np.sin(yaw),
                        np.cos(pitch) * np.cos(yaw),
                        np.sin(pitch)])
    right = np.array([np.cos(yaw), -np.sin(yaw), 0.])
    down = np.cross(forward, right)
    if roll:                                        # alabeo alrededor del eje optico
        c, s = np.cos(roll), np.sin(roll)
        right, down = c * right + s * down, -s * right + c * down
    return np.vstack([right, down, forward])


def local_metres(latitude, longitude, reference):
    """(este, norte) en metros respecto a una latitud y longitud de referencia."""
    scale = np.cos(np.radians(reference[0]))
    east = np.radians(longitude - reference[1]) * EARTH * scale
    north = np.radians(latitude - reference[0]) * EARTH
    return east, north


def read_photo(path, reference=None, convention='horizontal'):
    """Lee una foto de dron y devuelve (Camera, datos).

    `reference` es la latitud y longitud del origen local; si no se da, se usa
    la de la propia foto, que queda entonces en el origen.
    """
    exif, xmp = read_exif(path), read_xmp(path)
    if 'GpsLatitude' not in xmp or 'GimbalPitchDegree' not in xmp:
        raise ValueError('la foto no trae XMP de DJI con posicion y angulos de gimbal; '
                         'comprueba que es el archivo original y no una copia recomprimida')
    latitude, longitude = float(xmp['GpsLatitude']), float(xmp['GpsLongitude'])
    height = float(xmp['RelativeAltitude'])
    reference = reference or (latitude, longitude)
    east, north = local_metres(latitude, longitude, reference)
    rotation = rotation_from_gimbal(float(xmp['GimbalYawDegree']),
                                    float(xmp['GimbalPitchDegree']),
                                    float(xmp.get('GimbalRollDegree', 0.)))
    centre = np.array([east, north, height])
    focal = focal_in_pixels(exif, xmp, convention)
    camera = Camera(focal, (exif['width'] / 2., exif['height'] / 2.),
                    rotation, -rotation @ centre,
                    name=str(path).split('/')[-1],
                    size=(exif['width'], exif['height']))
    info = {'latitude': latitude, 'longitude': longitude, 'height': height,
            'gimbal': (float(xmp['GimbalYawDegree']), float(xmp['GimbalPitchDegree']),
                       float(xmp.get('GimbalRollDegree', 0.))),
            'model': xmp.get('DroneModel', exif.get('Model', '')),
            'gps_status': xmp.get('GpsStatus', ''),
            'absolute_altitude': float(xmp.get('AbsoluteAltitude', 'nan')),
            'focal': focal, 'convention': convention,
            'taken': exif.get('DateTimeOriginal', ''),
            'size': (exif['width'], exif['height'])}
    return camera, info


def read_folder(paths, convention='horizontal'):
    """Varias fotos en un mismo origen local. Devuelve (camaras, datos)."""
    paths = list(paths)
    if not paths:
        return [], []
    first = read_xmp(paths[0])
    reference = (float(first['GpsLatitude']), float(first['GpsLongitude']))
    cameras, infos = [], []
    for path in paths:
        camera, info = read_photo(path, reference, convention)
        cameras.append(camera)
        infos.append(info)
    return cameras, infos


def ground_sampling(camera, height_above_ground):
    """Tamaño de un pixel sobre el suelo, en metros. Solo en toma cenital."""
    return height_above_ground / camera.focal[0]


def nadir_footprint(camera, height_above_ground):
    """Huella rectangular en el suelo de una toma cenital, en metros."""
    gsd = ground_sampling(camera, height_above_ground)
    return camera.size[0] * gsd, camera.size[1] * gsd
