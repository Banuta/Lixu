"""Punte spre SignalRGB: pentru dispozitivele pe care doar SignalRGB le controlează
(ex. memoriile Kingston FURY care merg doar cu pluginul SignalRGB).

AI Colors calculează culorile ca pentru o bandă de LED-uri ("leds" puncte, efectul ales),
iar efectul „AI Colors CS2” din SignalRGB (aicolors/signalrgb/AIColorsCS2.html) le citește
de la http://127.0.0.1:<ui_port>/api/signalrgb și le întinde de la stânga la dreapta pe
canvasul SignalRGB, deci pe toate dispozitivele din SignalRGB, după cum sunt așezate în Layout.
Nu cere SignalRGB Pro.

Linie în aicolors.json:
    {"type": "signalrgb", "effect": "ambient", "leds": 32}
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..protocol import RGB
from .base import Device

EFFECT_FILE = Path(__file__).resolve().parent.parent / "signalrgb" / "AIColorsCS2.html"

_lock = threading.Lock()
_latest: Dict = {"colors": [], "at": 0.0}


def latest() -> Dict:
    with _lock:
        colors = list(_latest["colors"])
        at = _latest["at"]
    return {"colors": ["#%02x%02x%02x" % tuple(int(v) for v in c) for c in colors],
            "age": round(time.time() - at, 2) if at else None}


class SignalRGBBridge(Device):
    kind = "signalrgb"
    min_interval = 0.03
    keepalive = 0.5

    def __init__(self, leds: int = 32, name: Optional[str] = None):
        super().__init__(name or "SignalRGB (efectul AI Colors CS2)", max(1, min(256, int(leds))))

    def send(self, colors: Sequence[RGB]) -> None:
        with _lock:
            _latest["colors"] = [tuple(c) for c in colors]
            _latest["at"] = time.time()

    def close(self) -> None:
        with _lock:
            _latest["colors"] = []
            _latest["at"] = 0.0


def from_config(entry: dict) -> Device:
    return SignalRGBBridge(entry.get("leds", 32), entry.get("name"))


def effects_dirs() -> List[Path]:
    """Folderele în care SignalRGB caută efecte personalizate."""
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    docs = [home / "Documents", home / "OneDrive" / "Documents", home / "OneDrive" / "Documente"]
    return [d / "WhirlwindFX" / "Effects" for d in docs]


def install_effect() -> Path:
    """Copiază efectul în primul folder WhirlwindFX existent (sau îl creează în Documents)."""
    dirs = effects_dirs()
    target_dir = next((d for d in dirs if d.parent.is_dir()), dirs[0])
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / EFFECT_FILE.name
    shutil.copyfile(EFFECT_FILE, target)
    return target
