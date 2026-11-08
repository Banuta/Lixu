"""Tastatura ca destinație pentru cadre LED (backend Windows real sau dry-run)."""

from __future__ import annotations

import logging
import sys
import time
from typing import List, Optional, Sequence

from . import protocol
from .protocol import RGB

log = logging.getLogger(__name__)


class KeyboardNotFound(RuntimeError):
    pass


class Keyboard:
    """Interfața comună: trimite cadre de 126 de culori."""

    def send_frame(self, colors: Sequence[RGB]) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self) -> "Keyboard":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class WindowsKeyboard(Keyboard):
    def __init__(self, rgb_order: Sequence[int] = protocol.DEFAULT_RGB_ORDER,
                 vendor_id: int = protocol.VENDOR_ID, product_id: int = protocol.PRODUCT_ID):
        from . import hid_win

        self.rgb_order = tuple(rgb_order)
        interfaces = hid_win.enumerate_interfaces(vendor_id, product_id)
        stream = [
            i for i in interfaces
            if i.usage_page == protocol.VENDOR_USAGE_PAGE
            and i.usage == protocol.VENDOR_USAGE
            and i.feature_len == protocol.FEATURE_LEN_STREAM
        ]
        if not stream:
            found = ", ".join(
                f"page=0x{i.usage_page:04X} usage=0x{i.usage:02X} feature={i.feature_len}"
                for i in interfaces
            ) or "nimic"
            raise KeyboardNotFound(
                f"Nu am găsit interfața LED (VID {vendor_id:04X}, PID {product_id:04X}, "
                f"feature {protocol.FEATURE_LEN_STREAM}). Interfețe găsite: {found}. "
                "Tastatura trebuie să fie conectată prin cablu."
            )
        self._handle = hid_win.HidHandle(stream[0])
        log.info("Tastatură deschisă: %s (fw 0x%04X)", stream[0].path, stream[0].version)

    def send_frame(self, colors: Sequence[RGB]) -> None:
        packet = protocol.build_stream_packet(colors, self.rgb_order)
        last_error: Optional[OSError] = None
        for attempt in range(3):  # ca aplicația originală: 3 încercări, pauză 200 ms
            try:
                self._handle.set_feature(packet)
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.2)
        raise last_error  # type: ignore[misc]

    def close(self) -> None:
        self._handle.close()


class DryRunKeyboard(Keyboard):
    """Nu trimite nimic; opțional desenează cadrul în terminal (ANSI truecolor)."""

    def __init__(self, preview: bool = False, stream=None):
        self.preview = preview
        self.frames_sent = 0
        self.last_frame: Optional[List[RGB]] = None
        self._stream = stream or sys.stdout

    def send_frame(self, colors: Sequence[RGB]) -> None:
        protocol.build_stream_packet(colors)  # validează cadrul
        self.frames_sent += 1
        self.last_frame = list(colors)
        if self.preview:
            self._stream.write("\x1b[H" + render_ansi(colors) + "\n")
            self._stream.flush()


def render_ansi(colors: Sequence[RGB]) -> str:
    from .layout import KEYS

    by_led = {k.led: k for k in KEYS}
    lines = []
    for row in range(1, protocol.LED_ROWS):  # rândul 0 (F1-F12) nu există pe 68%
        cells = []
        for col in range(protocol.LED_COLS):
            led = protocol.led_index(row, col)
            k = by_led.get(led)
            if k is None:
                continue
            r, g, b = (int(c) for c in colors[led])
            label = k.name[:3].center(3)
            fg = "30" if (r * 299 + g * 587 + b * 114) / 1000 > 128 else "97"
            cells.append(f"\x1b[48;2;{r};{g};{b}m\x1b[{fg}m{label}\x1b[0m")
        lines.append(" ".join(cells))
    return "\n".join(lines)


def open_keyboard(dry_run: bool = False, preview: bool = False,
                  rgb_order: Sequence[int] = protocol.DEFAULT_RGB_ORDER) -> Keyboard:
    if dry_run:
        return DryRunKeyboard(preview=preview)
    if sys.platform != "win32":
        raise KeyboardNotFound(
            "Backend-ul HID e implementat doar pentru Windows. Folosește --dry-run pentru test."
        )
    return WindowsKeyboard(rgb_order=rgb_order)
