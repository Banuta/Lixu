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


class ZenkabeatModeKeyboard(Device):
    """Firmware fără canal live: schimbăm efectul tastaturii după situația din joc.

    `modes` = {situație: număr efect}; situațiile lipsă sau None păstrează efectul tău.
    O scriere doar când se schimbă situația, cel mult una la 3 secunde.
    """

    kind = "zenkabeat"
    min_interval = 3.0
    keepalive = 1e9
    scene_based = True
    DEFAULT_MODES = {"bomb": 4}

    def __init__(self, modes: Optional[dict] = None, writer=None, auto_colors: bool = False,
                 static_mode: int = 1, reload: str = "force"):
        Device.__init__(self, "ZENKABEAT (culori automate)" if auto_colors else "ZENKABEAT (efecte)", 1)
        if writer is None:
            from ..kbmode import KbModeWriter

            writer = KbModeWriter()
        self.writer = writer
        self.modes = dict(self.DEFAULT_MODES if modes is None else modes)
        self.original = writer.current()
        self.current = self.original
        self.scene = ""
        self.auto_colors = auto_colors
        self.static_mode = int(static_mode)
        self.reload = reload
        self.palette_now: Optional[bytes] = None
        self.original_palette: Optional[bytes] = None
        if auto_colors:
            from ..kbmode import load_original_palette, palette_groups

            current = writer.read_palette()
            self.original_palette = load_original_palette(current)
            self.palette_now = current
            self.groups = palette_groups(current)
            if self.original == self.static_mode and self.original_palette != current:
                # pornit după o închidere forțată: efectul fix a rămas de la noi; revenim la respirație
                self.original = 2
        log.info("Tastatură: %s; efectul tău: %d", "culori automate" if auto_colors else "efecte", self.original)

    @staticmethod
    def scene_color(scene: str):
        from .. import effects

        return {
            "ct": effects.CT_COLOR, "t": effects.T_COLOR, "bomb": effects.BOMB_COLOR,
            "dead": effects.DEAD_COLOR, "low_hp": (255, 0, 0), "identify": (255, 255, 255),
        }.get(scene)

    def _apply_auto(self, scene: str) -> None:
        from ..kbmode import fill_palette

        color = self.scene_color(scene)
        if color is None:  # meniu: paleta și efectul tău
            palette, mode = self.original_palette, self.original
        else:
            palette, mode = fill_palette(self.original_palette, color, self.groups), self.static_mode
        palette_changed = palette != self.palette_now
        if palette_changed:
            if not self.writer.write_palette(palette):
                raise OSError("tastatura nu a acceptat paleta")
            self.palette_now = palette
        if mode != self.current:
            self._write(mode)
        elif palette_changed:  # același efect: îl reaplicăm ca să citească paleta nouă
            if self.reload == "toggle":
                other = 2 if mode != 2 else 3
                self.writer.set_mode(other)
                self.writer.set_mode(mode)
            else:
                self.writer.set_mode(mode, force=True)

    def mode_for(self, scene: str) -> int:
        if scene == "identify":
            value = self.modes.get("bomb")
            return int(value) if value not in (None, "") else (1 if self.original != 1 else 2)
        value = self.modes.get(scene)
        return self.original if value in (None, "") else int(value)

    def _write(self, value: int) -> None:
        if value == self.current:
            return
        if not self.writer.set_mode(value):
            raise OSError(f"tastatura nu a acceptat efectul {value}")
        self.current = value

    def send(self, items) -> None:
        scene = items[0] if items and isinstance(items[0], str) else "identify"
        self.scene = scene
        if self.auto_colors:
            self._apply_auto(scene)
        else:
            self._write(self.mode_for(scene))

    def preview(self, value: Optional[int]) -> None:
        """Pentru butonul „Încearcă” din interfață; None = înapoi la efectul tău."""
        self._write(self.original if value is None else int(value))

    def close(self) -> None:
        try:
            if self.auto_colors and self.palette_now != self.original_palette:
                self.writer.write_palette(self.original_palette)
                self.palette_now = self.original_palette
                self.writer.set_mode(self.original, force=True)
                self.current = self.original
            self._write(self.original)
        except Exception as exc:
            log.warning("Nu am putut pune înapoi efectul tastaturii: %s", exc)
        finally:
            self.writer.close()


def has_live_channel() -> bool:
    from .. import hid_win

    return any(_is_stream(i) for i in hid_win.enumerate_interfaces(protocol.VENDOR_ID, protocol.PRODUCT_ID))


def from_config(entry: dict) -> Device:
    if sys.platform == "win32" and not has_live_channel():
        return ZenkabeatModeKeyboard(entry.get("modes"), auto_colors=bool(entry.get("auto_colors", False)),
                                     static_mode=int(entry.get("static_mode", 1)),
                                     reload=entry.get("reload", "force"))
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
                               details=f"fw 0x{i.version:04X}, schimbă efectul la evenimente",
                               config={"type": "zenkabeat", "effect": "keyboard", "modes": {"bomb": 4}},
                               notes=["modelul tău nu are culori live; AI Colors schimbă efectul tastaturii "
                                      "(alegi efectele în Dispozitive -> Efectele tastaturii)"]))
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
