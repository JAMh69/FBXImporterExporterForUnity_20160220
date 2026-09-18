"""Seguimiento de anotaciones entre fotogramas.

Lo que hoy falta en la aplicacion: las marcas se guardan por (hash de archivo,
numero de frame) y hay que rehacerlas en cada fotograma. Con esto una fachada
marcada una vez se sigue sola, y el usuario solo corrige donde se desvia.
"""
import numpy as np
import cv2

LK = dict(winSize=(21, 21), maxLevel=3,
          criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, .01))


def track(previous_gray, gray, points, forward_backward=1.6):
    """Sigue puntos de un fotograma al siguiente y devuelve (puntos, validos).

    Comprobacion de ida y vuelta: se sigue A->B y despues B->A; si el punto no
    regresa a su sitio, se descarta. Sin esto, una fachada con ventanas
    repetidas engancha en la ventana contigua y devuelve un resultado
    equivocado *con residuo bajo*, es decir, un error que no se nota. Es
    preferible perder un vertice -el usuario lo vuelve a marcar- que arrastrar
    uno mal puesto durante doscientos fotogramas.
    """
    points = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
    if len(points) == 0:
        return np.empty((0, 2), np.float32), np.empty(0, bool)
    ahead, status, _ = cv2.calcOpticalFlowPyrLK(previous_gray, gray, points, None, **LK)
    back, status_back, _ = cv2.calcOpticalFlowPyrLK(gray, previous_gray, ahead, None, **LK)
    distance = np.linalg.norm(points.reshape(-1, 2) - back.reshape(-1, 2), axis=1)
    good = (status.ravel() == 1) & (status_back.ravel() == 1) & (distance <= forward_backward)
    return ahead.reshape(-1, 2), good


def track_annotation(previous_gray, gray, points, minimum_ratio=.5, forward_backward=1.6):
    """Sigue un poligono completo. Devuelve None si pierde demasiados vertices.

    Un poligono con la mitad de los vertices mal colocados no es una anotacion
    util, y arrastrarlo ensucia el dataset: mejor no propagarlo.
    """
    moved, good = track(previous_gray, gray, points, forward_backward)
    if len(good) == 0 or good.mean() < minimum_ratio:
        return None
    result = np.asarray(points, dtype=np.float64).copy()
    result[good] = moved[good]
    return result


def interpolate(keyframes, index):
    """Posicion en un fotograma a partir de los fotogramas clave del usuario.

    `keyframes` es {numero_de_frame: puntos}. Entre dos claves se interpola
    linealmente; fuera del rango se mantiene la clave mas cercana. Asi el
    usuario corrige en dos o tres fotogramas y el resto sale solo.
    """
    if not keyframes:
        return None
    if index in keyframes:
        return np.asarray(keyframes[index], dtype=np.float64)
    order = sorted(keyframes)
    if index <= order[0]:
        return np.asarray(keyframes[order[0]], dtype=np.float64)
    if index >= order[-1]:
        return np.asarray(keyframes[order[-1]], dtype=np.float64)
    low = max(k for k in order if k <= index)
    high = min(k for k in order if k >= index)
    first = np.asarray(keyframes[low], dtype=np.float64)
    second = np.asarray(keyframes[high], dtype=np.float64)
    if first.shape != second.shape:
        return first
    ratio = (index - low) / (high - low)
    return first + (second - first) * ratio
