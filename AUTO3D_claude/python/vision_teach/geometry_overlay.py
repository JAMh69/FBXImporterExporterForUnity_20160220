"""Puente entre `geometry.py` y la aplicacion: una llamada y un dibujo.

Se mantiene aparte para que `geometry.py` no sepa nada de colores ni de BGR:
la geometria se puede probar sin dibujar, y el dibujo se puede cambiar sin
tocar la matematica.
"""
import numpy as np
import cv2

from . import geometry as geo

FAMILY_COLOURS = ((95, 95, 255), (157, 255, 95), (255, 168, 95))    # BGR
HORIZON_COLOUR = (95, 210, 255)
PLANE_COLOUR = (255, 211, 127)


def analyse(frame, parameters, camera_height=1.6):
    """Ejecuta la cadena geometrica sobre un fotograma ya calibrado.

    `parameters` es el diccionario que devuelve `Learner.parameters`: los mismos
    umbrales que el Random Forest ha aprendido sirven aqui, de modo que enseñar
    a la aplicacion mejora tambien la geometria, no solo el dibujo de contornos.
    """
    height, width = frame.shape[:2]
    segs, edges = geo.segments(frame, parameters['low'], parameters['high'])
    found = geo.vanishing_points(segs)
    group = geo.labels(segs, found)
    calibration = geo.calibrate(found, width, height)
    line = geo.horizon(found, calibration)
    return {'segments': segs, 'groups': group, 'edge_map': edges,
            'vanishing': found, 'calibration': calibration,
            'horizon': line, 'horizon_y': geo.horizon_y(line, width),
            'planes': geo.plane_candidates(segs, group, edges),
            'camera_height': camera_height}


def draw(image, analysis):
    """Superpone aristas por familia, horizonte y planos candidatos."""
    result = image.copy()
    segs, group = analysis['segments'], analysis['groups']
    for segment, family in zip(segs, group):
        colour = FAMILY_COLOURS[family % len(FAMILY_COLOURS)] if family >= 0 else (150, 150, 150)
        cv2.line(result, tuple(segment[:2].astype(int)), tuple(segment[2:].astype(int)), colour, 1)
    for plane in analysis['planes']:
        corners = plane['corners'].astype(np.int32)
        cv2.polylines(result, [corners], True, PLANE_COLOUR, 1)
        centre = corners.mean(axis=0).astype(int)
        cv2.putText(result, f"{plane['score'] * 100:.0f}%", tuple(centre),
                    cv2.FONT_HERSHEY_SIMPLEX, .4, PLANE_COLOUR, 1, cv2.LINE_AA)
    y = analysis['horizon_y']
    if y is not None and -1e4 < y < 1e4:
        cv2.line(result, (0, int(y)), (result.shape[1], int(y)), HORIZON_COLOUR, 1, cv2.LINE_AA)
        cv2.putText(result, 'horizonte', (8, int(y) - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, .4, HORIZON_COLOUR, 1, cv2.LINE_AA)
    return result


def summary(analysis):
    """Una linea para la barra de estado, en el idioma de la aplicacion."""
    calibration = analysis['calibration']
    parts = [f"{len(analysis['segments'])} aristas rectas",
             f"{len(analysis['vanishing'])} puntos de fuga",
             f"{len(analysis['planes'])} planos"]
    if calibration is None:
        parts.append('sin calibracion: fotografia por la esquina del edificio')
    else:
        width = analysis['edge_map'].shape[1]
        field = 2 * np.degrees(np.arctan(width / 2 / calibration['focal']))
        parts.append(f"focal {calibration['focal']:.0f} px, campo {field:.0f}°")
    return ' · '.join(parts)


def measure(analysis, points, axis):
    """Dimensiones metricas de un poligono anotado, o el motivo de no poder."""
    result = geo.reconstruct(points, axis, analysis['calibration'], analysis['camera_height'])
    if 'error' in result:
        return result
    world = geo.to_world(analysis['calibration'], result['points'])
    sides = np.linalg.norm(world - np.roll(world, -1, axis=0), axis=1)
    return {'world': world, 'sides': sides, 'method': result['method'],
            'height': float(world[:, 1].max() - world[:, 1].min()),
            'warning': result.get('warning')}
