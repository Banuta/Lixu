"""Punte spre SignalRGB: pentru dispozitivele pe care doar SignalRGB le controlează
(ex. memoriile Kingston FURY care merg doar cu pluginul SignalRGB).

AI Colors calculează culorile ca pentru o bandă de LED-uri ("leds" puncte, efectul ales) și
le trimite la SignalRGB prin calea oficială pentru aplicații:
    POST http://localhost:16034/canvas/event?sender=AIColors&event=c|rrggbb|rrggbb|...
Efectul „AI Colors CS2” (aicolors/signalrgb/AIColorsCS2.html) le primește în
onCanvasApiEvent și le întinde de la stânga la dreapta pe canvasul SignalRGB, deci pe toate
dispozitivele din SignalRGB, după cum sunt așezate în Layout. (SignalRGB nu lasă efectul să
citească singur de la AI Colors – XHR blocat – de aceea împingem noi datele.)
Trimiterea nu cere SignalRGB Pro; doar aplicarea automată a efectului cere Pro.

Linie în aicolors.json:
    {"type": "signalrgb", "effect": "ambient", "leds": 32}
"""

from __future__ import annotations

import http.client
import os
import shutil
import urllib.parse
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..protocol import RGB
from .base import Device

EFFECT_FILE = Path(__file__).resolve().parent.parent / "signalrgb" / "AIColorsCS2.html"

EVENT_PORT = 16034
SENDER = "AIColors"

_lock = threading.Lock()
_latest: Dict = {"colors": [], "at": 0.0}


def event_text(colors: Sequence[RGB]) -> str:
    """c|rrggbb|... ; dacă toate culorile sunt la fel, una singură (mesaj scurt)."""
    hexes = ["%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in c) for c in colors]
    if hexes and all(h == hexes[0] for h in hexes):
        hexes = hexes[:1]
    return "c|" + "|".join(hexes)


def post_event(event: str, host: str = "127.0.0.1", port: int = EVENT_PORT,
               timeout: float = 0.5) -> int:
    """Trimite un eveniment către efectul SignalRGB activ; întoarce codul HTTP."""
    query = urllib.parse.urlencode({"sender": SENDER, "event": event})
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("POST", "/canvas/event?" + query, body=b"",
                     headers={"Content-Length": "0"})
        resp = conn.getresponse()
        resp.read()
        return resp.status
    finally:
        conn.close()


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
                 api_port: int = 16038, api=None, event_port: int = EVENT_PORT):
        super().__init__(name or "SignalRGB (efectul AI Colors CS2)", max(1, min(256, int(leds))))
        self.previous_effect: Optional[str] = None
        self.shutdown = False   # la oprirea PC-ului nu mai punem efectul vechi (rămâne negru)
        self.event_port = event_port
        self.event_status = "încă nimic trimis"
        self._event_fail = 0
        self.api = None
        self.api_status = "fără control (alege tu efectul în SignalRGB)"
        try:
            update_installed_effect()   # o versiune veche a efectului e înlocuită cu cea nouă
        except OSError:
            pass
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
        self._push(event_text(colors))

    def _push(self, event: str) -> None:
        # După erori la rând (SignalRGB închis) încercăm mai rar, ca să nu încetinim nimic.
        if self._event_fail >= 3 and self._event_fail % 10:
            self._event_fail += 1
            return
        try:
            code = post_event(event, port=self.event_port)
        except OSError as exc:
            self._event_fail += 1
            self.event_status = f"SignalRGB nu primește evenimente pe portul {self.event_port}: {exc}"
            return
        if 200 <= code < 300:
            self._event_fail = 0
            self.event_status = "trimite culorile la SignalRGB"
        else:
            self._event_fail += 1
            self.event_status = f"SignalRGB a răspuns {code} la evenimente"

    @property
    def status_text(self) -> str:
        return f"{self.api_status}; {self.event_status}"

    def close(self) -> None:
        with _lock:
            _latest["colors"] = []
            _latest["at"] = 0.0
        try:
            post_event("c|000000", port=self.event_port, timeout=0.3)   # negru la închidere
        except OSError:
            pass
        if self.api is not None and self.previous_effect and not self.shutdown:
            try:
                self.api.apply(self.previous_effect)  # efectul tău din SignalRGB înapoi
            except Exception:
                pass


def from_config(entry: dict) -> Device:
    return SignalRGBBridge(entry.get("leds", 32), entry.get("name"), bool(entry.get("control", True)),
                           int(entry.get("api_port", 16038)),
                           event_port=int(entry.get("event_port", EVENT_PORT)))


def effects_dirs() -> List[Path]:
    """Folderele în care SignalRGB caută efecte personalizate."""
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    docs = [home / "Documents", home / "OneDrive" / "Documents", home / "OneDrive" / "Documente"]
    return [d / "WhirlwindFX" / "Effects" for d in docs]


def update_installed_effect() -> List[Path]:
    """Rescrie efectul deja instalat dacă diferă de cel din aplicație (după o actualizare)."""
    new = EFFECT_FILE.read_bytes()
    updated = []
    for d in effects_dirs():
        target = d / EFFECT_FILE.name
        if target.is_file() and target.read_bytes() != new:
            target.write_bytes(new)
            updated.append(target)
    return updated


def install_effect() -> Path:
    """Copiază efectul în primul folder WhirlwindFX existent (sau îl creează în Documents)."""
    dirs = effects_dirs()
    target_dir = next((d for d in dirs if d.parent.is_dir()), dirs[0])
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / EFFECT_FILE.name
    shutil.copyfile(EFFECT_FILE, target)
    return target
