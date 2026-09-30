"""Parámetros de procesamiento. Se guardan en ``config/ajustes.json``."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import paths


@dataclass
class TerrainSettings:
    celda_m: float = 1.0            # celda de la rejilla para detectar suelo
    ventana_max_m: float = 20.0      # ventana máxima del filtro morfológico (≈ tamaño del mayor edificio)
    pendiente: float = 0.3           # pendiente máxima del terreno (m/m)
    tolerancia_m: float = 0.15       # distancia máxima de un punto al terreno para ser "suelo"
    malla_m: float = 1.0             # paso de la malla del modelo digital del terreno
    max_puntos_revit: int = 10000    # puntos máximos enviados a Toposolid


@dataclass
class LevelSettings:
    voxel_m: float = 0.05           # submuestreo para el análisis
    bin_m: float = 0.02             # resolución del histograma de alturas
    celda_area_m: float = 0.25      # celda para medir la superficie horizontal
    celda_contorno_m: float = 0.02  # resolución del contorno de forjados (= submuestreo)
    area_min_m2: float = 4.0        # superficie mínima de un suelo/techo
    area_rel_min: float = 0.25      # superficie mínima relativa a la mayor
    altura_libre_min_m: float = 2.0 # altura mínima suelo-techo de una planta
    forjado_min_m: float = 0.10     # espesor mínimo de forjado
    forjado_max_m: float = 0.80     # espesor máximo de forjado


@dataclass
class WallSettings:
    voxel_m: float = 0.05             # submuestreo para el análisis de superficies verticales
    tol_m: float = 0.04               # distancia máxima de un punto a la línea del muro
    espesor_defecto_m: float = 0.20   # el escáner sólo ve una cara: el espesor es un supuesto
    longitud_min_m: float = 0.50
    hueco_max_m: float = 1.00         # separación máxima entre puntos de un mismo muro (puertas anchas lo parten)
    margen_z_m: float = 0.10          # se ignora la franja junto a suelo y techo
    cobertura_z_min: float = 0.5      # el muro debe cubrir al menos esta fracción de la altura libre
    puntos_min: int = 150
    iteraciones: int = 600
    muestra_max: int = 30000
    max_por_nivel: int = 60


@dataclass
class Settings:
    voxel_m: float = 0.02           # submuestreo general (la tolerancia del proyecto es 2 cm)
    quitar_ruido: bool = True
    extension_escaner_aviso_m: float = 300.0   # avisa si la nube de escáner es mayor (¿solar o dron?)
    max_puntos: int = 40_000_000    # por encima, se sube el vóxel (el análisis usa 5 cm; más puntos no aportan)
    terreno: TerrainSettings = field(default_factory=TerrainSettings)
    niveles: LevelSettings = field(default_factory=LevelSettings)
    muros: WallSettings = field(default_factory=WallSettings)
    revit_exe: str = r"C:\Program Files\Autodesk\Revit 2026\Revit.exe"
    revit_version: str = "2026"
    plantilla_rte: str = ""
    epsg: str = ""                  # p. ej. "25830" (ETRS89 / UTM 30N)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        s = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            current = getattr(s, f.name)
            if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
                known = {k: v for k, v in value.items() if k in current.__dataclass_fields__}
                value = type(current)(**known)
            setattr(s, f.name, value)
        return s

    def to_dict(self) -> dict:
        return asdict(self)


def settings_file() -> Path:
    return paths.config_dir() / "ajustes.json"


def load() -> Settings:
    f = settings_file()
    if f.exists():
        try:
            return Settings.from_dict(json.loads(f.read_text(encoding="utf-8")))
        except (ValueError, TypeError):
            pass
    return Settings()


def save(settings: Settings) -> None:
    f = settings_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(settings.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
