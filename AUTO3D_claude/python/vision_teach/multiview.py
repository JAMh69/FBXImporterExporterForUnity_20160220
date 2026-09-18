"""Anotacion sobre varias vistas con las posiciones de camara conocidas.

El cambio de enfoque respecto a `tracking.py`: alli una marca se *arrastra* de
un fotograma al siguiente y el error se acumula; aqui, si se sabe donde estaba
la camara en cada toma, marcar el mismo punto en dos fotos da su posicion 3D
por interseccion de rayos, y a la inversa un punto 3D se proyecta sobre todas
las demas fotos por geometria. No hay deriva porque no hay cadena.

Las posiciones de camara vienen de la fotogrametria (COLMAP, OpenDroneMap).
Este modulo no las calcula: las consume.

Convenio, el de COLMAP: la pose es mundo -> camara, x_cam = R X + t, y el
centro de la camara en el mundo es C = -R^T t.
"""
import numpy as np

EPS = 1e-12


class Camera:
    """Camara pinhole con pose conocida.

    `distortion` se admite pero no se aplica: las imagenes de un flujo
    fotogrametrico llegan ya corregidas. Guardarlo evita que se pierda el dato
    y deja constancia de que la correccion es responsabilidad de quien prepara
    las imagenes, no de este modulo.
    """

    def __init__(self, focal, principal, rotation, translation, name='', size=None, distortion=None):
        self.focal = np.asarray(focal, float).reshape(-1)          # (fx, fy) o (f,)
        if self.focal.size == 1:
            self.focal = np.array([self.focal[0], self.focal[0]])
        self.principal = np.asarray(principal, float)
        self.rotation = np.asarray(rotation, float).reshape(3, 3)
        self.translation = np.asarray(translation, float).reshape(3)
        self.name = name
        self.size = size
        self.distortion = distortion

    @property
    def centre(self):
        """Posicion de la camara en el mundo."""
        return -self.rotation.T @ self.translation

    def matrix(self):
        """Matriz de proyeccion 3x4."""
        intrinsic = np.array([[self.focal[0], 0., self.principal[0]],
                              [0., self.focal[1], self.principal[1]],
                              [0., 0., 1.]])
        return intrinsic @ np.hstack([self.rotation, self.translation[:, None]])

    def project(self, points):
        """Proyecta puntos del mundo. Devuelve (pixeles, delante_de_la_camara)."""
        points = np.atleast_2d(np.asarray(points, float))
        camera = points @ self.rotation.T + self.translation
        depth = camera[:, 2]
        safe = np.where(np.abs(depth) < EPS, EPS, depth)
        pixels = np.column_stack([
            self.focal[0] * camera[:, 0] / safe + self.principal[0],
            self.focal[1] * camera[:, 1] / safe + self.principal[1]])
        return pixels, depth > 0

    def ray(self, pixel):
        """Direccion unitaria en el mundo del rayo que pasa por un pixel."""
        pixel = np.asarray(pixel, float)
        direction = np.array([(pixel[0] - self.principal[0]) / self.focal[0],
                              (pixel[1] - self.principal[1]) / self.focal[1], 1.])
        world = self.rotation.T @ direction
        return world / max(np.linalg.norm(world), EPS)

    def looks_at(self, points, margin=0):
        """Que puntos caen dentro del encuadre (necesita `size`)."""
        pixels, ahead = self.project(points)
        if self.size is None:
            return ahead
        width, height = self.size
        inside = ((pixels[:, 0] >= -margin) & (pixels[:, 0] < width + margin) &
                  (pixels[:, 1] >= -margin) & (pixels[:, 1] < height + margin))
        return ahead & inside


# --------------------------------------------------------------------------
# Triangulacion
# --------------------------------------------------------------------------
def triangulate(cameras, pixels, refine=True):
    """Punto 3D a partir de la misma marca en dos o mas fotos.

    DLT para arrancar y despues minimizacion del error de reproyeccion. El DLT
    minimiza un residuo algebraico que no es el error en pixeles; sin el
    refinado, una vista muy oblicua sesga el resultado.
    """
    if len(cameras) < 2:
        raise ValueError('hacen falta al menos dos vistas para triangular')
    rows = []
    for camera, pixel in zip(cameras, pixels):
        P = camera.matrix()
        rows.append(pixel[0] * P[2] - P[0])
        rows.append(pixel[1] * P[2] - P[1])
    _, _, vt = np.linalg.svd(np.asarray(rows))
    homogeneous = vt[-1]
    if abs(homogeneous[3]) < EPS:
        raise ValueError('rayos casi paralelos: las vistas estan demasiado juntas')
    point = homogeneous[:3] / homogeneous[3]
    if refine:
        point = _refine(cameras, np.asarray(pixels, float), point)
    return point


def _refine(cameras, pixels, point, iterations=12):
    """Gauss-Newton sobre el error de reproyeccion, con amortiguacion."""
    current = point.copy()
    damping = 1e-6
    for _ in range(iterations):
        jacobian, residual = [], []
        for camera, pixel in zip(cameras, pixels):
            local = camera.rotation @ current + camera.translation
            if local[2] <= EPS:
                return current                      # detras de la camara: no seguir
            fx, fy = camera.focal
            u = fx * local[0] / local[2] + camera.principal[0]
            v = fy * local[1] / local[2] + camera.principal[1]
            # d(u,v)/d(local) y regla de la cadena con R
            partial = np.array([[fx / local[2], 0., -fx * local[0] / local[2] ** 2],
                                [0., fy / local[2], -fy * local[1] / local[2] ** 2]])
            jacobian.append(partial @ camera.rotation)
            residual.append([pixel[0] - u, pixel[1] - v])
        jacobian = np.vstack(jacobian)
        residual = np.asarray(residual).reshape(-1)
        normal = jacobian.T @ jacobian + damping * np.eye(3)
        try:
            step = np.linalg.solve(normal, jacobian.T @ residual)
        except np.linalg.LinAlgError:
            return current
        current = current + step
        if np.linalg.norm(step) < 1e-9:
            break
    return current


def reprojection_error(cameras, pixels, point):
    """Error en pixeles de cada vista. Es el numero que debe ver el usuario:
    si una marca reproyecta a 40 px, esa marca esta mal puesta."""
    errors = []
    for camera, pixel in zip(cameras, pixels):
        projected, ahead = camera.project(point)
        errors.append(np.linalg.norm(projected[0] - np.asarray(pixel, float))
                      if ahead[0] else np.inf)
    return np.asarray(errors)


def triangulate_polygon(cameras, polygons, refine=True):
    """Triangula un contorno marcado en varias vistas, vertice a vertice.

    Todas las vistas deben tener el mismo numero de vertices y en el mismo
    orden: es responsabilidad de la interfaz, y conviene que lo impida antes
    de llegar aqui en vez de fallar luego.
    """
    counts = {len(p) for p in polygons}
    if len(counts) != 1:
        raise ValueError('el contorno tiene distinto numero de vertices en cada vista')
    points, errors = [], []
    for index in range(counts.pop()):
        marks = [np.asarray(p[index], float) for p in polygons]
        point = triangulate(cameras, marks, refine)
        points.append(point)
        errors.append(reprojection_error(cameras, marks, point).max())
    return np.asarray(points), np.asarray(errors)


# --------------------------------------------------------------------------
# Propagacion: de un punto 3D a todas las fotos
# --------------------------------------------------------------------------
def propagate(points3d, cameras, margin=0, minimum_visible=1.):
    """Donde cae una marca 3D en cada foto.

    Devuelve {nombre: pixeles} solo para las camaras que ven la fraccion pedida
    de los vertices. Esto es lo que sustituye al seguimiento: marcar una vez y
    que aparezca en el resto por geometria, sin cadena de errores.
    """
    points3d = np.atleast_2d(points3d)
    out = {}
    for camera in cameras:
        pixels, _ = camera.project(points3d)
        visible = camera.looks_at(points3d, margin)
        if visible.mean() >= minimum_visible:
            out[camera.name] = pixels
    return out


# --------------------------------------------------------------------------
# Planos
# --------------------------------------------------------------------------
def fit_plane(points, iterations=200, threshold=.05, seed=0):
    """Plano por RANSAC: normal, distancia, residuos y mascara de inliers.

    Aqui "plano" es un plano de verdad, ajustado a puntos 3D. No es la mancha
    de color de `detection.py` ni el cuadrilatero de `geometry.py`.
    """
    points = np.atleast_2d(np.asarray(points, float))
    if len(points) < 3:
        raise ValueError('hacen falta al menos tres puntos')
    if len(points) == 3:
        return _plane_through(points)
    rng = np.random.default_rng(seed)
    best, best_count = None, -1
    for _ in range(iterations):
        sample = points[rng.choice(len(points), 3, replace=False)]
        try:
            normal, offset = _plane_through(sample)[:2]
        except ValueError:
            continue
        count = int((np.abs(points @ normal - offset) < threshold).sum())
        if count > best_count:
            best_count, best = count, (normal, offset)
    if best is None:
        raise ValueError('no se ha podido ajustar un plano')
    normal, offset = best
    inliers = np.abs(points @ normal - offset) < threshold
    if inliers.sum() >= 3:                          # reajuste por minimos cuadrados
        normal, offset = _plane_least_squares(points[inliers])
    residuals = points @ normal - offset
    return normal, offset, residuals, inliers


def _plane_through(three):
    normal = np.cross(three[1] - three[0], three[2] - three[0])
    length = np.linalg.norm(normal)
    if length < 1e-9:
        raise ValueError('los tres puntos estan alineados')
    normal = normal / length
    offset = float(normal @ three[0])
    return normal, offset, np.zeros(len(three)), np.ones(len(three), bool)


def _plane_least_squares(points):
    centre = points.mean(axis=0)
    _, _, vt = np.linalg.svd(points - centre)
    normal = vt[-1]
    return normal, float(normal @ centre)


def plane_angle(normal, up=(0., 0., 1.)):
    """Inclinacion del plano respecto a la horizontal, en grados.

    0 = horizontal (un suelo o una cubierta plana), 90 = vertical (una
    fachada). Los valores intermedios son faldones de cubierta, que es
    justamente lo que domina en una foto de dron y lo que la geometria
    monocular no sabia tratar.
    """
    up = np.asarray(up, float)
    up = up / max(np.linalg.norm(up), EPS)
    cosine = abs(float(np.asarray(normal) @ up))
    return float(np.degrees(np.arccos(np.clip(cosine, 0., 1.))))
