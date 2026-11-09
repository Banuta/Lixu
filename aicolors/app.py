"""Aplicația completă: server GSI + motor de lumini + mouse/căști + interfață web locală.

Interfața e o pagină (aicolors/ui/index.html) servită doar pe 127.0.0.1. Se deschide
într-o fereastră de tip aplicație (Edge/Chrome cu --app). Când o închizi, aicolors
rulează mai departe în fundal fără niciun cost.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

from . import __version__, config as configmod, cs2cfg, effects, layout
from .devices import FACTORIES
from .engine import Engine
from .gsi import GsiServer, StateStore

log = logging.getLogger(__name__)

UI_DIR = Path(__file__).resolve().parent / "ui"

SIMULATIONS: Dict[str, Dict[str, Any]] = {
    "menu": {},
    "ct": {"map": {"phase": "live"}, "round": {"phase": "live"},
           "player": {"team": "CT", "activity": "playing",
                      "state": {"health": 100, "armor": 100, "helmet": True, "round_kills": 1},
                      "weapons": {"w": {"name": "weapon_m4a1", "state": "active", "ammo_clip": 14, "ammo_clip_max": 20}}}},
    "t_low": {"map": {"phase": "live"}, "round": {"phase": "live"},
              "player": {"team": "T", "activity": "playing", "state": {"health": 17, "armor": 30, "round_kills": 3,
                                                                       "round_killhs": 2},
                         "weapons": {"w": {"name": "weapon_ak47", "state": "active", "ammo_clip": 0, "ammo_clip_max": 30}}}},
    "bomb": {"map": {"phase": "live"}, "round": {"phase": "live", "bomb": "planted"},
             "player": {"team": "CT", "activity": "playing", "state": {"health": 64, "armor": 80}}},
    "flash": {"map": {"phase": "live"}, "round": {"phase": "live"},
              "player": {"team": "CT", "activity": "playing", "state": {"health": 90, "armor": 100, "flashed": 220}}},
    "fire": {"map": {"phase": "live"}, "round": {"phase": "live"},
             "player": {"team": "T", "activity": "playing", "state": {"health": 55, "armor": 0, "burning": 255}}},
    "dead": {"map": {"phase": "live"}, "round": {"phase": "live"},
             "player": {"team": "T", "activity": "playing", "state": {"health": 0}}},
    "win": {"map": {"phase": "live"}, "round": {"phase": "over", "win_team": "CT", "bomb": "defused"},
            "player": {"team": "CT", "activity": "playing", "state": {"health": 40, "armor": 20}}},
}

DEVICE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "zenkabeat": {"type": "zenkabeat", "effect": "keyboard"},
    "wled": {"type": "wled", "host": "192.168.1.50", "effect": "health"},
    "govee": {"type": "govee", "host": "192.168.1.51", "effect": "ambient"},
    "logitech": {"type": "logitech", "target": "mouse", "effect": "ambient"},
    "openrgb": {"type": "openrgb", "device_type": "motherboard", "effect": "ambient"},
    "tuya": {"type": "tuya", "id": "", "effect": "ambient"},
}


def _state_dict(store: StateStore) -> Dict[str, Any]:
    if not store.updates:
        return {"connected": False}
    st = store.get()
    raw = st.raw or {}
    w = st.active_weapon
    return {
        "connected": time.time() - st.received_at < 35,
        "age": round(time.time() - st.received_at, 1),
        "in_game": st.in_game, "team": st.team, "health": st.health, "armor": st.armor,
        "helmet": st.helmet, "flashed": st.flashed, "burning": st.burning, "money": st.money,
        "round_kills": st.round_kills, "round_killhs": st.round_killhs,
        "round_phase": st.round_phase, "bomb": st.bomb, "map_phase": st.map_phase,
        "map": (raw.get("map") or {}).get("name", ""),
        "score_ct": ((raw.get("map") or {}).get("team_ct") or {}).get("score"),
        "score_t": ((raw.get("map") or {}).get("team_t") or {}).get("score"),
        "weapon": w.name.replace("weapon_", "") if w else "",
        "ammo": w.ammo_clip if w else None, "ammo_max": w.ammo_clip_max if w else None,
    }


class App:
    def __init__(self, cfg: configmod.Config, dry_run: bool = False, preview: bool = False):
        self.cfg = cfg
        self.dry_run = dry_run
        effects.apply_palette(cfg.colors)
        self.store = StateStore()
        self.engine = Engine(cfg.active_devices, self.store, fps=cfg.fps, idle_fps=cfg.idle_fps,
                             brightness=cfg.brightness, dry_run=dry_run, preview=preview)
        self.gsi = GsiServer(self.store, host=cfg.host, port=cfg.port, token=cfg.token)
        self.peripherals = None
        if cfg.peripherals.get("enabled", True) and not dry_run:
            from .peripherals.logitech import PeripheralMonitor

            self.peripherals = PeripheralMonitor(cfg.peripherals.get("poll_seconds", 60), cfg.peripherals)
        self.ui: Optional[ThreadingHTTPServer] = None
        self._engine_thread: Optional[threading.Thread] = None
        self.restart_needed = False

    # ------------------------------------------------------------ ciclu de viață

    def start(self, ui: bool = True) -> None:
        if self.cfg.openrgb.get("autostart") and not self.dry_run:
            threading.Thread(target=self._autostart_openrgb, name="openrgb", daemon=True).start()
        self.gsi.start()
        log.info("Server GSI pe http://%s:%d/", self.cfg.host, self.gsi.port)
        if self.peripherals:
            self.peripherals.start()
        if ui:
            self.ui = ThreadingHTTPServer(("127.0.0.1", self.cfg.ui_port), make_ui_handler(self))
            self.ui.daemon_threads = True
            threading.Thread(target=self.ui.serve_forever, name="ui", daemon=True).start()
            log.info("Interfață: %s", self.ui_url)
        self._engine_thread = threading.Thread(target=self.engine.run, name="engine", daemon=True)
        self._engine_thread.start()

    def _autostart_openrgb(self) -> None:
        from . import openrgb_setup

        try:
            if not openrgb_setup.server_running() and openrgb_setup.find_exe():
                openrgb_setup.start()
        except Exception as exc:
            log.warning("OpenRGB: %s", exc)

    def openrgb(self, action: str) -> Dict[str, Any]:
        from . import openrgb_setup

        if action == "install":
            openrgb_setup.install()
        elif action == "start":
            openrgb_setup.start()
        return openrgb_setup.status()

    def tuya_keys(self, data: Dict[str, Any]) -> Dict[str, Any]:
        from .devices import tuya

        ids = [d.get("id") for d in self.cfg.devices if d.get("type") == "tuya" and d.get("id")]
        ids += [i for i in (data.get("device_ids") or []) if i]
        path = tuya.fetch_cloud_keys(data.get("region", "eu"), data["api_key"].strip(),
                                     data["api_secret"].strip(), ids)
        found = tuya.wizard_devices(str(path))
        self.engine.reconfigure(self.cfg.active_devices)
        with self.engine.lock:  # becurile deconectate încearcă imediat cu cheile noi
            for o in self.engine.outputs:
                if o.device is None:
                    o.next_retry = 0.0
        return {"ok": True, "path": str(path), "devices": [{"id": k, "name": v.get("name")} for k, v in found.items()]}

    @property
    def ui_url(self) -> str:
        port = self.ui.server_address[1] if self.ui else self.cfg.ui_port
        return f"http://127.0.0.1:{port}/"

    def wait(self) -> None:
        while self._engine_thread and self._engine_thread.is_alive():
            self._engine_thread.join(0.5)

    def stop(self) -> None:
        self.engine.stop()
        if self._engine_thread:
            self._engine_thread.join(3)
        self.gsi.stop()
        if self.peripherals:
            self.peripherals.stop()
        if self.ui:
            self.ui.shutdown()
            self.ui.server_close()

    # ------------------------------------------------------------ API

    def api_state(self) -> Dict[str, Any]:
        return {
            "game": _state_dict(self.store),
            "devices": self.engine.snapshot(),
            "peripherals": self.peripherals.snapshot() if self.peripherals else
            {"note": "dezactivat" if self.dry_run else "Mouse/căști Logitech: dezactivat în setări", "devices": []},
            "restart_needed": self.restart_needed,
        }

    def api_config(self) -> Dict[str, Any]:
        d = self.cfg.to_dict()
        d["colors"] = effects.palette()
        d["path"] = str(self.cfg.path or "")
        return d

    def api_meta(self) -> Dict[str, Any]:
        return {
            "version": __version__,
            "effects": ["keyboard"] + list(effects.STRIP_EFFECTS),
            "types": list(FACTORIES),
            "templates": DEVICE_TEMPLATES,
            "simulations": list(SIMULATIONS),
            "default_palette": DEFAULT_PALETTE,
            "keys": [{"name": k.name, "led": k.led} for k in layout.KEYS],
            "scenes": effects.SCENES,
            "dry_run": self.dry_run,
        }

    def save_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        data = {k: v for k, v in data.items() if k != "path"}
        new = configmod.from_dict(data, self.cfg.path)
        effects.apply_palette(new.colors)
        if (new.host, new.port, new.token, new.ui_port) != (self.cfg.host, self.cfg.port, self.cfg.token,
                                                            self.cfg.ui_port):
            self.restart_needed = True
        self.engine.reconfigure(new.active_devices, new.fps, new.idle_fps, new.brightness)
        if self.peripherals:
            self.peripherals.settings = new.peripherals
        path = self.cfg.path or (Path.cwd() / "aicolors.json")
        new.path = configmod.save(new, path)
        self.cfg = new
        log.info("Config salvat: %s", path)
        return {"ok": True, "path": str(path), "restart_needed": self.restart_needed}

    def scan(self, subnet: Optional[str] = None) -> Dict[str, Any]:
        from .discovery.scan import scan

        results = scan(timeout=2.5, subnet=subnet or None)
        return {"groups": [
            {"name": name, "error": err, "found": [
                {"kind": f.kind, "name": f.name, "address": f.address, "details": f.details,
                 "controllable": f.controllable, "config": f.config, "notes": f.notes} for f in found]}
            for name, found, err in results]}

    def simulate(self, preset: str) -> Dict[str, Any]:
        if preset not in SIMULATIONS:
            raise KeyError(preset)
        self.store.update(SIMULATIONS[preset])
        return {"ok": True}

    def install_cfg(self, cs2_dir: Optional[str] = None) -> Dict[str, Any]:
        dirs = [Path(cs2_dir)] if cs2_dir else cs2cfg.find_cs2_cfg_dirs()
        if not dirs:
            return {"ok": False, "error": "Nu am găsit CS2. Scrie calea către ...\\game\\csgo\\cfg.",
                    "content": cs2cfg.render_cfg(self.cfg.port, self.cfg.token)}
        written = [str(cs2cfg.install_cfg(d, self.cfg.port, self.cfg.token)) for d in dirs]
        return {"ok": True, "written": written}

    def mouse(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.peripherals:
            raise RuntimeError("monitorul pentru mouse/căști e dezactivat")
        key = data["id"]
        if "host_mode" in data:
            self.peripherals.set_host_mode(key, bool(data["host_mode"]))
        if data.get("dpi"):
            self.peripherals.set_dpi(key, int(data["dpi"]))
        if data.get("rate"):
            self.peripherals.set_rate(key, int(data["rate"]))
        if data.get("remember"):
            mouse = dict(self.cfg.peripherals.get("mouse") or {})
            for src, dst in (("dpi", "dpi"), ("rate", "polling_rate"), ("host_mode", "host_mode")):
                if data.get(src) is not None:
                    mouse[dst] = data[src]
            cfg = self.cfg.to_dict()
            cfg["peripherals"] = dict(self.cfg.peripherals, mouse=mouse)
            self.save_config(cfg)
        return {"ok": True, "peripherals": self.peripherals.snapshot()}


DEFAULT_PALETTE = effects.palette()


def make_ui_handler(app: App):
    index = UI_DIR / "index.html"

    class Handler(BaseHTTPRequestHandler):
        server_version = "AIColorsUI/1.0"

        def _json(self, obj: Any, code: int = 200) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                body = index.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/state":
                self._json(app.api_state())
            elif path == "/api/config":
                self._json(app.api_config())
            elif path == "/api/meta":
                self._json(app.api_meta())
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            # antet obligatoriu: un site străin nu-l poate trimite fără CORS, deci nu poate schimba setări
            if self.headers.get("X-AIColors") != "1":
                self._json({"error": "forbidden"}, 403)
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
            except ValueError:
                self._json({"error": "JSON invalid"}, 400)
                return
            routes = {
                "/api/config": lambda: app.save_config(data),
                "/api/scan": lambda: app.scan(data.get("subnet")),
                "/api/identify": lambda: (app.engine.identify(int(data["index"])), {"ok": True})[1],
                "/api/simulate": lambda: app.simulate(data.get("preset", "")),
                "/api/install-cfg": lambda: app.install_cfg(data.get("cs2_dir")),
                "/api/mouse": lambda: app.mouse(data),
                "/api/openrgb": lambda: app.openrgb(data.get("action", "status")),
                "/api/tuya/keys": lambda: app.tuya_keys(data),
                "/api/kbmode": lambda: app.engine.keyboard_preview(data.get("value")),
                "/api/quit": lambda: (threading.Timer(0.3, app.engine.stop).start(), {"ok": True})[1],
                "/api/peripherals/refresh": lambda: (app.peripherals and app.peripherals.refresh(), {"ok": True})[1],
            }
            route = routes.get(self.path.split("?")[0])
            if route is None:
                self._json({"error": "not found"}, 404)
                return
            try:
                self._json(route())
            except Exception as exc:
                log.warning("API %s: %s", self.path, exc)
                self._json({"error": str(exc)}, 400)

        def log_message(self, fmt: str, *args: Any) -> None:
            log.debug("ui: " + fmt, *args)

    return Handler


def open_window(url: str) -> None:
    """Deschide interfața ca fereastră de aplicație (Edge/Chrome --app), altfel în browser."""
    candidates = []
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("LOCALAPPDATA", "")):
            candidates += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                           os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    candidates += [shutil.which(n) for n in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser")]
    for exe in candidates:
        if exe and os.path.isfile(exe):
            try:
                subprocess.Popen([exe, f"--app={url}", "--window-size=1180,820"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                continue
    webbrowser.open(url)
