"""`aicolors diag`: diagnostic complet, scris în diagnostic.txt.

Strânge tot ce trebuie ca să vedem de ce nu merge un dispozitiv, fără să
modifice nimic permanent: doar citiri, plus câteva cadre de test pe canalul
live al tastaturii (care nu se salvează în memoria ei).
"""

from __future__ import annotations

import platform
import sys
import time
import traceback
from pathlib import Path
from typing import Callable, List

from . import __version__, protocol


class Report:
    def __init__(self) -> None:
        self.lines: List[str] = []

    def __call__(self, text: str = "") -> None:
        print(text)
        self.lines.append(text)

    def section(self, title: str, fn: Callable[[], None]) -> None:
        self(f"\n===== {title} =====")
        try:
            fn()
        except Exception:
            self("EROARE:\n" + traceback.format_exc())


def _hex(data: bytes, limit: int = 48) -> str:
    return " ".join(f"{b:02x}" for b in data[:limit]) + (" ..." if len(data) > limit else "")


def run(out_path: Path) -> Path:
    r = Report()
    r(f"AI Colors {__version__} - diagnostic {time.strftime('%Y-%m-%d %H:%M:%S')}")
    r(f"Python {sys.version.split()[0]} ({platform.architecture()[0]}), {platform.platform()}")

    if sys.platform != "win32":
        r("Diagnosticul HID funcționează doar pe Windows.")
        out_path.write_text("\n".join(r.lines), encoding="utf-8")
        return out_path

    from . import hid_win

    all_ifaces = []

    def list_all() -> None:
        all_ifaces.extend(hid_win.enumerate_interfaces())
        seen = set()
        for i in sorted(all_ifaces, key=lambda x: (x.vendor_id, x.product_id, x.usage_page, x.usage)):
            key = (i.vendor_id, i.product_id, i.usage_page, i.usage, i.feature_len, i.input_len, i.output_len)
            if key in seen:
                continue
            seen.add(key)
            r(f"{i.vendor_id:04X}:{i.product_id:04X} mi={i.interface_number} page=0x{i.usage_page:04X} "
              f"usage=0x{i.usage:04X} in={i.input_len} out={i.output_len} feature={i.feature_len} "
              f"fw={i.version:04X} {i.manufacturer!r} {i.product!r}")

    r.section("Toate dispozitivele HID", list_all)

    def keyboard() -> None:
        kb = [i for i in all_ifaces if i.vendor_id == protocol.VENDOR_ID]
        if not kb:
            r(f"Nicio interfață cu VID {protocol.VENDOR_ID:04X}. Tastatura e pe cablu? Caută mai sus "
              "un dispozitiv cu numele tastaturii și spune-mi VID:PID-ul lui.")
            return
        r(f"Interfețe cu VID {protocol.VENDOR_ID:04X}: {len(kb)}")
        for i in kb:
            r(f"  {i.product_id:04X} page=0x{i.usage_page:04X} usage=0x{i.usage:04X} feature={i.feature_len} "
              f"in={i.input_len} out={i.output_len}")
            r(f"    {i.path}")
        vendor = [i for i in kb if i.usage_page >= 0xFF00 and i.feature_len]
        for i in vendor:
            r(f"\n-- interfața feature={i.feature_len} (page 0x{i.usage_page:04X})")
            try:
                h = hid_win.HidHandle(i)
            except OSError as exc:
                r(f"   nu se poate deschide: {exc}")
                continue
            with h:
                r("   deschisă OK")
                for rid in (5, 6, 8, 0x0B):
                    try:
                        data = h.get_feature(rid, i.feature_len)
                        r(f"   GetFeature(0x{rid:02X}) OK: {_hex(data)}")
                    except OSError as exc:
                        r(f"   GetFeature(0x{rid:02X}): {exc}")
                if i.feature_len == protocol.FEATURE_LEN_STREAM:
                    for name, color in (("ROȘU", (255, 0, 0)), ("VERDE", (0, 255, 0)), ("ALBASTRU", (0, 0, 255))):
                        try:
                            h.set_feature(protocol.build_stream_packet(protocol.solid_frame(color)))
                            r(f"   cadru live {name}: trimis OK (s-a colorat tastatura?)")
                        except OSError as exc:
                            r(f"   cadru live {name}: EȘUAT {exc}")
                        time.sleep(1.5)
        if not any(i.feature_len == protocol.FEATURE_LEN_STREAM for i in vendor):
            r(f"\nNu există interfața cu feature={protocol.FEATURE_LEN_STREAM}: firmware-ul nu are canalul live "
              "(modul Music). Trebuie folosită altă metodă.")

    r.section("Tastatura ZENKABEAT", keyboard)

    def keyboard_table() -> None:
        from .devices.zenkabeat import read_table

        data = read_table()
        r(f"Răspuns ({len(data)} bytes): {_hex(data, 64)}")
        ok = len(data) > 2 and data[1] == protocol.CMD_READ and data[2] == protocol.TABLE_RGB
        r("Protocolul de citire CONFIRMAT (88 B8)." if ok else "Răspunsul nu începe cu 88 B8: protocolul diferă.")
        body = data[8:8 + 126 * 3]
        r("Primele culori: " + " ".join(f"#{body[i]:02x}{body[i+1]:02x}{body[i+2]:02x}" for i in range(0, 30, 3)))

    r.section("Tabela de culori a tastaturii (doar citire)", keyboard_table)

    def board() -> None:
        from .discovery.motherboard import board_info

        r("Placa de bază: %s %s" % board_info())

    r.section("Placa de bază", board)

    def logitech() -> None:
        from .peripherals.logitech import PeripheralMonitor

        mon = PeripheralMonitor()
        mon._discover()
        for ep in mon.endpoints:
            mon._poll(ep)
        r(mon.note or f"{len(mon.info)} dispozitive HID++")
        for i in mon.info.values():
            r(f"  {i.id} {i.name} [{i.kind}] online={i.online} baterie={i.battery} încarcă={i.charging} "
              f"mV={i.voltage} dpi={i.dpi} hz={i.rate} memorie={i.onboard_mode} {i.error}")
        from .devices.logitech import _ghub_running, find_dll

        r(f"LED SDK DLL: {find_dll()}; G HUB pornit: {_ghub_running()}")

    r.section("Logitech", logitech)

    def network() -> None:
        from .discovery.scan import format_results, scan

        r(format_results(scan(timeout=2.5)))

    r.section("Scanare completă", network)

    out_path.write_text("\n".join(r.lines), encoding="utf-8")
    return out_path
