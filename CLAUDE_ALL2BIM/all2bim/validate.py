"""Validacion del modelo interno antes de exportar."""
from __future__ import annotations

import math

from .model import BimModel


def validate(model: BimModel, min_wall_len: float = 0.3, min_confidence: float = 0.5) -> list[str]:
    """Devuelve una lista de problemas (vacia = valido)."""
    issues: list[str] = []
    names = [s.name for s in model.storeys]
    if len(set(names)) != len(names):
        issues.append("Nombres de planta duplicados")
    known = set(names)
    for i, w in enumerate(model.walls):
        if w.storey not in known:
            issues.append(f"Muro {i}: planta '{w.storey}' inexistente")
        length = math.dist(w.start, w.end)
        if length < min_wall_len:
            issues.append(f"Muro {i}: longitud {length:.2f} m < {min_wall_len} m")
        if w.height <= 0 or w.thickness <= 0:
            issues.append(f"Muro {i}: altura/espesor no positivo")
        if w.confidence < min_confidence:
            issues.append(f"Muro {i}: confianza baja ({w.confidence:.2f}), revisar")
    for i, s in enumerate(model.slabs):
        if s.storey not in known:
            issues.append(f"Forjado {i}: planta '{s.storey}' inexistente")
        if len(s.outline) < 3:
            issues.append(f"Forjado {i}: contorno con menos de 3 vertices")
        if s.thickness <= 0:
            issues.append(f"Forjado {i}: espesor no positivo")
    return issues
