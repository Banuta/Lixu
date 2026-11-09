"""Tastatura ZENKABEAT (backend Windows real, dry-run și previzualizare în terminal)."""

from __future__ import annotations

import logging
import sys
import time
from typing import List, Optional, Sequence

from .. import protocol
from ..protocol import RGB
from .base import Device, Found

log = logging.getLogger(__name__)


class KeyboardNotFound(RuntimeError):
    pass


class KeyboardLayout:
    """Mixin: efectele de tip bandă se întind pe cele 21 de coloane."""

    led_count = protocol.LED_COUNT

    @property
    def strip_length(self) -> int:
        return protocol.LED_COLS

    def map_strip(self, colors: Sequence[RGB]) -> List[RGB]:
        if len(colors) == protocol.LED_COUNT:
            return list(colors)
        n = len(colors)
        return [colors[min(n - 1, (led // protocol.LED_ROWS) * n // protocol.LED_COLS)]
                for led in range(protocol.LED_COUNT)]


class ZenkabeatKeyboard(KeyboardLayout, Device):
    kind = "zenkabeat"
    keepalive = 0.5

    def __init__(self, rgb_order: Sequence[int] = protocol.DEFAULT_RGB_ORDER,
                 vendor_id: int = protocol.VENDOR_ID, product_id: int = protocol.PRODUCT_ID):
        if sys.platform != "win32":
            raise KeyboardNotFound("Backend-ul HID pentru tastatură e doar pentru Windows (folosește --dry-run).")
        from .. import hid_win

        Device.__init__(self, "ZENKABEAT", protocol.LED_COUNT)
        self.rgb_order = tuple(rgb_order)
        interfaces = hid_win.enumerate_interfaces(vendor_id, product_id)
        stream = [i for i in interfaces if _is_stream(i)]
        if not stream and any(i.feature_len == protocol.FEATURE_LEN_DATA for i in interfaces):
            raise KeyboardNotFound(
                "Tastatura e conectată, dar firmware-ul ei nu are canal de culori live (modul Music). "
                "Dezactiveaz-o deocamdată în Dispozitive; lucrăm la o metodă alternativă."
            )
        if not stream:
            found = ", ".join(
                f"page=0x{i.usage_page:04X} usage=0x{i.usage:02X} feature={i.feature_len}"
                for i in interfaces
            ) or "nimic"
            raise KeyboardNotFound(
                f"Nu am găsit interfața LED (VID {vendor_id:04X}, PID {product_id:04X}, "
                f"feature {protocol.FEATURE_LEN_STREAM}). Interfețe găsite: {found}. "
                "Tastatura trebuie să fie conectată prin cablu, iar aplicația ZENKABEAT închisă."
            )
        self._handle = hid_win.HidHandle(stream[0])
        log.info("Tastatură deschisă: %s (fw 0x%04X)", stream[0].path, stream[0].version)

    def send(self, colors: Sequence[RGB]) -> None:
        packet = protocol.build_stream_packet(colors, self.rgb_order)
        last_error: Optional[OSError] = None
        for _ in range(3):  # ca aplicația originală: 3 încercări, pauză 200 ms
            try:
                self._handle.set_feature(packet)
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.2)
        raise last_error  # type: ignore[misc]

    send_frame = send

    def close(self) -> None:
        self._handle.close()


class DryRunKeyboard(KeyboardLayout, Device):
    """Nu trimite nimic; opțional desenează cadrul în terminal (ANSI truecolor)."""

    kind = "zenkabeat"
    keepalive = 0.5

    def __init__(self, preview: bool = False, stream=None):
        Device.__init__(self, "ZENKABEAT (dry-run)", protocol.LED_COUNT)
        self.preview = preview
        self.frames_sent = 0
        self.last_frame: Optional[List[RGB]] = None
        self._stream = stream or sys.stdout

    def send(self, colors: Sequence[RGB]) -> None:
        protocol.build_stream_packet(colors)  # validează cadrul
        self.frames_sent += 1
        self.last_frame = list(colors)
        if self.preview:
            self._stream.write("\x1b[H" + render_ansi(colors) + "\n")
            self._stream.flush()

    send_frame = send


def _is_stream(i) -> bool:
    return (i.usage_page == protocol.VENDOR_USAGE_PAGE and i.usage == protocol.VENDOR_USAGE
            and i.feature_len == protocol.FEATURE_LEN_STREAM)


def render_ansi(colors: Sequence[RGB]) -> str:
    from ..layout import KEYS

    by_led = {k.led: k for k in KEYS}
    lines = []
    for row in range(1, protocol.LED_ROWS):  # rândul 0 (F1-F12) nu există pe 68%
        cells = []
        for col in range(protocol.LED_COLS):
            k = by_led.get(protocol.led_index(row, col))
            if k is None:
                continue
            r, g, b = (int(c) for c in colors[k.led])
            fg = "30" if (r * 299 + g * 587 + b * 114) / 1000 > 128 else "97"
            cells.append(f"\x1b[48;2;{r};{g};{b}m\x1b[{fg}m{k.name[:3].center(3)}\x1b[0m")
        lines.append(" ".join(cells))
    return "\n".join(lines)


def open_keyboard(dry_run: bool = False, preview: bool = False,
                  rgb_order: Sequence[int] = protocol.DEFAULT_RGB_ORDER) -> Device:
    if dry_run:
        return DryRunKeyboard(preview=preview)
    return ZenkabeatKeyboard(rgb_order=rgb_order)


def from_config(entry: dict) -> Device:
    return ZenkabeatKeyboard(rgb_order=protocol.parse_rgb_order(entry.get("rgb_order", "0,1,2")))


def discover() -> List[Found]:
    if sys.platform != "win32":
        return []
    from .. import hid_win

    found = []
    for i in hid_win.enumerate_interfaces(protocol.VENDOR_ID, protocol.PRODUCT_ID):
        if _is_stream(i):
            found.append(Found("zenkabeat", i.product or "ZENKABEAT Keyboard", address="USB",
                               details=f"fw 0x{i.version:04X}, 126 LED-uri",
                               config={"type": "zenkabeat", "effect": "keyboard"}))
        elif i.usage_page == protocol.VENDOR_USAGE_PAGE and i.feature_len == protocol.FEATURE_LEN_DATA and not found:
            found.append(Found("zenkabeat", i.product or "ZENKABEAT Keyboard", address="USB",
                               details=f"fw 0x{i.version:04X}, conectată", controllable=False,
                               notes=["firmware-ul acestui model nu are canal de culori live (modul Music);"
                                      " lucrăm la o metodă alternativă"]))
    return found


def read_table(table: int = protocol.TABLE_RGB) -> bytes:
    """Citește o tabelă din tastatură (doar citire, nu modifică nimic)."""
    from .. import hid_win

    ifaces = hid_win.enumerate_interfaces(protocol.VENDOR_ID, protocol.PRODUCT_ID)
    cmd = next(i for i in ifaces if i.usage_page == protocol.VENDOR_USAGE_PAGE
               and i.feature_len == protocol.FEATURE_LEN_CMD)
    data = next(i for i in ifaces if i.usage_page == protocol.VENDOR_USAGE_PAGE
                and i.feature_len == protocol.FEATURE_LEN_DATA)
    with hid_win.HidHandle(cmd) as hc, hid_win.HidHandle(data) as hd:
        hc.set_feature(protocol.read_request(table))
        time.sleep(0.02)
        return hd.get_feature(protocol.DATA_REPORT_ID, protocol.FEATURE_LEN_DATA)
