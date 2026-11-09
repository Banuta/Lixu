"""Benzi LED cu WLED (ESP32/ESP8266).

Control: protocolul UDP realtime al WLED (port 21324), foarte ieftin:
  DRGB  = [2, timeout, R,G,B, R,G,B, ...]         (max 490 LED-uri)
  DNRGB = [4, timeout, start_hi, start_lo, R,G,B ...] (pentru benzi mai lungi)
După `timeout` secunde fără pachete, WLED revine la efectul lui.

Descoperire: mDNS `_wled._tcp.local`, apoi confirmare cu GET /json/info.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Sequence

from ..discovery import mdns
from ..protocol import RGB
from .base import Device, DeviceError, Found

log = logging.getLogger(__name__)

UDP_PORT = 21324
DRGB_MAX = 490
DNRGB_CHUNK = 489


def get_info(host: str, timeout: float = 1.5) -> Optional[Dict]:
    try:
        with urllib.request.urlopen(f"http://{host}/json/info", timeout=timeout) as resp:
            info = json.loads(resp.read().decode("utf-8", "replace"))
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict) or "leds" not in info:
        return None
    return info


def build_packets(colors: Sequence[RGB], timeout_s: int = 2) -> List[bytes]:
    timeout_s = max(1, min(255, int(timeout_s)))
    flat = bytes(v for c in colors for v in c)
    if len(colors) <= DRGB_MAX:
        return [bytes((2, timeout_s)) + flat]
    packets = []
    for start in range(0, len(colors), DNRGB_CHUNK):
        chunk = flat[start * 3 : (start + DNRGB_CHUNK) * 3]
        packets.append(bytes((4, timeout_s, start >> 8, start & 0xFF)) + chunk)
    return packets


class WledDevice(Device):
    kind = "wled"
    keepalive = 1.0

    def __init__(self, host: str, led_count: Optional[int] = None, port: int = UDP_PORT,
                 timeout_s: int = 2, name: Optional[str] = None):
        if led_count is None:
            info = get_info(host)
            if info is None:
                raise DeviceError(f"WLED {host} nu răspunde la /json/info")
            led_count = int(info["leds"].get("count", 30))
            name = name or info.get("name")
        super().__init__(name or f"WLED {host}", int(led_count))
        self.address = (host, port)
        self.timeout_s = timeout_s
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, colors: Sequence[RGB]) -> None:
        for pkt in build_packets(colors, self.timeout_s):
            self._sock.sendto(pkt, self.address)

    def close(self) -> None:
        self._sock.close()


def from_config(entry: dict) -> Device:
    return WledDevice(entry["host"], entry.get("leds"), entry.get("port", UDP_PORT),
                      entry.get("timeout", 2), entry.get("name"))


def _found(ip: str, info: Dict) -> Found:
    leds = info.get("leds", {}).get("count", "?")
    return Found(
        "wled", info.get("name", "WLED"), address=ip,
        details=f"WLED {info.get('ver', '?')}, {info.get('arch', '?')}, {leds} LED-uri",
        config={"type": "wled", "host": ip, "leds": leds if isinstance(leds, int) else None,
                "effect": "health", "name": info.get("name", "WLED")},
    )


def discover(timeout: float = 2.0, subnet: Optional[str] = None) -> List[Found]:
    hosts = {r["ip"] for r in mdns.browse("_wled._tcp.local.", timeout)}
    if subnet:
        net = ipaddress.ip_network(subnet, strict=False)
        if net.num_addresses > 1024:
            raise ValueError("subrețea prea mare (maxim /22)")
        hosts |= {str(h) for h in net.hosts()}
    found = []
    with ThreadPoolExecutor(max_workers=64) as pool:
        for ip, info in zip(hosts, pool.map(lambda h: get_info(h, 0.8), hosts)):
            if info is not None:
                found.append(_found(ip, info))
    return sorted(found, key=lambda f: f.address)
