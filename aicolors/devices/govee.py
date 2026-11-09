"""Benzi/lămpi Govee prin API-ul LAN oficial (UDP, fără cloud).

Trebuie activat „LAN Control” pentru dispozitiv în aplicația Govee Home.
  * scanare: multicast 239.255.255.250:4001, răspunsurile vin pe portul 4002
  * comenzi: UDP la IP-ul dispozitivului, port 4003 (turn / brightness / colorwc)
Govee nu suportă rate mari de comenzi, așa că limităm la ~10/s și trimitem
doar când se schimbă culoarea (o singură culoare pe toată banda).

Segmente (benzi RGBIC, ex. H619A): cu "segments" folosim modul DreamView („razer”)
din API-ul LAN, care primește câte o culoare pe segment:
    {"msg": {"cmd": "razer", "data": {"pt": base64(BB 00 len B0 gradient n RGB... xor)}}}
Grupuri: "groups" leagă mai multe segmente într-o singură „lumină”, iar "hosts"
controlează mai multe dispozitive Govee ca unul singur.

Exemple de linii în aicolors.json:
    {"type": "govee", "host": "192.168.68.70"}
    {"type": "govee", "host": "192.168.68.70", "segments": 15, "effect": "health"}
    {"type": "govee", "host": "192.168.68.70", "segments": 15, "groups": [[0,1,2],[3,4,5,6],[7,8],[9,10,11,12,13,14]]}
    {"type": "govee", "hosts": ["192.168.68.70", "192.168.68.80"], "effect": "ambient"}
"""

from __future__ import annotations

import base64
import json
import logging
import socket
import struct
import time
from typing import Dict, List, Optional, Sequence

from ..protocol import RGB
from .base import Device, DeviceError, Found, average

log = logging.getLogger(__name__)

# Câte puncte de culoare are fiecare model în modul pe segmente (din tabela OpenRGB).
SEGMENTS_BY_SKU = {"H619A": 20}

MULTICAST = ("239.255.255.250", 4001)
LISTEN_PORT = 4002
CONTROL_PORT = 4003


def _msg(cmd: str, data: Dict) -> bytes:
    return json.dumps({"msg": {"cmd": cmd, "data": data}}, separators=(",", ":")).encode()


def color_message(color: RGB) -> bytes:
    r, g, b = (int(v) for v in color)
    return _msg("colorwc", {"color": {"r": r, "g": g, "b": b}, "colorTemInKelvin": 0})


def _razer(payload: bytes) -> bytes:
    data = bytes((0xBB, 0x00)) + payload
    checksum = 0
    for b in data:
        checksum ^= b
    pt = base64.b64encode(data + bytes((checksum,))).decode()
    return _msg("razer", {"pt": pt})


def razer_enable(on: bool = True) -> bytes:
    return _razer(bytes((0x01, 0xB1, 0x01 if on else 0x00)))


def razer_frame(colors: Sequence[RGB], gradient: bool = False) -> bytes:
    """Octetul de după B0: 0x01 = culori separate pe segmente, 0x00 = degrade (ca în OpenRGB,
    unde e marcat „gradient_off = 1”)."""
    n = len(colors)
    if not 0 < n <= 80:
        raise ValueError("între 1 și 80 de segmente")
    body = bytes((0x00 if gradient else 0x01, n)) + bytes(int(v) & 0xFF for c in colors for v in c)
    return _razer(bytes((len(body), 0xB0)) + body)


def expand_groups(colors: Sequence[RGB], groups: List[List[int]], segments: int) -> List[RGB]:
    """Culoarea fiecărui grup pe segmentele lui; segmentele din niciun grup rămân stinse."""
    out: List[RGB] = [(0, 0, 0)] * segments
    for color, group in zip(colors, groups):
        for seg in group:
            out[seg] = color
    return out


class GoveeDevice(Device):
    kind = "govee"
    min_interval = 0.1
    keepalive = 10.0
    RAZER_REFRESH = 30.0  # retrimite pornirea modului pe segmente, în caz că dispozitivul a ieșit din el

    def __init__(self, host=None, name: Optional[str] = None, brightness: int = 100,
                 hosts: Optional[List[str]] = None, segments: Optional[int] = None,
                 groups: Optional[List[List[int]]] = None, gradient: bool = False):
        targets = list(hosts or ([host] if host else []))
        if not targets:
            raise DeviceError("Govee: lipsește \"host\" sau \"hosts\"")
        self.segments = int(segments) if segments else 0
        self.groups = [list(map(int, g)) for g in groups] if groups else None
        if self.groups is not None:
            if not self.segments:
                raise DeviceError("Govee: \"groups\" cere și \"segments\" (numărul de segmente)")
            bad = [seg for g in self.groups for seg in g if not 0 <= seg < self.segments]
            if bad:
                raise DeviceError(f"Govee: segmente în afara benzii (0..{self.segments - 1}): {bad}")
        leds = len(self.groups) if self.groups else (self.segments or 1)
        label = name or (f"Govee {targets[0]}" if len(targets) == 1 else f"Govee x{len(targets)}")
        super().__init__(label, leds)
        if self.segments:
            self.min_interval, self.keepalive = 0.05, 2.0
        self.gradient = gradient
        self.addresses = [(h, CONTROL_PORT) for h in targets]
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._razer_at = 0.0
        self._broadcast(_msg("turn", {"value": 1}))
        self._broadcast(_msg("brightness", {"value": max(1, min(100, int(brightness)))}))

    def _broadcast(self, data: bytes) -> None:
        for addr in self.addresses:
            self._sock.sendto(data, addr)

    def send(self, colors: Sequence[RGB]) -> None:
        if not self.segments:
            self._broadcast(color_message(average(colors)))
            return
        now = time.monotonic()
        if now - self._razer_at > self.RAZER_REFRESH:
            self._broadcast(razer_enable(True))
            self._razer_at = now
        seg_colors = expand_groups(colors, self.groups, self.segments) if self.groups else list(colors)
        self._broadcast(razer_frame(seg_colors, self.gradient))

    def close(self) -> None:
        try:
            if self.segments:
                self._broadcast(razer_enable(False))  # banda revine la ce avea înainte
        finally:
            self._sock.close()


def from_config(entry: dict) -> Device:
    return GoveeDevice(entry.get("host"), entry.get("name"), entry.get("device_brightness", 100),
                       hosts=entry.get("hosts"), segments=entry.get("segments"), groups=entry.get("groups"),
                       gradient=bool(entry.get("gradient", False)))


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
                config = {"type": "govee", "host": ip, "name": f"Govee {sku}", "effect": "ambient"}
                segs = SEGMENTS_BY_SKU.get(str(sku).upper())
                if segs:
                    config.update(segments=segs, effect="health")
                found[ip] = Found("govee", f"Govee {sku}", address=ip,
                                  details=f"id {d.get('device', '?')}" + (f", {segs} segmente" if segs else ""),
                                  config=config)
        finally:
            tx.close()
        return list(found.values())
    finally:
        rx.close()
