"""Linia de comandă: python -m lixu <comandă>

  scan         caută dispozitivele: tastatură, placă de bază, Logitech, WLED, Govee, OpenRGB
  run          pornește serverul GSI și controlează toate luminile din lixu.json
  identify     aprinde pe rând fiecare dispozitiv din config, ca să vezi care e care
  install-cfg  scrie gamestate_integration_lixu.cfg în folderul CS2
  test         test detaliat pentru tastatura ZENKABEAT
  demo         simulează o rundă (fără CS2), util cu --dry-run --preview
  probe        listează interfețele HID ale tastaturii
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

from . import __version__, config as configmod, cs2cfg, layout, protocol
from .devices import create_device
from .devices.zenkabeat import KeyboardNotFound, open_keyboard
from .engine import Engine
from .gsi import GsiServer, StateStore

log = logging.getLogger("lixu")


def _common(p: argparse.ArgumentParser, keyboard_only: bool = False) -> None:
    if not keyboard_only:
        p.add_argument("--config", help="fișierul lixu.json (implicit ./lixu.json sau %%APPDATA%%/lixu/lixu.json)")
    p.add_argument("--dry-run", action="store_true", help="nu trimite nimic la dispozitive")
    p.add_argument("--preview", action="store_true", help="desenează tastatura în terminal (cu --dry-run)")


def _load(args) -> configmod.Config:
    cfg = configmod.load(getattr(args, "config", None))
    for name in ("port", "token", "fps", "brightness"):
        value = getattr(args, name, None)
        if value is not None:
            setattr(cfg, name, value)
    log.info("Config: %s (%d dispozitive)", cfg.path or "implicit (doar tastatura)", len(cfg.devices))
    return cfg


def _engine(args, cfg: configmod.Config, store: StateStore) -> Engine:
    if args.preview:
        sys.stdout.write("\x1b[2J")
    return Engine(cfg.devices, store, fps=cfg.fps, idle_fps=cfg.idle_fps, brightness=cfg.brightness,
                  dry_run=args.dry_run, preview=args.preview)


def cmd_run(args) -> int:
    cfg = _load(args)
    store = StateStore()
    server = GsiServer(store, host=cfg.host, port=cfg.port, token=cfg.token)
    server.start()
    log.info("Server GSI pe http://%s:%d/ - aștept date de la CS2...", cfg.host, server.port)
    engine = _engine(args, cfg, store)
    try:
        engine.run()
    except KeyboardInterrupt:
        log.info("Oprire.")
    finally:
        server.stop()
    return 0


def cmd_scan(args) -> int:
    from .discovery.scan import format_results, scan, suggested_devices

    print("Caut dispozitive (câteva secunde)...\n")
    results = scan(timeout=args.timeout, subnet=args.subnet, openrgb_host=args.openrgb_host)
    print(format_results(results))
    devices = suggested_devices(results)
    print("\nConfig sugerat (\"devices\"):")
    print(json.dumps(devices, indent=2, ensure_ascii=False))
    if args.write_config:
        path = Path(args.write_config)
        if path.exists() and not args.force:
            print(f"\n{path} există deja; folosește --force ca să-l suprascrii.")
            return 1
        cfg = configmod.Config(devices=devices or [dict(d) for d in configmod.DEFAULT_DEVICES])
        print(f"\nScris: {configmod.save(cfg, path)}")
    return 0


def cmd_identify(args) -> int:
    cfg = _load(args)
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]
    for entry in cfg.devices:
        label = entry.get("name") or entry.get("type")
        try:
            dev = create_device(entry, dry_run=args.dry_run)
        except Exception as exc:
            print(f"!! {label}: {exc}")
            continue
        with dev:
            print(f"-> {dev.name} ({entry.get('type')}, {dev.led_count} LED-uri): roșu, verde, albastru, alb")
            for c in colors:
                dev.send([c] * dev.led_count)
                time.sleep(args.delay)
            dev.send([(0, 0, 0)] * dev.led_count)
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
        print(f"Scris: {cs2cfg.install_cfg(d, port=args.port, token=args.token)}")
    print("Repornește CS2 ca să încarce fișierul.")
    return 0


def cmd_test(args) -> int:
    try:
        kb = open_keyboard(dry_run=args.dry_run, preview=args.preview,
                           rgb_order=protocol.parse_rgb_order(args.rgb_order))
    except KeyboardNotFound as exc:
        print(exc)
        return 1
    d = args.delay
    with kb:
        for name, color in (("ROȘU", (255, 0, 0)), ("VERDE", (0, 255, 0)),
                            ("ALBASTRU", (0, 0, 255)), ("ALB", (255, 255, 255))):
            print(f"Toată tastatura: {name}")
            kb.send(protocol.solid_frame(color))
            time.sleep(d * 3)
        print("Rând cu rând (sus -> jos)")
        for row in range(protocol.LED_ROWS):
            frame = protocol.solid_frame((0, 0, 0))
            for col in range(protocol.LED_COLS):
                frame[protocol.led_index(row, col)] = (0, 255, 120)
            kb.send(frame)
            time.sleep(d * 2)
        if not args.skip_keys:
            print("Fiecare tastă pe rând (verifică dacă se aprinde tasta afișată)")
            for k in layout.KEYS:
                frame = protocol.solid_frame((0, 0, 0))
                frame[k.led] = (255, 255, 255)
                kb.send(frame)
                print(f"  {k.name:10} LED {k.led}")
                time.sleep(d)
        kb.send(protocol.solid_frame((0, 0, 0)))
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
    (3, {"player": {"team": "CT", "activity": "playing", "state": {"health": 18, "armor": 12, "round_kills": 2,
                                                                    "round_killhs": 1, "burning": 200},
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
    cfg = _load(args)
    store = StateStore()
    engine = _engine(args, cfg, store)
    thread = threading.Thread(target=engine.run, daemon=True)
    thread.start()
    try:
        for duration, payload in DEMO_SCRIPT:
            store.update(payload)
            time.sleep(duration)
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
        thread.join(5)
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
        print(f"{i.vendor_id:04X}:{i.product_id:04X} {i.product!r} fw={i.version:04X} mi={i.interface_number} "
              f"page=0x{i.usage_page:04X} usage=0x{i.usage:02X} in={i.input_len} out={i.output_len} "
              f"feature={i.feature_len} {role}")
        if args.verbose:
            print("   ", i.path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lixu", description="Lumini CS2 pentru tastatură, placă de bază, "
                                                         "Logitech, WLED și Govee")
    p.add_argument("--version", action="version", version=f"lixu {__version__}")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="server GSI + lumini")
    r.add_argument("--port", type=int, default=None)
    r.add_argument("--token", default=None, help="tokenul din cfg-ul CS2 (opțional)")
    r.add_argument("--fps", type=float, default=None, help="cadre/s în animații (implicit 30)")
    r.add_argument("--brightness", type=float, default=None)
    _common(r)
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("scan", help="caută dispozitivele cu lumini")
    s.add_argument("--timeout", type=float, default=2.5)
    s.add_argument("--subnet", help="scanează și subrețeaua pentru WLED, ex. 192.168.1.0/24")
    s.add_argument("--openrgb-host", default="127.0.0.1")
    s.add_argument("--write-config", metavar="FIȘIER", help="scrie config-ul sugerat, ex. lixu.json")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_scan)

    i = sub.add_parser("identify", help="aprinde pe rând fiecare dispozitiv din config")
    i.add_argument("--delay", type=float, default=0.7)
    _common(i)
    i.set_defaults(func=cmd_identify)

    c = sub.add_parser("install-cfg", help="scrie cfg-ul GSI în CS2")
    c.add_argument("--cs2-dir", help="folderul ...\\game\\csgo\\cfg")
    c.add_argument("--port", type=int, default=3000)
    c.add_argument("--token", default=None)
    c.set_defaults(func=cmd_install_cfg)

    t = sub.add_parser("test", help="test detaliat pentru tastatura ZENKABEAT")
    t.add_argument("--delay", type=float, default=0.4)
    t.add_argument("--skip-keys", action="store_true")
    t.add_argument("--rgb-order", default="0,1,2",
                   help="ordinea canalelor (ca RGBIndex din Cfg.ini); încearcă 2,1,0 dacă roșul iese albastru")
    _common(t, keyboard_only=True)
    t.set_defaults(func=cmd_test)

    d = sub.add_parser("demo", help="simulează o rundă fără CS2")
    _common(d)
    d.set_defaults(func=cmd_demo)

    pr = sub.add_parser("probe", help="listează interfețele HID ale tastaturii")
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
