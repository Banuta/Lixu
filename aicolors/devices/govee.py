"""Benzi/lămpi Govee prin API-ul LAN oficial (UDP, fără cloud).

Trebuie activat „LAN Control” pentru dispozitiv în aplicația Govee Home.
  * scanare: multicast 239.255.255.250:4001, răspunsurile vin pe portul 4002
  * comenzi: UDP la IP-ul dispozitivului, port 4003 (turn / brightness / colorwc)
Govee nu suportă rate mari de comenzi, așa că limităm la ~10/s și trimitem
doar când se schimbă culoarea (o singură culoare pe toată banda).
"""

from __future__ import annotations

import json
import logging
import socket
import struct
import time
from typing import Dict, List, Optional, Sequence

from ..protocol import RGB
from .base import Device, Found, average

log = logging.getLogger(__name__)

MULTICAST = ("239.255.255.250", 4001)
LISTEN_PORT = 4002
CONTROL_PORT = 4003


def _msg(cmd: str, data: Dict) -> bytes:
    return json.dumps({"msg": {"cmd": cmd, "data": data}}, separators=(",", ":")).encode()


def color_message(color: RGB) -> bytes:
    r, g, b = (int(v) for v in color)
    return _msg("colorwc", {"color": {"r": r, "g": g, "b": b}, "colorTemInKelvin": 0})


class GoveeDevice(Device):
    kind = "govee"
    min_interval = 0.1
    keepalive = 10.0

    def __init__(self, host: str, name: Optional[str] = None, brightness: int = 100):
        super().__init__(name or f"Govee {host}", 1)
        self.address = (host, CONTROL_PORT)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.sendto(_msg("turn", {"value": 1}), self.address)
        self._sock.sendto(_msg("brightness", {"value": max(1, min(100, int(brightness)))}), self.address)

    def send(self, colors: Sequence[RGB]) -> None:
        self._sock.sendto(color_message(average(colors)), self.address)

    def close(self) -> None:
        self._sock.close()


def from_config(entry: dict) -> Device:
    return GoveeDevice(entry["host"], entry.get("name"), entry.get("device_brightness", 100))


def discover(timeout: float = 2.0) -> List[Found]:
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            rx.bind(("", LISTEN_PORT))
        except OSError as exc:
            raise RuntimeError(f"portul {LISTEN_PORT} e ocupat (aplicația Govee de PC?): {exc}") from exc
        try:
            mreq = struct.pack("4s4s", socket.inet_aton(MULTICAST[0]), socket.inet_aton("0.0.0.0"))
            rx.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError:
            pass
        rx.settimeout(0.2)
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        scan = _msg("scan", {"account_topic": "reserve"})
        found: Dict[str, Found] = {}
        deadline = time.time() + timeout
        next_send = 0.0
        try:
            while time.time() < deadline:
                if time.time() >= next_send:
                    tx.sendto(scan, MULTICAST)
                    next_send = time.time() + 0.8
                try:
                    data, (src, _) = rx.recvfrom(4096)
                    msg = json.loads(data.decode("utf-8", "replace")).get("msg", {})
                except (socket.timeout, ValueError, AttributeError):
                    continue
                if msg.get("cmd") != "scan":
                    continue
                d = msg.get("data", {})
                ip = d.get("ip", src)
                sku = d.get("sku", "Govee")
                found[ip] = Found("govee", f"Govee {sku}", address=ip,
                                  details=f"id {d.get('device', '?')}",
                                  config={"type": "govee", "host": ip, "name": f"Govee {sku}",
                                          "effect": "ambient"})
        finally:
            tx.close()
        return list(found.values())
    finally:
        rx.close()
