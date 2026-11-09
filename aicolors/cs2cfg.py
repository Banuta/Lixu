"""Găsește instalarea CS2 și scrie fișierul gamestate_integration_aicolors.cfg."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Iterable, List, Optional

CFG_NAME = "gamestate_integration_aicolors.cfg"
CS2_SUBDIR = Path("steamapps/common/Counter-Strike Global Offensive/game/csgo/cfg")


def render_cfg(port: int = 3000, token: Optional[str] = None, host: str = "127.0.0.1") -> str:
    auth = f'\n  "auth"\n  {{\n    "token" "{token}"\n  }}' if token else ""
    return f'''"AI Colors"
{{
  "uri"       "http://{host}:{port}/"
  "timeout"   "1.1"
  "buffer"    "0.0"
  "throttle"  "0.05"
  "heartbeat" "10.0"{auth}
  "data"
  {{
    "provider"            "1"
    "map"                 "1"
    "round"               "1"
    "player_id"           "1"
    "player_state"        "1"
    "player_weapons"      "1"
    "player_match_stats"  "1"
  }}
}}
'''


def _steam_roots() -> List[Path]:
    roots: List[Path] = []
    if sys.platform == "win32":
        try:
            import winreg

            for hive, key, value in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
            ):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        roots.append(Path(winreg.QueryValueEx(k, value)[0]))
                except OSError:
                    pass
        except ImportError:  # pragma: no cover
            pass
        roots += [Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")]
    else:
        home = Path.home()
        roots += [home / ".steam/steam", home / ".local/share/Steam"]
    return roots


def library_folders(steam_root: Path) -> List[Path]:
    """Toate bibliotecile Steam, din steamapps/libraryfolders.vdf."""
    folders = [steam_root]
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return folders
    for m in re.finditer(r'"path"\s+"([^"]+)"', text):
        folders.append(Path(m.group(1).replace("\\\\", "\\")))
    return folders


def find_cs2_cfg_dirs(roots: Optional[Iterable[Path]] = None) -> List[Path]:
    seen = set()
    found: List[Path] = []
    for root in roots if roots is not None else _steam_roots():
        for lib in library_folders(Path(root)):
            cfg = lib / CS2_SUBDIR
            key = os.path.normcase(str(cfg))
            if key in seen:
                continue
            seen.add(key)
            if cfg.is_dir():
                found.append(cfg)
    return found


def install_cfg(cfg_dir: Path, port: int = 3000, token: Optional[str] = None) -> Path:
    cfg_dir = Path(cfg_dir)
    if not cfg_dir.is_dir():
        raise FileNotFoundError(f"directorul nu există: {cfg_dir}")
    target = cfg_dir / CFG_NAME
    target.write_text(render_cfg(port=port, token=token), encoding="utf-8")
    return target
