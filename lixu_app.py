"""Punct de intrare pentru Lixu.exe (PyInstaller). Fără argumente pornește aplicația cu interfață."""
import sys

from lixu.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
