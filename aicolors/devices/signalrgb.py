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
    """Cu SignalRGB Pro ("control": true, implicit): la pornire aplică singur efectul
    „AI Colors CS2” prin API-ul local și la ieșire pune înapoi efectul tău. Fără Pro: doar
    publică culorile, iar efectul îl alegi tu în SignalRGB."""

    kind = "signalrgb"
    min_interval = 0.03
    keepalive = 0.5

    def __init__(self, leds: int = 32, name: Optional[str] = None, control: bool = True,
                 api_port: int = 16038, api=None):
        super().__init__(name or "SignalRGB (efectul AI Colors CS2)", max(1, min(256, int(leds))))
        self.previous_effect: Optional[str] = None
        self.shutdown = False   # la oprirea PC-ului nu mai punem efectul vechi (rămâne negru)
        self.api = None
        self.api_status = "fără control (alege tu efectul în SignalRGB)"
        if control:
            from ..signalrgb_api import SignalRGBApi, SignalRGBError

            api = api or SignalRGBApi(port=api_port)
            try:
                prev_id, prev_name = api.current()
                ours = api.find()
                if ours is None:
                    install_effect()
                    self.api_status = ("efectul „AI Colors CS2” nu apare încă în SignalRGB: "
                                       "l-am pus în folderul de efecte, repornește SignalRGB")
                else:
                    if prev_id != ours:
                        self.previous_effect = prev_id
                        api.apply(ours)
                    self.api = api
                    self.api_status = f"control prin API Pro (înainte era „{prev_name}”)"
            except SignalRGBError as exc:
                self.api_status = str(exc)

    def send(self, colors: Sequence[RGB]) -> None:
        with _lock:
            _latest["colors"] = [tuple(c) for c in colors]
            _latest["at"] = time.time()

    def close(self) -> None:
        with _lock:
            _latest["colors"] = []
            _latest["at"] = 0.0
        if self.api is not None and self.previous_effect and not self.shutdown:
            try:
                self.api.apply(self.previous_effect)  # efectul tău din SignalRGB înapoi
            except Exception:
                pass


def from_config(entry: dict) -> Device:
    return SignalRGBBridge(entry.get("leds", 32), entry.get("name"), bool(entry.get("control", True)),
                           int(entry.get("api_port", 16038)))


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
