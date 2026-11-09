"""Serverul HTTP pentru Counter-Strike 2 Game State Integration.

CS2 trimite POST-uri JSON către URI-ul din gamestate_integration_*.cfg.
Păstrăm ultima stare primită, plus câteva momente de timp (când a fost
plantată bomba, când s-a terminat runda) de care au nevoie efectele.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional

log = logging.getLogger(__name__)


def _get(data: Dict[str, Any], *path: str, default: Any = None) -> Any:
    cur: Any = data
    for part in path:
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class Weapon:
    name: str = ""
    type: str = ""
    ammo_clip: int = -1
    ammo_clip_max: int = -1
    ammo_reserve: int = -1
    state: str = ""


@dataclass
class GameState:
    received_at: float = 0.0
    activity: str = "menu"          # playing / menu / textinput
    map_phase: str = ""             # warmup / live / intermission / gameover
    round_phase: str = ""           # freezetime / live / over
    bomb: str = ""                  # planted / exploded / defused / ""
    win_team: str = ""              # CT / T
    team: str = ""                  # CT / T
    is_local_player: bool = True
    health: int = 100
    armor: int = 0
    helmet: bool = False
    flashed: int = 0
    smoked: int = 0
    burning: int = 0
    money: int = 0
    round_kills: int = 0
    round_killhs: int = 0
    active_weapon: Optional[Weapon] = None
    bomb_planted_at: Optional[float] = None
    round_over_at: Optional[float] = None
    bomb_ended_at: Optional[float] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def in_game(self) -> bool:
        return bool(self.map_phase) and bool(self.team)

    @property
    def alive(self) -> bool:
        return self.health > 0


def parse_state(payload: Dict[str, Any], previous: Optional[GameState] = None,
                now: Optional[float] = None) -> GameState:
    now = time.time() if now is None else now
    prev = previous or GameState()
    st = GameState(received_at=now, raw=payload)

    st.activity = _get(payload, "player", "activity", default="menu") or "menu"
    st.map_phase = _get(payload, "map", "phase", default="") or ""
    st.round_phase = _get(payload, "round", "phase", default="") or ""
    st.bomb = _get(payload, "round", "bomb", default="") or ""
    st.win_team = _get(payload, "round", "win_team", default="") or ""
    st.team = _get(payload, "player", "team", default="") or ""

    provider_id = _get(payload, "provider", "steamid")
    player_id = _get(payload, "player", "steamid")
    st.is_local_player = provider_id is None or player_id is None or provider_id == player_id

    state = _get(payload, "player", "state", default={}) or {}
    st.health = _int(state.get("health"), 100 if not state else 0)
    st.armor = _int(state.get("armor"))
    st.helmet = bool(state.get("helmet", False))
    st.flashed = _int(state.get("flashed"))
    st.smoked = _int(state.get("smoked"))
    st.burning = _int(state.get("burning"))
    st.money = _int(state.get("money"))
    st.round_kills = _int(state.get("round_kills"))
    st.round_killhs = _int(state.get("round_killhs"))

    weapons = _get(payload, "player", "weapons", default={}) or {}
    for w in weapons.values():
        if isinstance(w, dict) and w.get("state") in ("active", "reloading"):
            st.active_weapon = Weapon(
                name=w.get("name", ""),
                type=w.get("type", ""),
                ammo_clip=_int(w.get("ammo_clip"), -1),
                ammo_clip_max=_int(w.get("ammo_clip_max"), -1),
                ammo_reserve=_int(w.get("ammo_reserve"), -1),
                state=w.get("state", ""),
            )
            break

    # Momente de timp pentru animații.
    st.bomb_planted_at = prev.bomb_planted_at if st.bomb == "planted" else None
    if st.bomb == "planted" and prev.bomb != "planted":
        st.bomb_planted_at = now
    st.bomb_ended_at = prev.bomb_ended_at
    if st.bomb in ("exploded", "defused") and prev.bomb != st.bomb:
        st.bomb_ended_at = now
    if not st.bomb:
        st.bomb_ended_at = None
    st.round_over_at = prev.round_over_at if st.round_phase == "over" else None
    if st.round_phase == "over" and prev.round_phase != "over":
        st.round_over_at = now
    return st


class StateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = GameState()
        self.updates = 0
        self.changed = threading.Event()  # trezește motorul când vin date noi

    def update(self, payload: Dict[str, Any], now: Optional[float] = None) -> GameState:
        with self._lock:
            self._state = parse_state(payload, self._state, now)
            self.updates += 1
            state = self._state
        self.changed.set()
        return state

    def get(self) -> GameState:
        with self._lock:
            return self._state


def make_handler(store: StateStore, token: Optional[str],
                 on_update: Optional[Callable[[GameState], None]] = None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AIColorsGSI/1.0"

        def do_POST(self) -> None:  # noqa: N802 (nume impus de http.server)
            length = _int(self.headers.get("Content-Length"))
            body = self.rfile.read(length) if length > 0 else b""
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_error(400, "JSON invalid")
                return
            if token is not None and _get(payload, "auth", "token") != token:
                log.warning("Payload GSI respins: token greșit")
                self.send_error(403, "token invalid")
                return
            state = store.update(payload)
            if on_update:
                on_update(state)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            st = store.get()
            body = json.dumps({
                "updates": store.updates,
                "team": st.team,
                "health": st.health,
                "armor": st.armor,
                "round_phase": st.round_phase,
                "bomb": st.bomb,
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            log.debug("%s - " + fmt, self.address_string(), *args)

    return Handler


class GsiServer:
    def __init__(self, store: StateStore, host: str = "127.0.0.1", port: int = 3000,
                 token: Optional[str] = None,
                 on_update: Optional[Callable[[GameState], None]] = None):
        self.store = store
        self.httpd = ThreadingHTTPServer((host, port), make_handler(store, token, on_update))
        self.httpd.daemon_threads = True
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="gsi", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
