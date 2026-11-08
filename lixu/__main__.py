"""Linia de comandă: python -m lixu <comandă>

  run          pornește serverul GSI și controlează luminile tastaturii
  install-cfg  scrie gamestate_integration_lixu.cfg în folderul CS2
  test         verifică tastatura: culori pline, ordinea RGB, fiecare tastă
  demo         simulează o rundă (fără CS2), util cu --dry-run --preview
  probe        listează interfețele HID ale tastaturii
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import List, Optional

from . import __version__, cs2cfg, layout, protocol
from .device import Keyboard, KeyboardNotFound, open_keyboard
from .effects import Renderer
from .gsi import GameState, GsiServer, StateStore, parse_state

log = logging.getLogger("lixu")


def _keyboard_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--dry-run", action="store_true", help="nu trimite nimic la tastatură")
    p.add_argument("--preview", action="store_true", help="desenează tastatura în terminal (cu --dry-run)")
    p.add_argument("--rgb-order", default="0,1,2",
                   help="ordinea canalelor în cadru (ca RGBIndex din Cfg.ini); încearcă 2,1,0 dacă roșul iese albastru")


def _open(args) -> Keyboard:
    if args.preview:
        sys.stdout.write("\x1b[2J")
    return open_keyboard(dry_run=args.dry_run, preview=args.preview,
                         rgb_order=protocol.parse_rgb_order(args.rgb_order))


class FrameLoop:
    """Trimite cadre la tastatură; redeschide tastatura dacă se deconectează."""

    def __init__(self, args, keepalive: float = 0.5):
        self.args = args
        self.keepalive = keepalive
        self.kb: Optional[Keyboard] = None
        self.last: Optional[List[protocol.RGB]] = None
        self.last_sent = 0.0
        self.next_retry = 0.0

    def push(self, frame: List[protocol.RGB], now: float) -> None:
        if frame == self.last and now - self.last_sent < self.keepalive:
            return
        if self.kb is None:
            if now < self.next_retry:
                return
            try:
                self.kb = _open(self.args)
            except (KeyboardNotFound, OSError) as exc:
                log.warning("%s (reîncerc în 3 s)", exc)
                self.next_retry = now + 3
                return
        try:
            self.kb.send_frame(frame)
            self.last, self.last_sent = frame, now
        except OSError as exc:
            log.warning("Tastatura nu răspunde (%s); o redeschid.", exc)
            self.close()
            self.next_retry = now + 1

    def close(self) -> None:
        if self.kb is not None:
            self.kb.close()
            self.kb = None


def cmd_run(args) -> int:
    store = StateStore()
    server = GsiServer(store, host=args.host, port=args.port, token=args.token)
    server.start()
    log.info("Server GSI pornit pe http://%s:%d/ - aștept date de la CS2...", args.host, server.port)
    renderer = Renderer(brightness=args.brightness)
    loop = FrameLoop(args)
    interval = 1.0 / args.fps
    last_updates = 0
    try:
        while True:
            now = time.time()
            if store.updates != last_updates:
                if last_updates == 0:
                    log.info("Primesc date de la CS2.")
                last_updates = store.updates
            state = store.get() if store.updates else None
            loop.push(renderer.render(state, now), now)
            time.sleep(max(0.0, interval - (time.time() - now)))
    except KeyboardInterrupt:
        log.info("Oprire.")
    finally:
        server.stop()
        loop.close()
    return 0


def cmd_install_cfg(args) -> int:
    dirs = [Path(args.cs2_dir)] if args.cs2_dir else cs2cfg.find_cs2_cfg_dirs()
    if not dirs:
        print("Nu am găsit CS2. Dă calea manual cu --cs2-dir, de ex.:\n"
              r'  "C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\cfg"')
        print("\nConținutul fișierului", cs2cfg.CFG_NAME + ":\n")
        print(cs2cfg.render_cfg(port=args.port, token=args.token))
        return 1
    for d in dirs:
        path = cs2cfg.install_cfg(d, port=args.port, token=args.token)
        print(f"Scris: {path}")
    print("Repornește CS2 ca să încarce fișierul.")
    return 0


def cmd_test(args) -> int:
    try:
        kb = _open(args)
    except KeyboardNotFound as exc:
        print(exc)
        return 1
    d = args.delay
    with kb:
        for name, color in (("ROȘU", (255, 0, 0)), ("VERDE", (0, 255, 0)),
                            ("ALBASTRU", (0, 0, 255)), ("ALB", (255, 255, 255))):
            print(f"Toată tastatura: {name}")
            kb.send_frame(protocol.solid_frame(color))
            time.sleep(d * 3)
        print("Rând cu rând (sus -> jos)")
        for row in range(protocol.LED_ROWS):
            frame = protocol.solid_frame((0, 0, 0))
            for col in range(protocol.LED_COLS):
                frame[protocol.led_index(row, col)] = (0, 255, 120)
            kb.send_frame(frame)
            time.sleep(d * 2)
        if not args.skip_keys:
            print("Fiecare tastă pe rând (verifică dacă se aprinde tasta afișată)")
            for k in layout.KEYS:
                frame = protocol.solid_frame((0, 0, 0))
                frame[k.led] = (255, 255, 255)
                kb.send_frame(frame)
                print(f"  {k.name:10} LED {k.led}")
                time.sleep(d)
        kb.send_frame(protocol.solid_frame((0, 0, 0)))
    return 0


DEMO_SCRIPT = [
    # (secunde, payload GSI parțial)
    (3, {"player": {"team": "CT", "activity": "playing", "state": {"health": 100, "armor": 100, "helmet": True},
                    "weapons": {"weapon_1": {"name": "weapon_m4a1", "state": "active", "ammo_clip": 20, "ammo_clip_max": 20}}},
         "map": {"phase": "live"}, "round": {"phase": "freezetime"}}),
    (3, {"player": {"team": "CT", "activity": "playing", "state": {"health": 100, "armor": 100, "helmet": True},
                    "weapons": {"weapon_1": {"name": "weapon_m4a1", "state": "active", "ammo_clip": 9, "ammo_clip_max": 20}}},
         "map": {"phase": "live"}, "round": {"phase": "live"}}),
    (2, {"player": {"team": "CT", "activity": "playing", "state": {"health": 73, "armor": 61, "helmet": True,
                                                                    "flashed": 255, "round_kills": 1}},
         "map": {"phase": "live"}, "round": {"phase": "live"}}),
    (3, {"player": {"team": "CT", "activity": "playing", "state": {"health": 18, "armor": 12, "round_kills": 2, "round_killhs": 1,
                                                                    "burning": 200},
                    "weapons": {"weapon_1": {"name": "weapon_m4a1", "state": "active", "ammo_clip": 0, "ammo_clip_max": 20}}},
         "map": {"phase": "live"}, "round": {"phase": "live"}}),
    (8, {"player": {"team": "CT", "activity": "playing", "state": {"health": 18, "armor": 12, "round_kills": 3}},
         "map": {"phase": "live"}, "round": {"phase": "live", "bomb": "planted"}}),
    (4, {"player": {"team": "CT", "activity": "playing", "state": {"health": 18, "armor": 12, "round_kills": 3}},
         "map": {"phase": "live"}, "round": {"phase": "over", "bomb": "defused", "win_team": "CT"}}),
    (3, {"player": {"team": "T", "activity": "playing", "state": {"health": 0}},
         "map": {"phase": "live"}, "round": {"phase": "live"}}),
]


def cmd_demo(args) -> int:
    renderer = Renderer(brightness=args.brightness)
    loop = FrameLoop(args)
    state: Optional[GameState] = None
    try:
        for duration, payload in DEMO_SCRIPT:
            state = parse_state(payload, state)
            end = time.time() + duration
            while time.time() < end:
                now = time.time()
                loop.push(renderer.render(state, now), now)
                time.sleep(1 / args.fps)
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
    return 0


def cmd_probe(args) -> int:
    if sys.platform != "win32":
        print("probe funcționează doar pe Windows.")
        return 1
    from . import hid_win

    vid = None if args.all else protocol.VENDOR_ID
    pid = None if args.all else protocol.PRODUCT_ID
    interfaces = hid_win.enumerate_interfaces(vid, pid)
    if not interfaces:
        print(f"Nicio interfață HID pentru VID {protocol.VENDOR_ID:04X} PID {protocol.PRODUCT_ID:04X}.")
        return 1
    for i in interfaces:
        role = {
            protocol.FEATURE_LEN_STREAM: "cadre LED (folosită de lixu)",
            protocol.FEATURE_LEN_DATA: "date/profiluri",
            protocol.FEATURE_LEN_CMD: "comenzi",
        }.get(i.feature_len, "") if i.usage_page == protocol.VENDOR_USAGE_PAGE else ""
        print(f"{i.vendor_id:04X}:{i.product_id:04X} fw={i.version:04X} mi={i.interface_number} "
              f"page=0x{i.usage_page:04X} usage=0x{i.usage:02X} in={i.input_len} out={i.output_len} "
              f"feature={i.feature_len} {role}")
        if args.verbose:
            print("   ", i.path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lixu", description="Lumini CS2 pentru tastatura ZENKABEAT")
    p.add_argument("--version", action="version", version=f"lixu {__version__}")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="server GSI + lumini")
    r.add_argument("--host", default="127.0.0.1")
    r.add_argument("--port", type=int, default=3000)
    r.add_argument("--token", default=None, help="tokenul din cfg (opțional)")
    r.add_argument("--fps", type=float, default=30.0)
    r.add_argument("--brightness", type=float, default=1.0)
    _keyboard_args(r)
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("install-cfg", help="scrie cfg-ul GSI în CS2")
    c.add_argument("--cs2-dir", help="folderul ...\\game\\csgo\\cfg")
    c.add_argument("--port", type=int, default=3000)
    c.add_argument("--token", default=None)
    c.set_defaults(func=cmd_install_cfg)

    t = sub.add_parser("test", help="testează tastatura")
    t.add_argument("--delay", type=float, default=0.4)
    t.add_argument("--skip-keys", action="store_true")
    _keyboard_args(t)
    t.set_defaults(func=cmd_test)

    d = sub.add_parser("demo", help="simulează o rundă fără CS2")
    d.add_argument("--fps", type=float, default=30.0)
    d.add_argument("--brightness", type=float, default=1.0)
    _keyboard_args(d)
    d.set_defaults(func=cmd_demo)

    pr = sub.add_parser("probe", help="listează interfețele HID")
    pr.add_argument("--all", action="store_true", help="toate dispozitivele HID, nu doar tastatura")
    pr.set_defaults(func=cmd_probe)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
