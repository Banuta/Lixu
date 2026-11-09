"""Clasa de bază pentru orice dispozitiv cu lumini.

Un dispozitiv primește o listă de culori (R, G, B) de lungime `led_count`.
Efectele generice (bandă/ambient) produc `strip_length` culori, pe care
`map_strip` le întinde pe LED-urile reale. Pentru o bandă WLED cele două sunt
egale; pentru tastatură banda are 21 de poziții (coloanele).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ..protocol import RGB


class DeviceError(RuntimeError):
    pass


class Device:
    kind = "device"
    #: pauza minimă între două trimiteri (unele dispozitive nu suportă rate mari)
    min_interval = 0.0
    #: retrimite ultimul cadru după atâtea secunde chiar dacă nu s-a schimbat
    keepalive = 1.0

    def __init__(self, name: str, led_count: int):
        self.name = name
        self.led_count = led_count

    @property
    def strip_length(self) -> int:
        return self.led_count

    def map_strip(self, colors: Sequence[RGB]) -> List[RGB]:
        return list(colors)

    def send(self, colors: Sequence[RGB]) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self) -> "Device":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name!r} leds={self.led_count}>"


@dataclass
class Found:
    """Rezultatul unei scanări."""

    kind: str
    name: str
    address: str = ""
    details: str = ""
    controllable: bool = True
    config: Optional[Dict[str, Any]] = None
    notes: List[str] = field(default_factory=list)


def average(colors: Sequence[RGB]) -> RGB:
    if not colors:
        return (0, 0, 0)
    n = len(colors)
    return (
        int(round(sum(c[0] for c in colors) / n)),
        int(round(sum(c[1] for c in colors) / n)),
        int(round(sum(c[2] for c in colors) / n)),
    )
