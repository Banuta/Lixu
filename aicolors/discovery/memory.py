"""Memoriile RAM instalate (model, capacitate) și dacă sunt Kingston FURY RGB.

Pe Windows citim Win32_PhysicalMemory prin PowerShell (o singură dată, la scanare).
LED-urile memoriilor se controlează prin OpenRGB, ca placa de bază: plăcuțele RGB
stau pe magistrala SMBus a plăcii de bază.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import Dict, List

from ..devices.base import Found

# Kingston FURY: coduri care încep cu KF; varianta RGB are de obicei „A” după seria
# (ex. KF436C17BBA/8 = FURY Beast RGB DDR4, KF560C40BBA-16 = FURY Beast RGB DDR5).
FURY_RE = re.compile(r"^KF\d+C\d+([A-Z]{2})(A)?", re.IGNORECASE)


def read_modules() -> List[Dict]:
    if sys.platform != "win32":
        return []
    cmd = ["powershell", "-NoProfile", "-Command",
           "Get-CimInstance Win32_PhysicalMemory | Select-Object DeviceLocator,Manufacturer,PartNumber,"
           "Capacity,ConfiguredClockSpeed | ConvertTo-Json -Compress"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_modules(out)


def parse_modules(text: str) -> List[Dict]:
    try:
        data = json.loads(text or "[]")
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    return [d for d in data if isinstance(d, dict)]


def describe(mods: List[Dict]) -> List[Found]:
    if not mods:
        return []
    parts = [str(m.get("PartNumber") or "").strip() for m in mods]
    total_gb = sum(int(m.get("Capacity") or 0) for m in mods) // (1024 ** 3)
    speed = max(int(m.get("ConfiguredClockSpeed") or 0) for m in mods)
    fury = [p for p in parts if p.upper().startswith("KF")]
    rgb = [p for p in fury if (FURY_RE.match(p) and FURY_RE.match(p).group(2))]
    names = ", ".join(sorted(set(p for p in parts if p))) or "necunoscut"
    vendor = "Kingston FURY" if fury else str(mods[0].get("Manufacturer") or "").strip() or "RAM"
    f = Found("dram", f"{vendor} {names}", address=f"{len(mods)} plăcuțe",
              details=f"{total_gb} GB, {speed} MT/s" + (", RGB" if rgb else ""),
              controllable=False,
              config={"type": "openrgb", "device_type": "dram", "all": True, "effect": "ambient",
                      "name": "Memorii RAM"})
    if fury:
        f.notes.append("Kingston FURY RGB: control prin OpenRGB (apare ca „Kingston Fury DDR4/DDR5 DRAM”)")
        f.notes.append("închide Kingston FURY CTRL, dacă îl ai, ca să nu se certe cu OpenRGB")
    else:
        f.notes.append("dacă memoriile au RGB, le controlezi prin OpenRGB")
    f.notes.append("pornește OpenRGB ca administrator, cu SDK Server, apoi scanează din nou")
    return [f]


def discover() -> List[Found]:
    return describe(read_modules())
