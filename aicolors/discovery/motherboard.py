"""Identifică placa de bază și controller-ele RGB de pe ea.

Citește producătorul/modelul plăcii (registry pe Windows, DMI pe Linux) și caută
controller-e RGB USB cunoscute. Controlul efectiv se face prin OpenRGB
(vezi devices/openrgb.py): fiecare producător are alt protocol, uneori pe SMBus.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

from ..devices.base import Found

# VID-uri de controller-e RGB de placă de bază văzute pe USB.
RGB_CONTROLLER_VIDS = {
    0x0B05: "ASUS (Aura)",
    0x1462: "MSI (Mystic Light)",
    0x048D: "ITE (Gigabyte RGB Fusion 2)",
    0x26CE: "ASRock (Polychrome)",
}

BOARD_HINTS = {
    "ASUS": "ASUS Aura: în OpenRGB apare ca „ASUS Aura USB/SMBus”",
    "MICRO-STAR": "MSI Mystic Light: în OpenRGB apare ca „MSI Mystic Light”",
    "MSI": "MSI Mystic Light: în OpenRGB apare ca „MSI Mystic Light”",
    "GIGABYTE": "Gigabyte RGB Fusion 2: în OpenRGB apare ca „Gigabyte RGB Fusion 2”",
    "ASROCK": "ASRock Polychrome: în OpenRGB apare ca „ASRock Polychrome”",
}


def board_info() -> Tuple[str, str]:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as k:
                vendor = winreg.QueryValueEx(k, "BaseBoardManufacturer")[0]
                product = winreg.QueryValueEx(k, "BaseBoardProduct")[0]
                return str(vendor).strip(), str(product).strip()
        except OSError:
            return "", ""
    base = Path("/sys/class/dmi/id")
    try:
        return ((base / "board_vendor").read_text().strip(), (base / "board_name").read_text().strip())
    except OSError:
        return "", ""


def discover() -> List[Found]:
    vendor, product = board_info()
    found: List[Found] = []
    if vendor or product:
        f = Found("motherboard", f"{vendor} {product}".strip(), address="placa de bază",
                  details="control prin OpenRGB", controllable=False,
                  config={"type": "openrgb", "device_type": "motherboard", "effect": "ambient"})
        for key, hint in BOARD_HINTS.items():
            if key in vendor.upper():
                f.notes.append(hint)
                break
        f.notes.append("pornește OpenRGB cu SDK Server ca să o controlezi")
        found.append(f)
    if sys.platform == "win32":
        from .. import hid_win

        seen = set()
        for i in hid_win.enumerate_interfaces():
            label = RGB_CONTROLLER_VIDS.get(i.vendor_id)
            key = (i.vendor_id, i.product_id)
            if label and key not in seen and i.usage_page >= 0xFF00:
                seen.add(key)
                found.append(Found("motherboard-rgb", i.product or label,
                                   address=f"USB {i.vendor_id:04X}:{i.product_id:04X}",
                                   details=f"posibil controller RGB {label}", controllable=False,
                                   notes=["control prin OpenRGB"]))
    return found
