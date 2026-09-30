"""Punto de entrada.

Sin argumentos abre la ventana. También funciona por línea de comandos:

    Scan2RVT.exe procesar --nombre "Obra X" --escaner E:\\scans --dron E:\\dron\\vuelo.las
    Scan2RVT.exe procesar --demo --nombre Demo
    Scan2RVT.exe instalar-revit | desinstalar-revit
"""

from __future__ import annotations

import argparse
import sys


def _cli(argv: list[str]) -> int:
    from . import config, paths, pipeline, revit_bridge

    p = argparse.ArgumentParser(prog="Scan2RVT")
    sub = p.add_subparsers(dest="orden", required=True)
    pr = sub.add_parser("procesar", help="procesa nubes y exporta")
    pr.add_argument("--nombre", required=True)
    pr.add_argument("--escaner", nargs="*", default=[])
    pr.add_argument("--dron", nargs="*", default=[])
    pr.add_argument("--salidas", default="rvt,ifc,glb", help="lista separada por comas: " + ",".join(pipeline.SALIDAS))
    pr.add_argument("--plantilla", default="")
    pr.add_argument("--epsg", default="")
    pr.add_argument("--no-alineadas", action="store_true")
    pr.add_argument("--demo", action="store_true")
    sub.add_parser("instalar-revit")
    sub.add_parser("desinstalar-revit")
    a = p.parse_args(argv)

    paths.ensure_dirs()
    ajustes = config.load()
    if a.orden == "instalar-revit":
        print(revit_bridge.instalar_complemento(ajustes.revit_version))
        return 0
    if a.orden == "desinstalar-revit":
        print("desinstalado" if revit_bridge.desinstalar_complemento(ajustes.revit_version) else "no estaba instalado")
        return 0

    salidas = [s.strip() for s in a.salidas.split(",") if s.strip()]
    malas = [s for s in salidas if s not in pipeline.SALIDAS]
    if malas:
        p.error(f"salidas desconocidas: {malas}")
    t = pipeline.Trabajo(nombre=a.nombre, escaner=a.escaner, dron=a.dron, salidas=salidas,
                         plantilla_rte=a.plantilla, epsg=a.epsg or ajustes.epsg,
                         alineadas=not a.no_alineadas, demo=a.demo)
    r = pipeline.ejecutar(t, ajustes, progreso=lambda m, pct: print(f"{pct:4.0%}  {m}", flush=True))
    print("\nAvisos:")
    for x in r.avisos:
        print("  -", x)
    print("\nArchivos:")
    for x in r.archivos:
        print("  -", x)
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if argv:
        return _cli(argv)
    from .gui.ventana import lanzar

    return lanzar()


if __name__ == "__main__":
    sys.exit(main())
