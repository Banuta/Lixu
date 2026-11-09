"""Client mDNS minimal (fără dependențe) pentru a găsi servicii pe rețeaua locală.

Trimite o întrebare PTR de pe un port efemer ("legacy unicast", RFC 6762 §6.7),
deci răspunsurile vin direct la noi și nu trebuie să ocupăm portul 5353.
"""

from __future__ import annotations

import socket
import struct
import time
from typing import Dict, List, Tuple

MDNS_ADDR = ("224.0.0.251", 5353)
TYPE_A, TYPE_PTR, TYPE_SRV = 1, 12, 33


def encode_name(name: str) -> bytes:
    out = b""
    for label in name.strip(".").split("."):
        raw = label.encode("utf-8")
        out += bytes([len(raw)]) + raw
    return out + b"\x00"


def build_query(service: str, query_id: int = 0) -> bytes:
    header = struct.pack(">HHHHHH", query_id, 0, 1, 0, 0, 0)
    return header + encode_name(service) + struct.pack(">HH", TYPE_PTR, 0x8001)  # QU + IN


def read_name(data: bytes, offset: int) -> Tuple[str, int]:
    labels: List[str] = []
    end = None
    jumps = 0
    while True:
        if offset >= len(data):
            raise ValueError("nume DNS trunchiat")
        length = data[offset]
        if length & 0xC0 == 0xC0:
            if end is None:
                end = offset + 2
            offset = ((length & 0x3F) << 8) | data[offset + 1]
            jumps += 1
            if jumps > 20:
                raise ValueError("buclă de compresie DNS")
            continue
        offset += 1
        if length == 0:
            break
        labels.append(data[offset : offset + length].decode("utf-8", "replace"))
        offset += length
    return ".".join(labels) + ".", (end if end is not None else offset)


def parse_records(data: bytes) -> List[Dict]:
    _id, _flags, qd, an, ns, ar = struct.unpack(">HHHHHH", data[:12])
    off = 12
    for _ in range(qd):
        _, off = read_name(data, off)
        off += 4
    records = []
    for _ in range(an + ns + ar):
        name, off = read_name(data, off)
        rtype, _rclass, _ttl, rdlen = struct.unpack(">HHIH", data[off : off + 10])
        off += 10
        rdata_off = off
        rec: Dict = {"name": name, "type": rtype}
        if rtype == TYPE_PTR:
            rec["target"], _ = read_name(data, rdata_off)
        elif rtype == TYPE_SRV:
            _prio, _weight, port = struct.unpack(">HHH", data[rdata_off : rdata_off + 6])
            rec["port"] = port
            rec["target"], _ = read_name(data, rdata_off + 6)
        elif rtype == TYPE_A and rdlen == 4:
            rec["ip"] = socket.inet_ntoa(data[rdata_off : rdata_off + 4])
        records.append(rec)
        off = rdata_off + rdlen
    return records


def browse(service: str, timeout: float = 2.0) -> List[Dict]:
    """Returnează [{instance, ip, port, host}] pentru serviciul cerut (ex. "_wled._tcp.local.")."""
    service = service if service.endswith(".") else service + "."
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        sock.bind(("", 0))
        sock.settimeout(0.2)
        query = build_query(service)
        results: Dict[str, Dict] = {}
        deadline = time.time() + timeout
        next_send = 0.0
        while time.time() < deadline:
            if time.time() >= next_send:
                sock.sendto(query, MDNS_ADDR)
                next_send = time.time() + 0.7
            try:
                data, (src_ip, _) = sock.recvfrom(9000)
            except socket.timeout:
                continue
            except OSError:
                continue
            try:
                records = parse_records(data)
            except (ValueError, struct.error):
                continue
            addrs = {r["name"]: r["ip"] for r in records if r["type"] == TYPE_A}
            srvs = {r["name"]: r for r in records if r["type"] == TYPE_SRV}
            for r in records:
                if r["type"] == TYPE_PTR and r["name"].lower() == service.lower():
                    instance = r["target"]
                    srv = srvs.get(instance, {})
                    host = srv.get("target", "")
                    ip = addrs.get(host, src_ip)
                    results[ip] = {
                        "instance": instance[: -len(service) - 1] if instance.endswith(service) else instance,
                        "ip": ip,
                        "port": srv.get("port", 80),
                        "host": host,
                    }
        return list(results.values())
    finally:
        sock.close()
