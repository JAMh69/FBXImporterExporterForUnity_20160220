"""CLI: all2bim las2model | validate | model2ifc"""
from __future__ import annotations

import argparse
import sys

from .model import BimModel


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="all2bim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("las2model", help="LAS -> modelo interno JSON")
    a.add_argument("las"); a.add_argument("out")
    a.add_argument("--voxel", type=float, default=0.05)
    v = sub.add_parser("validate", help="Validar modelo interno")
    v.add_argument("model")
    e = sub.add_parser("model2ifc", help="Modelo interno -> IFC4 (se valida antes)")
    e.add_argument("model"); e.add_argument("out")
    e.add_argument("--force", action="store_true", help="Exportar aunque haya avisos")
    args = ap.parse_args(argv)

    if args.cmd == "las2model":
        from .detect import load_las, points_to_model
        m = points_to_model(load_las(args.las, args.voxel))
        m.save(args.out)
        print(f"{len(m.storeys)} plantas, {len(m.walls)} muros, {len(m.slabs)} forjados -> {args.out}")
        return 0
    from .validate import validate
    m = BimModel.load(args.model)
    issues = validate(m)
    for i in issues:
        print("AVISO:", i)
    if args.cmd == "validate":
        return 1 if issues else 0
    if issues and not args.force:
        print("Exportacion cancelada (use --force para ignorar avisos).", file=sys.stderr)
        return 1
    from .ifc_export import export_ifc
    export_ifc(m, args.out)
    print("IFC escrito:", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
