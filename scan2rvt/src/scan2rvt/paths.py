"""Rutas de la aplicación en modo portátil.

Todo vive bajo una carpeta raíz (p. ej. ``E:\\000 APPS JAMh\\Scan2RVT``):

    Scan2RVT/
        app/        ejecutable empaquetado
        revit/      complemento de Revit
        config/     ajustes y plantilla .rte
        proyectos/  un subdirectorio por obra
        temp/
        logs/

La raíz se resuelve así:
1. Variable de entorno ``SCAN2RVT_HOME`` si existe.
2. Si la app está empaquetada (PyInstaller), la carpeta padre de ``app/``.
3. En desarrollo, ``<repo>/_local``.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

SUBDIRS = ("config", "proyectos", "temp", "logs", "revit")


def app_root() -> Path:
    env = os.environ.get("SCAN2RVT_HOME")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        return exe_dir.parent if exe_dir.name.lower() == "app" else exe_dir
    return Path(__file__).resolve().parents[2] / "_local"


def ensure_dirs(root: Path | None = None) -> Path:
    root = root or app_root()
    for name in SUBDIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def config_dir() -> Path:
    return app_root() / "config"


def projects_dir() -> Path:
    return app_root() / "proyectos"


def temp_dir() -> Path:
    return app_root() / "temp"


def logs_dir() -> Path:
    return app_root() / "logs"


def revit_dir() -> Path:
    return app_root() / "revit"


_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name: str) -> str:
    """Nombre válido como carpeta de Windows (conserva espacios y acentos)."""
    cleaned = _INVALID.sub("_", name).strip().rstrip(".")
    return cleaned or "Proyecto"


class ProjectPaths:
    """Carpetas de una obra dentro de ``proyectos/``."""

    def __init__(self, name: str, base: Path | None = None):
        self.name = name
        self.root = (base or projects_dir()) / safe_name(name)
        self.resultados = self.root / "resultados"
        self.informe = self.root / "informe"
        self.cache = self.root / "cache"

    def create(self) -> "ProjectPaths":
        for d in (self.resultados, self.informe, self.cache):
            d.mkdir(parents=True, exist_ok=True)
        return self
