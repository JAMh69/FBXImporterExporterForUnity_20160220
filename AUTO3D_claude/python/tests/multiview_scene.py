"""Camaras sinteticas con pose conocida, para medir la triangulacion.

Mundo con Z hacia arriba, como en fotogrametria. La camara mira al edificio
desde varias posiciones de un arco, imitando un vuelo alrededor.
"""
import numpy as np

from vision_teach.multiview import Camera

FOCAL, WIDTH, HEIGHT = 2800., 4000., 3000.


def look_at(position, target, name='', world_up=(0., 0., 1.)):
    position = np.asarray(position, float)
    forward = np.asarray(target, float) - position
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, np.asarray(world_up, float))
    if np.linalg.norm(right) < 1e-8:                 # mirando justo hacia abajo
        right = np.cross(forward, np.array([0., 1., 0.]))
    right /= np.linalg.norm(right)
    down = np.cross(forward, right)
    rotation = np.vstack([right, down, forward])     # mundo -> camara
    return Camera(FOCAL, (WIDTH / 2, HEIGHT / 2), rotation, -rotation @ position,
                  name=name or f'IMG_{position[0]:.0f}_{position[1]:.0f}.JPG',
                  size=(WIDTH, HEIGHT))


def orbit(count=6, radius=60., altitude=45., target=(0., 0., 5.), start=0., sweep=360.):
    """Vuelo circular alrededor del edificio, como una mision de DJI."""
    target = np.asarray(target, float)
    cameras = []
    for i in range(count):
        angle = np.radians(start + sweep * i / count)
        position = target + np.array([radius * np.cos(angle), radius * np.sin(angle),
                                      altitude - target[2]])
        cameras.append(look_at(position, target, name=f'DJI_{i:04d}.JPG'))
    return cameras


# edificio de 20 x 10 m en planta y 8 m de altura de alero,
# con cubierta a dos aguas de 3 m de flecha
EAVES, RIDGE = 8., 11.
FOOTPRINT = np.array([[-10., -5., 0.], [10., -5., 0.], [10., 5., 0.], [-10., 5., 0.]])
ROOF_SLOPE = np.array([[-10., -5., EAVES], [10., -5., EAVES],
                       [10., 0., RIDGE], [-10., 0., RIDGE]])
