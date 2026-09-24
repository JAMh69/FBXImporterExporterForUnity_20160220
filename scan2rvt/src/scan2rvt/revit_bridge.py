"""Generación del .rvt con el Revit 2026 instalado en el PC.

Revit no tiene modo "sin ventana" en local, así que se hace así:
1. Un manifiesto ``Scan2RVT.addin`` (1 KB) en ``%AppData%\\Autodesk\\Revit\\Addins\\2026``
   apunta al complemento, que está en ``<raíz>\\revit\\``. Revit sólo busca
   complementos en esa carpeta; todo lo demás queda en la carpeta de la app.
2. Se abre Revit con la variable ``SCAN2RVT_JOB`` apuntando a un encargo.
   El complemento sólo actúa si esa variable existe: con Revit abierto a mano no hace nada.
3. El complemento crea el proyecto, niveles, suelos y terreno, guarda el .rvt,
   escribe un archivo de estado y cierra Revit.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Callable

from . import paths
from .config import Settings

DLL = "Scan2Rvt.Revit.dll"
CLASE = "Scan2Rvt.Revit.App"
ADDIN_ID = "6F0C2E4B-8B1D-4C3A-9E57-3C2B1A5D7E91"
TIEMPO_MAX_S = 30 * 60


class RevitNoDisponible(RuntimeError):
    pass


def carpeta_addins(version: str) -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(appdata) / "Autodesk" / "Revit" / "Addins" / version


def manifiesto(dll: Path) -> str:
    from xml.sax.saxutils import escape

    return f"""<?xml version="1.0" encoding="utf-8"?>
<RevitAddIns>
  <AddIn Type="Application">
    <Name>Scan2RVT</Name>
    <Assembly>{escape(str(dll))}</Assembly>
    <AddInId>{ADDIN_ID}</AddInId>
    <FullClassName>{CLASE}</FullClassName>
    <VendorId>JAMH</VendorId>
    <VendorDescription>Scan2RVT</VendorDescription>
  </AddIn>
</RevitAddIns>
"""


def instalar_complemento(version: str = "2026") -> Path:
    dll = paths.revit_dir() / DLL
    if not dll.exists():
        raise RevitNoDisponible(f"No se encuentra el complemento {dll}.")
    destino = carpeta_addins(version)
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / "Scan2RVT.addin"
    ruta.write_text(manifiesto(dll), encoding="utf-8")
    return ruta


def desinstalar_complemento(version: str = "2026") -> bool:
    ruta = carpeta_addins(version) / "Scan2RVT.addin"
    if ruta.exists():
        ruta.unlink()
        return True
    return False


def generar_rvt(modelo_json: Path, salida: Path, ajustes: Settings, plantilla: str, pp: paths.ProjectPaths,
                progreso: Callable[[str], None] | None = None) -> Path:
    log = progreso or (lambda _m: None)
    if os.name != "nt":
        raise RevitNoDisponible("sólo se puede generar en Windows con Revit instalado.")
    exe = Path(ajustes.revit_exe)
    if not exe.exists():
        raise RevitNoDisponible(f"no se encuentra Revit en «{exe}». Indica la ruta en Ajustes.")
    if plantilla and not Path(plantilla).exists():
        raise RevitNoDisponible(f"no se encuentra la plantilla «{plantilla}».")
    instalar_complemento(ajustes.revit_version)

    estado = pp.cache / "revit_estado.json"
    registro = pp.cache / "revit_registro.txt"
    for f in (estado, salida):
        if f.exists():
            f.unlink()
    encargo = pp.cache / "revit_encargo.json"
    encargo.write_text(json.dumps({
        "modelo": str(modelo_json),
        "salida": str(salida),
        "plantilla": plantilla or "",
        "estado": str(estado),
        "registro": str(registro),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    env = dict(os.environ, SCAN2RVT_JOB=str(encargo))
    log("Abriendo Revit (puede tardar un par de minutos)…")
    proc = subprocess.Popen([str(exe)], env=env)
    t0 = time.time()
    try:
        while not estado.exists():
            if proc.poll() is not None:
                raise RevitNoDisponible(f"Revit se cerró sin terminar. Revisa {registro}.")
            if time.time() - t0 > TIEMPO_MAX_S:
                raise RevitNoDisponible("Revit no terminó en 30 minutos.")
            time.sleep(2)
        time.sleep(1)
        res = json.loads(estado.read_text(encoding="utf-8"))
    finally:
        # El complemento cierra Revit al acabar; si no lo consigue, se cierra aquí.
        try:
            proc.wait(timeout=90)
        except subprocess.TimeoutExpired:
            proc.terminate()
    if res.get("estado") != "ok":
        raise RevitNoDisponible(res.get("mensaje", "error desconocido en Revit"))
    log("Archivo .rvt guardado.")
    return salida
