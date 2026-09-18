"""Geometria de escena: aristas rectas, puntos de fuga, calibracion y 3D.

Complementa a `detection.py`. Alli una "arista" es un contorno de Canny y un
"plano" una mancha de color Lab; aqui una arista es un segmento recto asignado
a un punto de fuga, y un plano un cuadrilatero con normal en el espacio.

Supuestos: mundo de Manhattan (tres direcciones ortogonales dominantes), camara
pinhole sin distorsion y centro optico en el centro de la imagen. La escala
metrica viene de un unico dato externo: la altura de la camara sobre el suelo.

Sin dependencias fuera de numpy y OpenCV, que ya estan en requirements.txt.
"""
import numpy as np
import cv2

EPS = 1e-9


# --------------------------------------------------------------------------
# 1. De pixeles de borde a segmentos rectos
# --------------------------------------------------------------------------
def segments(frame, low, high, min_length=26., epsilon=1.8):
    """Devuelve (segmentos Nx4, mapa de bordes).

    Reutiliza el mismo Canny que `detection.detect`, de modo que los umbrales
    que aprende el Random Forest calibran tambien esta parte. Los contornos se
    parten en tramos rectos con approxPolyDP: a diferencia de HoughLinesP, cada
    tramo conserva sus extremos reales, que es lo que necesitan tanto el
    cuadrilatero de un plano como el seguimiento de un vertice.
    """
    gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    edges = cv2.Canny(gray, int(low), int(high), L2gradient=True)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    out = []
    for contour in contours:
        if len(contour) < 3:
            continue
        polyline = cv2.approxPolyDP(contour, epsilon, False).reshape(-1, 2)
        for a, b in zip(polyline[:-1], polyline[1:]):
            if np.hypot(*(b - a)) >= min_length:
                out.append([a[0], a[1], b[0], b[1]])
    return np.asarray(out, dtype=np.float64).reshape(-1, 4), edges


def _parts(segs):
    """Precalcula recta homogenea, direccion unitaria, punto medio y longitud."""
    p, q = segs[:, :2], segs[:, 2:]
    ones = np.ones((len(segs), 1))
    lines = np.cross(np.hstack([p, ones]), np.hstack([q, ones]))
    delta = q - p
    length = np.linalg.norm(delta, axis=1)
    direction = delta / np.maximum(length, EPS)[:, None]
    return lines, direction, (p + q) / 2, length


def _cosines(vanishing, mids, directions):
    """|cos| del angulo entre cada segmento y la direccion hacia el punto de fuga."""
    if abs(vanishing[2]) > EPS:
        towards = vanishing[:2] / vanishing[2] - mids
    else:                                    # punto de fuga en el infinito
        towards = np.broadcast_to(vanishing[:2], mids.shape)
    towards = towards / np.maximum(np.linalg.norm(towards, axis=1), EPS)[:, None]
    return np.abs(np.sum(towards * directions, axis=1))


# --------------------------------------------------------------------------
# 2. Puntos de fuga
# --------------------------------------------------------------------------
def vanishing_points(segs, iterations=900, tolerance_deg=2.2, maximum=3, seed=0):
    """RANSAC en cascada, con el voto ponderado por longitud.

    Un muro de 300 px debe pesar mas que diez ruidos de 30 px: contar segmentos
    en vez de longitud deja que la textura fina decida la direccion dominante.
    """
    if len(segs) < 4:
        return []
    lines, directions, mids, lengths = _parts(segs)
    threshold = np.cos(np.radians(tolerance_deg))
    rng = np.random.default_rng(seed)          # reproducible entre ejecuciones
    available = np.ones(len(segs), bool)
    found = []

    for _ in range(maximum):
        index = np.flatnonzero(available)
        if len(index) < 6:
            break
        best, best_score = None, 0.
        for _ in range(iterations):
            a, b = rng.choice(index, 2, replace=False)
            candidate = np.cross(lines[a], lines[b])
            norm = np.linalg.norm(candidate)
            if norm < EPS:
                continue
            candidate = candidate / norm
            hits = _cosines(candidate, mids[index], directions[index]) > threshold
            score = lengths[index][hits].sum()
            if score > best_score:
                best_score, best = score, candidate
        if best is None:
            break
        hits = index[_cosines(best, mids[index], directions[index]) > threshold]
        if len(hits) < 3:
            break
        best = refine(lines[hits], lengths[hits])
        hits = index[_cosines(best, mids[index], directions[index]) > threshold]
        if len(hits) < 3:
            break
        available[hits] = False
        found.append({'point': best, 'inliers': hits, 'weight': float(lengths[hits].sum())})

    found.sort(key=lambda item: -item['weight'])
    return found


def refine(lines, weights):
    """Minimiza sum w (l.v)^2 con |v|=1: autovector menor de sum w l l^T."""
    normalized = lines / np.maximum(np.linalg.norm(lines[:, :2], axis=1), EPS)[:, None]
    scatter = (normalized * weights[:, None]).T @ normalized
    _, vectors = np.linalg.eigh(scatter)
    return vectors[:, 0]


def labels(segs, found):
    """Indice de punto de fuga por segmento, o -1 si no pertenece a ninguno."""
    out = np.full(len(segs), -1, int)
    for i, item in enumerate(found):
        out[item['inliers']] = i
    return out


# --------------------------------------------------------------------------
# 3. Calibracion y horizonte
# --------------------------------------------------------------------------
def calibrate(found, width, height):
    """Focal a partir de dos puntos de fuga ortogonales: (u-pp).(v-pp) = -f^2.

    Devuelve None si no hay ninguna pareja valida, que es lo que ocurre cuando
    se fotografia una fachada de frente: un solo punto de fuga no da escala.
    """
    principal = np.array([width / 2., height / 2.])
    finite = [(i, item['point'][:2] / item['point'][2])
              for i, item in enumerate(found) if abs(item['point'][2]) > 1e-7]
    focals = []
    for a in range(len(finite)):
        for b in range(a + 1, len(finite)):
            product = np.dot(finite[a][1] - principal, finite[b][1] - principal)
            if product < -1.:
                focals.append(np.sqrt(-product))
    if not focals:
        return None
    focal = float(np.median(focals))
    if not np.isfinite(focal) or focal <= 0:
        return None

    directions = []
    for item in found:
        point = item['point']
        if abs(point[2]) > EPS:
            vector = np.r_[point[:2] / point[2] - principal, focal]
        else:
            vector = np.r_[point[:2], 0.]
        directions.append(vector / max(np.linalg.norm(vector), EPS))
    directions = np.asarray(directions)

    # la vertical del mundo es la direccion mas vertical en la imagen
    vertical = int(np.argmax(np.abs(directions[:, 1]) /
                             np.maximum(np.linalg.norm(directions[:, :2], axis=1), EPS)))
    up = directions[vertical].copy()
    if up[1] > 0:                              # "arriba" es y negativa en imagen
        up = -up
    return {'focal': focal, 'principal': principal, 'directions': directions,
            'vertical': vertical, 'up': up, 'samples': len(focals)}


def horizon(found, calibration):
    """Linea de fuga del plano horizontal.

    Con tres puntos de fuga es la recta que une los dos horizontales. Con solo
    dos -el caso corriente- se deriva de la vertical: l = K^-T . up. La primera
    version exigia tres y dejaba el horizonte sin calcular casi siempre.
    """
    if calibration is None:
        return None
    others = [item['point'] for i, item in enumerate(found) if i != calibration['vertical']]
    if len(others) >= 2:
        line = np.cross(others[0], others[1])
        if np.hypot(line[0], line[1]) > EPS:
            return line
    up, focal = calibration['up'], calibration['focal']
    cx, cy = calibration['principal']
    return np.array([up[0] / focal, up[1] / focal,
                     up[2] - (cx * up[0] + cy * up[1]) / focal])


def horizon_y(line, width):
    """Altura del horizonte en el centro de la imagen, o None si es vertical."""
    if line is None or abs(line[1]) < EPS:
        return None
    return float(-(line[0] * width / 2. + line[2]) / line[1])


# --------------------------------------------------------------------------
# 4. Planos candidatos
# --------------------------------------------------------------------------
def edge_support(edges, a, b, tolerance=2):
    """Fraccion del segmento a-b que discurre sobre pixeles de borde reales.

    Es lo que separa un cuadrilatero apoyado en la fachada de otro que solo
    existe porque dos rectas se cruzan en el cielo.
    """
    height, width = edges.shape
    length = np.hypot(*(np.asarray(b) - np.asarray(a)))
    if length < 2:
        return 0.
    count = max(4, int(length / 2))
    t = np.linspace(0., 1., count + 1)
    xs = np.clip(np.round(a[0] + (b[0] - a[0]) * t).astype(int), 0, width - 1)
    ys = np.clip(np.round(a[1] + (b[1] - a[1]) * t).astype(int), 0, height - 1)
    hit = np.zeros(len(t), bool)
    for dy in range(-tolerance, tolerance + 1):
        for dx in range(-tolerance, tolerance + 1):
            hit |= edges[np.clip(ys + dy, 0, height - 1),
                         np.clip(xs + dx, 0, width - 1)] > 0
    return float(hit.mean())


def plane_candidates(segs, group, edges, support=.42, maximum=12, per_family=9):
    """Cuadrilateros formados por dos rectas de una familia y dos de otra.

    Se puntuan por soporte de borde, no por su area ni por lo bien que encajan
    entre si: un plano sin bordes que lo sostengan no esta en la fotografia.
    """
    height, width = edges.shape
    lines, _, _, lengths = _parts(segs)
    families = sorted({int(g) for g in group if g >= 0})
    found = []

    def longest(family):
        index = np.flatnonzero(group == family)
        return index[np.argsort(-lengths[index])][:per_family]

    for i in range(len(families)):
        for j in range(i + 1, len(families)):
            first, second = longest(families[i]), longest(families[j])
            for a1 in range(len(first)):
                for a2 in range(a1 + 1, len(first)):
                    for b1 in range(len(second)):
                        for b2 in range(b1 + 1, len(second)):
                            corners = _quad(lines, first[a1], first[a2], second[b1], second[b2])
                            if corners is None:
                                continue
                            if (corners[:, 0] < -width * .25).any() or (corners[:, 0] > width * 1.25).any():
                                continue
                            if (corners[:, 1] < -height * .25).any() or (corners[:, 1] > height * 1.25).any():
                                continue
                            area = abs(cv2.contourArea(corners.astype(np.float32)))
                            if not (width * height * .012 <= area <= width * height * .94):
                                continue
                            score = np.mean([edge_support(edges, corners[k], corners[(k + 1) % 4])
                                             for k in range(4)])
                            if score >= support:
                                found.append({'corners': corners, 'score': float(score),
                                              'area': float(area),
                                              'families': (families[i], families[j])})

    found.sort(key=lambda item: -item['score'] * np.sqrt(item['area']))
    kept = []
    for candidate in found:
        centre = candidate['corners'].mean(axis=0)
        radius = np.sqrt(max(candidate['area'], 1.)) * .45
        if all(np.hypot(*(centre - k['corners'].mean(axis=0))) >= radius for k in kept):
            kept.append(candidate)
            if len(kept) >= maximum:
                break
    return kept


def _quad(lines, a1, a2, b1, b2):
    corners = []
    for first, second in ((a1, b1), (a1, b2), (a2, b2), (a2, b1)):
        point = np.cross(lines[first], lines[second])
        if abs(point[2]) < 1e-12:
            return None
        corners.append(point[:2] / point[2])
    return np.asarray(corners)


# --------------------------------------------------------------------------
# 5. Reconstruccion metrica de una sola vista
# --------------------------------------------------------------------------
HORIZONTAL, VERTICAL, FREE = 'horizontal', 'vertical', 'libre'


def ray(calibration, point):
    return np.r_[point[0] - calibration['principal'][0],
                 point[1] - calibration['principal'][1], calibration['focal']]


def ground_point(calibration, point, camera_height):
    """Interseccion del rayo con el suelo, o None si mira por encima del horizonte."""
    direction = ray(calibration, point)
    denominator = float(np.dot(direction, calibration['up']))
    if denominator > -1e-6:
        return None
    distance = -camera_height / denominator
    return direction * distance if distance > 0 else None


def plane_point(calibration, point, normal, offset):
    direction = ray(calibration, point)
    denominator = float(np.dot(direction, normal))
    if abs(denominator) < EPS:
        return None
    distance = offset / denominator
    return direction * distance if distance > 0 else None


def reconstruct(points, axis, calibration, camera_height):
    """Lleva un poligono de la imagen al espacio metrico.

    La clase semantica decide la geometria: un suelo se apoya entero en el
    plano del terreno; una fachada se ancla por sus dos vertices mas bajos y
    el resto se proyecta sobre el plano vertical que pasa por ellos. Por eso
    etiquetar bien no es cosmetica.
    """
    if calibration is None:
        return {'error': 'sin calibracion: hacen falta dos puntos de fuga ortogonales'}
    points = np.asarray(points, dtype=np.float64)
    if len(points) < 3:
        return {'error': 'un plano necesita al menos tres vertices'}

    if axis == HORIZONTAL:
        space = []
        for point in points:
            found = ground_point(calibration, point, camera_height)
            if found is None:
                return {'error': 'vertice por encima del horizonte: no se apoya en el suelo'}
            space.append(found)
        return {'points': np.asarray(space), 'method': 'suelo'}

    order = np.argsort(-points[:, 1])            # de mas bajo a mas alto en imagen
    base = ground_point(calibration, points[order[0]], camera_height)
    other = None
    for index in order[1:]:
        candidate = ground_point(calibration, points[index], camera_height)
        if candidate is not None and np.hypot(*(points[index] - points[order[0]])) > 8:
            other = candidate
            break
    if base is None or other is None:
        return {'error': 'no hay dos vertices apoyables en el suelo (base oculta u horizonte)'}

    along = other - base
    along /= max(np.linalg.norm(along), EPS)
    normal = np.cross(along, calibration['up'])
    normal /= max(np.linalg.norm(normal), EPS)
    offset = float(np.dot(normal, base))
    space = []
    for point in points:
        found = plane_point(calibration, point, normal, offset)
        if found is None:
            return {'error': 'vertice paralelo al plano: geometria degenerada'}
        space.append(found)
    result = {'points': np.asarray(space), 'method': 'vertical', 'normal': normal}
    if axis == FREE:
        result['warning'] = 'clase sin eje definido: se ha supuesto plano vertical'
    return result


def world_axes(calibration):
    """Terna ortonormal alineada con el mundo de Manhattan (X, arriba, Z)."""
    up = calibration['up']
    horizontal = [d for i, d in enumerate(calibration['directions'])
                  if i != calibration['vertical']]
    first = horizontal[0] if horizontal else np.array([1., 0., 0.])
    first = first - up * np.dot(first, up)
    norm = np.linalg.norm(first)
    if norm < 1e-6:                              # degenerado: cualquier perpendicular sirve
        first = np.cross(up, [0., 0., 1.])
        norm = np.linalg.norm(first)
    first /= max(norm, EPS)
    return first, up, np.cross(up, first)


def to_world(calibration, points):
    first, up, third = world_axes(calibration)
    points = np.atleast_2d(points)
    return np.column_stack([points @ first, points @ up, points @ third])
