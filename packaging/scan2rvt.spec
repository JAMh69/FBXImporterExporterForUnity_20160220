# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: pyinstaller packaging/scan2rvt.spec  →  dist/Scan2RVT/Scan2RVT.exe
import os

from PyInstaller.utils.hooks import collect_all

RAIZ = os.path.abspath(os.path.join(SPECPATH, ".."))

datas, binaries, hiddenimports = [], [], []
for paquete in ("ifcopenshell", "laspy", "lazrs", "pye57", "trimesh", "mapbox_earcut", "shapely"):
    d, b, h = collect_all(paquete)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(SPECPATH, "lanzador.py")],
    pathex=[os.path.join(RAIZ, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["scan2rvt.gui.ventana"],
    excludes=["tkinter", "matplotlib", "open3d", "IPython", "pytest", "PyQt5", "PyQt6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Scan2RVT",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Scan2RVT")
