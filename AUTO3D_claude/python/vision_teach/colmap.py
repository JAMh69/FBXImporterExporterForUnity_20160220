"""Lectura de la salida de COLMAP / OpenDroneMap (formato texto).

Solo lo necesario para construir `multiview.Camera`: intrinsecos y poses.
El resto del modelo (puntos, observaciones) no hace falta aqui.
"""
import numpy as np

from .multiview import Camera

# parametros por modelo de camara de COLMAP: (indices de fx, fy, cx, cy)
MODELS = {
    'SIMPLE_PINHOLE': (0, 0, 1, 2), 'PINHOLE': (0, 1, 2, 3),
    'SIMPLE_RADIAL': (0, 0, 1, 2), 'RADIAL': (0, 0, 1, 2),
    'SIMPLE_RADIAL_FISHEYE': (0, 0, 1, 2), 'RADIAL_FISHEYE': (0, 0, 1, 2),
    'OPENCV': (0, 1, 2, 3), 'OPENCV_FISHEYE': (0, 1, 2, 3),
    'FULL_OPENCV': (0, 1, 2, 3), 'FOV': (0, 1, 2, 3), 'THIN_PRISM_FISHEYE': (0, 1, 2, 3),
}


def quaternion_to_matrix(q):
    """COLMAP guarda (w, x, y, z), rotacion de mundo a camara."""
    w, x, y, z = np.asarray(q, float)
    norm = np.sqrt(w * w + x * x + y * y + z * z)
    if norm < 1e-12:
        raise ValueError('cuaternion nulo')
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def _rows(path):
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith('#'):
                yield line.split()


def read_cameras(path):
    out = {}
    for parts in _rows(path):
        identifier, model = int(parts[0]), parts[1]
        width, height = int(parts[2]), int(parts[3])
        values = [float(v) for v in parts[4:]]
        if model not in MODELS:
            raise ValueError(f'modelo de camara no contemplado: {model}')
        fx, fy, cx, cy = MODELS[model]
        out[identifier] = {'focal': (values[fx], values[fy]),
                           'principal': (values[cx], values[cy]),
                           'size': (width, height), 'model': model,
                           'distortion': values}
    return out


def read_images(path, cameras):
    """Devuelve la lista de camaras con pose. Las lineas de puntos 2D de
    COLMAP se alternan con las de imagen y aqui se descartan."""
    out, expect_pose = [], True
    for parts in _rows(path):
        if not expect_pose:
            expect_pose = True                       # esta era la fila de puntos 2D
            continue
        quaternion = [float(v) for v in parts[1:5]]
        translation = [float(v) for v in parts[5:8]]
        intrinsics = cameras[int(parts[8])]
        out.append(Camera(focal=intrinsics['focal'], principal=intrinsics['principal'],
                          rotation=quaternion_to_matrix(quaternion), translation=translation,
                          name=parts[9], size=intrinsics['size'],
                          distortion=intrinsics['distortion']))
        expect_pose = False
    return out


def read_model(directory):
    """Lee `cameras.txt` e `images.txt` de una carpeta de COLMAP."""
    from pathlib import Path
    directory = Path(directory)
    return read_images(directory / 'images.txt', read_cameras(directory / 'cameras.txt'))
