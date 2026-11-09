"""Logitech G (mouse G502, căști G733 etc.) prin Logitech LED SDK din G HUB.

G HUB înregistrează DLL-ul SDK-ului (sdk_legacy_led_x64.dll) sub CLSID-ul de mai jos;
îl încărcăm direct cu ctypes. Cerințe:
  * G HUB pornit
  * în G HUB: Settings -> „Allow games & applications to control my illumination” activat

Alternativă fără G HUB: OpenRGB (închide G HUB, pornește OpenRGB cu SDK server)
și folosește dispozitivul cu "type": "openrgb".
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from ..protocol import RGB
from .base import Device, DeviceError, Found, average

log = logging.getLogger(__name__)

LOGITECH_VID = 0x046D
SDK_CLSID = "{a6519e67-7632-4375-afdf-caa889744403}"

# DeviceType din LogitechLEDLib.h
TARGETS = {"keyboard": 0x0, "mouse": 0x3, "mousemat": 0x4, "headset": 0x8, "speaker": 0xE}
LOGI_DEVICETYPE_ALL = 0x7

KNOWN_PIDS = {
    0xC539: ("mouse", "Receiver LIGHTSPEED (G502 / G703 / G903 ...)"),
    0xC08D: ("mouse", "G502 LIGHTSPEED (pe cablu)"),
    0xC08B: ("mouse", "G502 HERO"),
    0xC332: ("mouse", "G502 Proteus Spectrum"),
    0xC547: ("mouse", "Receiver LIGHTSPEED (G502 X PLUS ...)"),
    0x0AB5: ("headset", "G733 LIGHTSPEED"),
    0x0B1F: ("headset", "G733 LIGHTSPEED"),
}


def _registry_dll_paths() -> List[str]:
    if sys.platform != "win32":
        return []
    import winreg

    paths = []
    key64 = ctypes.sizeof(ctypes.c_void_p) == 8
    sub = rf"CLSID\{SDK_CLSID}\ServerBinary" if key64 else rf"WOW6432Node\CLSID\{SDK_CLSID}\ServerBinary"
    for s in (sub, rf"CLSID\{SDK_CLSID}\ServerBinary"):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, s) as k:
                paths.append(winreg.QueryValueEx(k, "")[0])
        except OSError:
            pass
    return paths


def candidate_dlls(extra: Optional[str] = None) -> List[str]:
    arch = "x64" if ctypes.sizeof(ctypes.c_void_p) == 8 else "x86"
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    out = [p for p in (extra, os.environ.get("AICOLORS_LOGI_DLL")) if p]
    out += _registry_dll_paths()
    out += [
        os.path.join(pf, "LGHUB", "sdks", f"sdk_legacy_led_{arch}.dll"),
        os.path.join(pf, "LGHUB", f"sdk_legacy_led_{arch}.dll"),
        os.path.join(pf, "Logitech Gaming Software", "SDK", "LED", arch, "LogitechLed.dll"),
        str(Path.cwd() / "LogitechLedEnginesWrapper.dll"),
    ]
    seen, result = set(), []
    for p in out:
        if p.lower() not in seen:
            seen.add(p.lower())
            result.append(p)
    return result


def find_dll(extra: Optional[str] = None) -> Optional[str]:
    for p in candidate_dlls(extra):
        if os.path.isfile(p):
            return p
    return None


class LogiSdk:
    """Un singur SDK pe proces, folosit de toate dispozitivele Logitech."""

    _instance: Optional["LogiSdk"] = None
    _lock = threading.Lock()

    def __init__(self, dll_path: str):
        self.dll = ctypes.CDLL(dll_path)
        d = self.dll
        for fn, args in (
            ("LogiLedSetTargetDevice", [ctypes.c_int]),
            ("LogiLedSetLighting", [ctypes.c_int] * 3),
            ("LogiLedSetLightingForTargetZone", [ctypes.c_int] * 5),
        ):
            if hasattr(d, fn):
                getattr(d, fn).argtypes = args
                getattr(d, fn).restype = ctypes.c_bool
        ok = False
        if hasattr(d, "LogiLedInitWithName"):
            d.LogiLedInitWithName.argtypes = [ctypes.c_char_p]
            d.LogiLedInitWithName.restype = ctypes.c_bool
            ok = d.LogiLedInitWithName(b"AI Colors")
        elif hasattr(d, "LogiLedInit"):
            d.LogiLedInit.restype = ctypes.c_bool
            ok = d.LogiLedInit()
        if not ok:
            raise DeviceError("LogiLedInit a eșuat: e pornit G HUB și e permis controlul luminilor de către aplicații?")
        d.LogiLedSetTargetDevice(LOGI_DEVICETYPE_ALL)
        self.refs = 0
        log.info("Logitech LED SDK încărcat: %s", dll_path)

    @classmethod
    def acquire(cls, dll_path: Optional[str] = None) -> "LogiSdk":
        with cls._lock:
            if cls._instance is None:
                path = find_dll(dll_path)
                if path is None:
                    raise DeviceError("Nu găsesc DLL-ul Logitech LED SDK. Instalează G HUB sau dă calea cu \"dll\".")
                cls._instance = LogiSdk(path)
            cls._instance.refs += 1
            return cls._instance

    def release(self) -> None:
        with self._lock:
            self.refs -= 1
            if self.refs <= 0:
                if hasattr(self.dll, "LogiLedShutdown"):
                    self.dll.LogiLedShutdown()
                LogiSdk._instance = None

    def set_all(self, color: RGB) -> None:
        self.dll.LogiLedSetLighting(*to_percent(color))

    def set_zone(self, target: int, zone: int, color: RGB) -> None:
        self.dll.LogiLedSetLightingForTargetZone(target, zone, *to_percent(color))


def to_percent(color: RGB) -> tuple:
    return tuple(int(round(max(0, min(255, c)) * 100 / 255)) for c in color)


class LogitechDevice(Device):
    kind = "logitech"
    min_interval = 0.03
    keepalive = 2.0

    def __init__(self, target: str = "all", zones: Iterable[int] = (0, 1), dll: Optional[str] = None,
                 name: Optional[str] = None):
        if sys.platform != "win32":
            raise DeviceError("Logitech LED SDK există doar pe Windows")
        if target != "all" and target not in TARGETS:
            raise DeviceError(f"target necunoscut: {target} (alege din all, {', '.join(TARGETS)})")
        super().__init__(name or f"Logitech {target}", 1)
        self.target = target
        self.zones = list(zones)
        self.sdk = LogiSdk.acquire(dll)

    def send(self, colors: Sequence[RGB]) -> None:
        color = average(colors)
        if self.target == "all":
            self.sdk.set_all(color)
        else:
            for zone in self.zones:
                self.sdk.set_zone(TARGETS[self.target], zone, color)

    def close(self) -> None:
        self.sdk.release()


def from_config(entry: dict) -> Device:
    return LogitechDevice(entry.get("target", "all"), entry.get("zones", (0, 1)), entry.get("dll"),
                          entry.get("name"))


def _ghub_running() -> Optional[bool]:
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                             timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return "lghub" in out.lower()


def classify(pid: int, product: str) -> Optional[tuple]:
    if pid in KNOWN_PIDS:
        return KNOWN_PIDS[pid]
    p = product.upper()
    if any(x in p for x in ("G502", "G703", "G903", "G305", "G PRO", "MOUSE")):
        return ("mouse", product)
    if any(x in p for x in ("G733", "G933", "G935", "G635", "G535", "G432", "HEADSET")):
        return ("headset", product)
    if "RECEIVER" in p or "LIGHTSPEED" in p:
        return ("mouse", product)
    return None


def discover() -> List[Found]:
    if sys.platform != "win32":
        return []
    from .. import hid_win

    seen = {}
    for i in hid_win.enumerate_interfaces(LOGITECH_VID):
        kind = classify(i.product_id, i.product)
        if kind and i.product_id not in seen:
            seen[i.product_id] = (kind, i)
    dll = find_dll()
    ghub = _ghub_running()
    found = []
    for pid, ((target, label), i) in seen.items():
        f = Found("logitech", label, address=f"USB {LOGITECH_VID:04X}:{pid:04X}",
                  details=i.product or "", controllable=dll is not None,
                  config={"type": "logitech", "target": target, "name": label,
                          "effect": "ambient" if target == "mouse" else "health"})
        if dll is None:
            f.notes.append("Nu găsesc DLL-ul LED SDK: instalează Logitech G HUB")
        elif ghub is False:
            f.notes.append("G HUB nu rulează: pornește-l (SDK-ul are nevoie de el)")
        f.notes.append("în G HUB activează „Allow games & applications to control my illumination”")
        found.append(f)
    return found
