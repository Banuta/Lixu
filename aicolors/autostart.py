"""Pornire odată cu Windows: o intrare în HKCU\\...\\Run (doar pentru utilizatorul tău, fără admin)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "AI Colors"


def command(config_path: Optional[Path] = None) -> str:
    """Comanda de pornire, fără consolă: AIColors.exe sau pythonw -m aicolors."""
    cfg = f' --config "{Path(config_path).resolve()}"' if config_path else ""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" app --tray{cfg}'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else exe
    return f'"{runner}" -m aicolors app --tray{cfg}'


def is_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, NAME)
            return True
    except OSError:
        return False


def set_enabled(enabled: bool, config_path: Optional[Path] = None) -> bool:
    if sys.platform != "win32":
        raise RuntimeError("pornirea cu Windows e doar pe Windows")
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, command(config_path))
        else:
            try:
                winreg.DeleteValue(k, NAME)
            except FileNotFoundError:
                pass
    return is_enabled()
