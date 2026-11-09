"""Punct de intrare pentru AIColors.exe (PyInstaller). Fără argumente pornește aplicația cu interfață."""
import sys

from aicolors.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
