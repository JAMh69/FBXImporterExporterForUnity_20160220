"""Modelo propuesto: lo que se ha detectado y se enviará a Revit y a los exportadores.

Es el formato de intercambio con el complemento de Revit (``modelo.json``).
Unidades: metros. Coordenadas **locales**: ``local = absoluta - offset``.
Si cambias este formato, sube ``VERSION`` y actualiza ``revit/Scan2Rvt.Revit/Modelo.cs``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

VERSION = 1


@dataclass
class Nivel:
    id: str
    nombre: str
    cota: float                  # cota local (m)


@dataclass
class Forjado:
    id: str
    nivel_id: str                # nivel al que pertenece su cara superior
    cota_superior: float         # cota local de la cara superior (m)
    espesor: float               # m
    contorno: list[list[float]]  # polígono exterior [[x, y], ...] local, sin repetir el primer punto
    huecos: list[list[list[float]]] = field(default_factory=list)
    area_m2: float = 0.0
    espesor_medido: bool = True  # False si no se vieron las dos caras y se usa un valor por defecto


@dataclass
class Terreno:
    puntos: list[list[float]]    # [[x, y, z], ...] local; para Toposolid
    vertices: list[list[float]] = field(default_factory=list)  # malla para exportar
    caras: list[list[int]] = field(default_factory=list)
    paso_m: float = 1.0


@dataclass
class Modelo:
    offset: list[float]
    epsg: str = ""
    niveles: list[Nivel] = field(default_factory=list)
    forjados: list[Forjado] = field(default_factory=list)
    terreno: Terreno | None = None
    avisos: list[str] = field(default_factory=list)
    version: int = VERSION
    unidades: str = "m"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Modelo":
        return cls(
            offset=list(d["offset"]),
            epsg=d.get("epsg", ""),
            niveles=[Nivel(**n) for n in d.get("niveles", [])],
            forjados=[Forjado(**f) for f in d.get("forjados", [])],
            terreno=Terreno(**d["terreno"]) if d.get("terreno") else None,
            avisos=list(d.get("avisos", [])),
            version=d.get("version", VERSION),
            unidades=d.get("unidades", "m"),
        )

    def save(self, ruta: Path) -> Path:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(self.to_dict(), ensure_ascii=False), encoding="utf-8")
        return ruta

    @classmethod
    def load(cls, ruta: Path) -> "Modelo":
        return cls.from_dict(json.loads(Path(ruta).read_text(encoding="utf-8")))
