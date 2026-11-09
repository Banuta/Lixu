"""Client pentru serverul SDK OpenRGB (TCP 6742).

OpenRGB știe deja protocoalele pentru plăcile de bază (ASUS Aura, MSI Mystic Light,
Gigabyte RGB Fusion, ASRock Polychrome), RAM, plăci video, coolere și multe periferice.
Pentru plăcile de bază e cea mai sigură cale: protocoalele lor diferă de la model la
model, iar comenzi greșite pe controller-ul plăcii pot da probleme.

Pornește OpenRGB cu `--server` (sau din tab-ul „SDK Server” -> Start Server).

Folosim protocolul în versiunea 0 (fără negociere), cel mai simplu și compatibil.
"""

from __future__ import annotations

import logging
import socket
import struct
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from ..protocol import RGB
from .base import Device, DeviceError, Found

log = logging.getLogger(__name__)

MAGIC = b"ORGB"
DEFAULT_PORT = 6742
REQUEST_CONTROLLER_COUNT = 0
REQUEST_CONTROLLER_DATA = 1
SET_CLIENT_NAME = 50
DEVICE_LIST_UPDATED = 100
UPDATE_LEDS = 1050
SET_CUSTOM_MODE = 1100

DEVICE_TYPES = [
    "motherboard", "dram", "gpu", "cooler", "ledstrip", "keyboard", "mouse", "mousemat",
    "headset", "headset_stand", "gamepad", "light", "speaker", "virtual", "storage", "case",
    "microphone", "accessory", "keypad", "unknown",
]


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.off = 0

    def take(self, fmt: str):
        size = struct.calcsize(fmt)
        if self.off + size > len(self.data):
            raise ValueError("date OpenRGB trunchiate")
        val = struct.unpack_from(fmt, self.data, self.off)
        self.off += size
        return val[0] if len(val) == 1 else val

    def string(self) -> str:
        n = self.take("<H")
        raw = self.data[self.off : self.off + n]
        self.off += n
        return raw.rstrip(b"\x00").decode("utf-8", "replace")

    def skip(self, n: int) -> None:
        self.off += n


@dataclass
class Controller:
    index: int
    type: str
    name: str
    description: str
    location: str
    zones: List[Tuple[str, int]]
    leds: int


def parse_controller(index: int, data: bytes) -> Controller:
    r = _Reader(data)
    r.take("<I")  # data_size
    ctype = r.take("<i")
    name = r.string()
    description = r.string()
    r.string()  # version
    r.string()  # serial
    location = r.string()
    num_modes = r.take("<H")
    r.take("<i")  # active mode
    for _ in range(num_modes):
        r.string()
        r.skip(4 * 9)  # value, flags, speed_min/max, colors_min/max, speed, direction, color_mode
        r.skip(4 * r.take("<H"))
    zones = []
    for _ in range(r.take("<H")):
        zname = r.string()
        r.skip(4 * 3)  # type, leds_min, leds_max
        count = r.take("<I")
        r.skip(r.take("<H"))  # matrix map
        zones.append((zname, count))
    num_leds = r.take("<H")
    t = DEVICE_TYPES[ctype] if 0 <= ctype < len(DEVICE_TYPES) else "unknown"
    return Controller(index, t, name, description, location, zones, num_leds)


def update_leds_payload(colors: Sequence[RGB]) -> bytes:
    n = len(colors)
    body = b"".join(struct.pack("<BBBB", int(c[0]), int(c[1]), int(c[2]), 0) for c in colors)
    return struct.pack("<IH", 4 + 2 + 4 * n, n) + body


class OpenRGBClient:
    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT, timeout: float = 2.0,
                 name: str = "AI Colors"):
        try:
            self.sock = socket.create_connection((host, port), timeout=timeout)
        except OSError as exc:
            raise DeviceError(f"OpenRGB nu răspunde pe {host}:{port} (e pornit SDK Server?): {exc}") from exc
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._send(0, SET_CLIENT_NAME, name.encode() + b"\x00")

    def _send(self, dev: int, pkt: int, payload: bytes = b"") -> None:
        self.sock.sendall(MAGIC + struct.pack("<III", dev, pkt, len(payload)) + payload)

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise DeviceError("OpenRGB a închis conexiunea")
            buf += chunk
        return buf

    def _request(self, dev: int, pkt: int) -> bytes:
        self._send(dev, pkt)
        while True:
            header = self._recv_exact(16)
            if header[:4] != MAGIC:
                raise DeviceError("răspuns OpenRGB invalid")
            _dev, rpkt, size = struct.unpack("<III", header[4:])
            data = self._recv_exact(size)
            if rpkt == pkt:
                return data

    def controller_count(self) -> int:
        return struct.unpack("<I", self._request(0, REQUEST_CONTROLLER_COUNT)[:4])[0]

    def controller(self, index: int) -> Controller:
        return parse_controller(index, self._request(index, REQUEST_CONTROLLER_DATA))

    def controllers(self) -> List[Controller]:
        return [self.controller(i) for i in range(self.controller_count())]

    def set_custom_mode(self, index: int) -> None:
        self._send(index, SET_CUSTOM_MODE)

    def update_leds(self, index: int, colors: Sequence[RGB]) -> None:
        self._send(index, UPDATE_LEDS, update_leds_payload(colors))

    def close(self) -> None:
        self.sock.close()


def matches(c: Controller, match: Optional[str] = None, dtype: Optional[str] = None,
            index: Optional[int] = None) -> bool:
    if index is not None and c.index != index:
        return False
    if dtype and c.type != dtype:
        return False
    if match and match.lower() not in f"{c.name} {c.description}".lower():
        return False
    return True


def select(controllers: List[Controller], match: Optional[str] = None, dtype: Optional[str] = None,
           index: Optional[int] = None, all_matches: bool = False) -> List[Controller]:
    """Controller-ele potrivite: primul, sau toate (ex. toate plăcuțele de RAM)."""
    found = [c for c in controllers if matches(c, match, dtype, index) and c.leds > 0]
    if not found:
        raise DeviceError(f"niciun controller OpenRGB cu LED-uri pentru match={match!r} "
                          f"device_type={dtype!r} index={index!r}")
    return found if all_matches else found[:1]


class OpenRGBDevice(Device):
    """Unul sau mai multe controller-e OpenRGB, văzute ca o singură bandă de LED-uri."""

    kind = "openrgb"
    min_interval = 0.03
    keepalive = 2.0

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT, match: Optional[str] = None,
                 device_type: Optional[str] = None, index: Optional[int] = None,
                 all_matches: bool = False, name: Optional[str] = None):
        self.client = OpenRGBClient(host, port)
        try:
            ctrls = select(self.client.controllers(), match, device_type, index, all_matches)
            for c in ctrls:
                self.client.set_custom_mode(c.index)
        except Exception:
            self.client.close()
            raise
        label = name or (ctrls[0].name if len(ctrls) == 1 else f"{ctrls[0].name} x{len(ctrls)}")
        super().__init__(label, sum(c.leds for c in ctrls))
        self.controllers = ctrls

    @property
    def controller(self) -> Controller:
        return self.controllers[0]

    def send(self, colors: Sequence[RGB]) -> None:
        try:
            pos = 0
            for c in self.controllers:
                self.client.update_leds(c.index, colors[pos:pos + c.leds])
                pos += c.leds
        except OSError as exc:
            raise DeviceError(f"OpenRGB: {exc}") from exc

    def close(self) -> None:
        self.client.close()


def from_config(entry: dict) -> Device:
    dtype = entry.get("device_type")
    return OpenRGBDevice(entry.get("host", "127.0.0.1"), entry.get("port", DEFAULT_PORT),
                         entry.get("match"), dtype, entry.get("index"),
                         all_matches=bool(entry.get("all", dtype == "dram")), name=entry.get("name"))


def discover(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> List[Found]:
    try:
        client = OpenRGBClient(host, port, timeout=1.0)
    except DeviceError:
        return []
    try:
        found = []
        ctrls = client.controllers()
        drams = [c for c in ctrls if c.type == "dram" and c.leds > 0]
        if drams:
            found.append(Found(
                "openrgb:dram", f"Memorii RAM: {drams[0].name}" + (f" x{len(drams)}" if len(drams) > 1 else ""),
                address=f"{host}:{port} #" + ",".join(str(c.index) for c in drams),
                details=f"{sum(c.leds for c in drams)} LED-uri în {len(drams)} plăcuțe",
                config={"type": "openrgb", "device_type": "dram", "all": True, "effect": "ambient",
                        "name": "Memorii RAM"},
            ))
        names = [c.name for c in ctrls]
        for c in ctrls:
            if c.type == "dram" and c.leds > 0:
                continue
            zones = ", ".join(f"{z} ({n})" for z, n in c.zones) or "-"
            effect = {"motherboard": "ambient", "ledstrip": "health", "keyboard": "health",
                      "mouse": "ambient", "headset": "ambient"}.get(c.type, "ambient")
            config = {"type": "openrgb", "match": c.name, "device_type": c.type, "effect": effect}
            if names.count(c.name) > 1:
                config["index"] = c.index
            found.append(Found(
                f"openrgb:{c.type}", c.name, address=f"{host}:{port} #{c.index}",
                details=f"{c.leds} LED-uri; zone: {zones}", controllable=c.leds > 0, config=config,
            ))
        return found
    finally:
        client.close()
