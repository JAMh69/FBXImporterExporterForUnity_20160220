"""Escena sintetica con verdad conocida, para medir error en vez de estimarlo.

Edificio en esquina: dos fachadas de 12 x 11 m sobre un suelo, camara a 1.60 m.
Al conocer la focal, el cabeceo y las dimensiones reales se puede afirmar
cuanto se equivoca cada etapa, que es la unica forma honesta de validar esto.
"""
import numpy as np
import cv2

WIDTH, HEIGHT, FOCAL = 800, 600, 620.
CAMERA = np.array([6., 1.6, -4.])
PITCH = np.radians(4.)


def _camera(points, yaw_deg):
    yaw = np.radians(yaw_deg)
    delta = np.atleast_2d(np.asarray(points, float)) - CAMERA
    x = delta[:, 0] * np.cos(yaw) - delta[:, 2] * np.sin(yaw)
    z = delta[:, 0] * np.sin(yaw) + delta[:, 2] * np.cos(yaw)
    y = delta[:, 1]
    return x, y * np.cos(PITCH) - z * np.sin(PITCH), y * np.sin(PITCH) + z * np.cos(PITCH)


def project(points, yaw_deg=28., shift=0.):
    """Proyeccion pinhole con y de imagen hacia abajo."""
    x, y, z = _camera(points, yaw_deg)
    z = np.maximum(z, .05)
    return np.column_stack([WIDTH / 2 + FOCAL * x / z + shift, HEIGHT / 2 - FOCAL * y / z])


def in_front(points, yaw_deg=28.):
    """True si todos los vertices estan delante de la camara.

    Sin esta comprobacion, un poligono que cruza el plano de la camara -el
    suelo extendido hacia atras- se proyecta dado la vuelta y cubre el cielo,
    y la escena de prueba deja de parecerse a una fotografia.
    """
    return bool((_camera(points, yaw_deg)[2] > .2).all())


def truth_calibration():
    """Calibracion exacta de la escena, en el formato de geometry.calibrate."""
    up = np.array([0., -np.cos(PITCH), np.sin(PITCH)])
    return {'focal': FOCAL, 'principal': np.array([WIDTH / 2., HEIGHT / 2.]),
            'directions': np.array([up]), 'vertical': 0, 'up': up, 'samples': 1}


FACADE = [[0, 0, 8], [12, 0, 8], [12, 11, 8], [0, 11, 8]]
SIDE = [[0, 0, 8], [0, 0, 22], [0, 11, 22], [0, 11, 8]]
GROUND_PATCH = [[0, 0, 8], [12, 0, 8], [12, 0, 20], [0, 0, 20]]


def render(yaw_deg=28., shift=0., noise=7., seed=0):
    image = np.full((HEIGHT, WIDTH, 3), (232, 196, 159), np.uint8)   # cielo (BGR)

    def quad(corners, colour, outline=(56, 68, 74)):
        if not in_front(corners, yaw_deg):
            return
        pts = project(corners, yaw_deg, shift).astype(np.int32)
        cv2.fillPoly(image, [pts], colour)
        cv2.polylines(image, [pts], True, outline, 2)

    # el suelo se extiende solo por delante de la camara
    quad([[-30, 0, 2], [45, 0, 2], [45, 0, 70], [-30, 0, 70]], (107, 111, 111), (107, 111, 111))
    quad(FACADE, (173, 195, 207))
    quad(SIDE, (149, 171, 183))
    for row in range(3):
        for column in range(4):
            x0, y0 = 1.2 + column * 2.7, 1.6 + row * 3.1
            quad([[x0, y0, 7.98], [x0 + 1.6, y0, 7.98],
                  [x0 + 1.6, y0 + 2, 7.98], [x0, y0 + 2, 7.98]], (92, 75, 59), (60, 48, 35))
            z0 = 9.4 + column * 3.
            quad([[-.02, y0, z0], [-.02, y0, z0 + 1.8],
                  [-.02, y0 + 2, z0 + 1.8], [-.02, y0 + 2, z0]], (90, 69, 53), (60, 48, 35))
    if noise:
        rng = np.random.default_rng(seed)
        image = np.clip(image.astype(np.int16) +
                        rng.normal(0, noise, image.shape).astype(np.int16), 0, 255).astype(np.uint8)
    return image


def side_lengths(points):
    points = np.asarray(points)
    return np.linalg.norm(points - np.roll(points, -1, axis=0), axis=1)
