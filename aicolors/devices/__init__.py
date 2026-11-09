"""Toate tipurile de dispozitive. Ca să adaugi unul nou:

1. creează aicolors/devices/<nume>.py cu o clasă derivată din `Device`
   (metoda `send(colors)`), o funcție `from_config(entry)` și opțional `discover()`
2. adaugă-l în FACTORIES (și în DRY_RUN_LEDS) de mai jos
"""

from __future__ import annotations

import importlib
from typing import Dict, Sequence

from ..protocol import RGB
from .base import Device, DeviceError, Found

# tip -> modulul care are from_config(entry)
FACTORIES: Dict[str, str] = {
    "zenkabeat": "aicolors.devices.zenkabeat",
    "wled": "aicolors.devices.wled",
    "govee": "aicolors.devices.govee",
    "logitech": "aicolors.devices.logitech",
    "openrgb": "aicolors.devices.openrgb",
    "tuya": "aicolors.devices.tuya",
}

# câte LED-uri simulăm în --dry-run când config-ul nu spune
DRY_RUN_LEDS = {"zenkabeat": 126, "wled": 30, "govee": 1, "logitech": 1, "openrgb": 8, "tuya": 1}


class DryRunDevice(Device):
    """Dispozitiv simulat: ține minte ultimul cadru, nu trimite nimic."""

    def __init__(self, kind: str, name: str, led_count: int):
        super().__init__(name, led_count)
        self.kind = kind
        self.frames_sent = 0
        self.last_frame = None

    def send(self, colors: Sequence[RGB]) -> None:
        if len(colors) != self.led_count:
            raise ValueError(f"{self.name}: {len(colors)} culori pentru {self.led_count} LED-uri")
        self.frames_sent += 1
        self.last_frame = list(colors)


def create_device(entry: dict, dry_run: bool = False, preview: bool = False) -> Device:
    kind = entry.get("type")
    if kind not in FACTORIES:
        raise DeviceError(f"tip de dispozitiv necunoscut: {kind!r} (cunoscute: {', '.join(FACTORIES)})")
    if dry_run:
        if kind == "zenkabeat":
            from .zenkabeat import DryRunKeyboard

            return DryRunKeyboard(preview=preview)
        leds = entry.get("leds") or DRY_RUN_LEDS[kind]
        return DryRunDevice(kind, entry.get("name") or f"{kind} (dry-run)", int(leds))
    module = importlib.import_module(FACTORIES[kind])
    return module.from_config(entry)


__all__ = ["Device", "DeviceError", "DryRunDevice", "FACTORIES", "Found", "create_device"]
