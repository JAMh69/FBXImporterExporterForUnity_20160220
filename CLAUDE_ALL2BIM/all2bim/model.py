"""Modelo 3D interno: formato intermedio editable y validable antes de exportar."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Storey:
    name: str
    elevation: float  # m


@dataclass
class Slab:
    storey: str
    outline: list[tuple[float, float]]  # polilinea cerrada XY, m
    thickness: float


@dataclass
class Wall:
    storey: str
    start: tuple[float, float]
    end: tuple[float, float]
    height: float
    thickness: float
    confidence: float = 1.0  # 0..1, para revision manual


@dataclass
class BimModel:
    units: str = "m"
    storeys: list[Storey] = field(default_factory=list)
    slabs: list[Slab] = field(default_factory=list)
    walls: list[Wall] = field(default_factory=list)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "BimModel":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            units=d.get("units", "m"),
            storeys=[Storey(**s) for s in d["storeys"]],
            slabs=[Slab(s["storey"], [tuple(p) for p in s["outline"]], s["thickness"]) for s in d["slabs"]],
            walls=[Wall(w["storey"], tuple(w["start"]), tuple(w["end"]), w["height"],
                        w["thickness"], w.get("confidence", 1.0)) for w in d["walls"]],
        )
