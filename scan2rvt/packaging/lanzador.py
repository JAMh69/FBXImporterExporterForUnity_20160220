"""Punto de entrada para PyInstaller (necesita un script, no un módulo con imports relativos)."""

import sys

from scan2rvt.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
