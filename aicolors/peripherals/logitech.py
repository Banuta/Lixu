"""Găsește mouse-ul și căștile Logitech (HID++) și le citește/setează periodic.

Rulează pe un fir separat, la prioritatea procesului (below normal), și citește
bateria o dată pe minut: practic zero impact asupra jocului.

Cu G HUB pornit:
  * bateria se citește fără probleme
  * DPI/polling rate: G HUB își aplică propriul profil (și per joc), deci poate
    suprascrie ce setează aicolors. Ori setezi aceleași valori în G HUB, ori închizi
    G HUB (și folosești OpenRGB pentru lumini), ori lași mouse-ul în „host mode”.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from .hidpp import DeviceOffline, HidppDevice, HidppError

log = logging.getLogger(__name__)

LOGITECH_VID = 0x046D
# receivere LIGHTSPEED / Unifying: dispozitivele sunt la indexurile 1..6
RECEIVER_PIDS = {0xC52B, 0xC532, 0xC534, 0xC539, 0xC53A, 0xC53D, 0xC53F, 0xC541, 0xC545, 0xC547, 0xC548}
HEADSET_HINTS = ("G733", "G933", "G935", "G635", "G535", "G435", "PRO X", "HEADSET")


@dataclass
class PeripheralInfo:
    id: str
    name: str
    kind: str                     # mouse / headset / other
    online: bool = False
    battery: Optional[int] = None
    charging: bool = False
    voltage: Optional[int] = None
    dpi: Optional[int] = None
    dpi_choices: List[int] = field(default_factory=list)
    rate: Optional[int] = None
    rate_choices: List[int] = field(default_factory=list)
    onboard_mode: Optional[str] = None
    error: str = ""
    updated: float = 0.0

    def to_dict(self) -> Dict:
        d = asdict(self)
        # lista de DPI poate avea sute de valori; UI-ul vrea doar câteva repere
        if len(self.dpi_choices) > 40:
            lo, hi = self.dpi_choices[0], self.dpi_choices[-1]
            step = self.dpi_choices[1] - lo if len(self.dpi_choices) > 1 else 50
            d["dpi_choices"] = []
            d["dpi_range"] = [lo, hi, step]
        return d


class _Endpoint:
    def __init__(self, stream, device: HidppDevice, product_id: int, product: str):
        self.stream = stream
        self.device = device
        self.product_id = product_id
        self.product = product
        self.lock = threading.Lock()


def _long_collections(interfaces) -> Dict[int, object]:
    """Pentru fiecare PID, colecția HID++ „lungă” (rapoarte de 20 de bytes, pagină vendor)."""
    best: Dict[int, object] = {}
    for i in interfaces:
        if i.usage_page >= 0xFF00 and i.output_len == 20 and i.input_len == 20:
            best.setdefault(i.product_id, i)
    return best


def find_endpoints() -> List[_Endpoint]:
    if sys.platform != "win32":
        return []
    from .. import hid_win

    endpoints = []
    for pid, iface in _long_collections(hid_win.enumerate_interfaces(LOGITECH_VID)).items():
        try:
            stream = hid_win.HidStream(iface)
        except OSError as exc:
            log.debug("nu pot deschide %04X: %s", pid, exc)
            continue
        indexes = range(1, 7) if pid in RECEIVER_PIDS else [0xFF]
        found = False
        for idx in indexes:
            dev = HidppDevice(stream, idx)
            if dev.ping() is not None:
                endpoints.append(_Endpoint(stream, dev, pid, iface.product))
                found = True
        if not found:
            stream.close()
    return endpoints


def _classify(dev: HidppDevice, name: str) -> str:
    if any(h in name.upper() for h in HEADSET_HINTS):
        return "headset"
    if dev.has(0x2201):
        return "mouse"
    return "other"


class PeripheralMonitor:
    def __init__(self, poll_seconds: float = 60.0, settings: Optional[Dict] = None):
        self.poll_seconds = max(10.0, poll_seconds)
        self.settings = settings or {}
        self.endpoints: List[_Endpoint] = []
        self.info: Dict[str, PeripheralInfo] = {}
        self.note = "" if sys.platform == "win32" else "Mouse/căști Logitech: doar pe Windows"
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._applied = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------ fir de lucru

    def start(self) -> None:
        if sys.platform != "win32":
            return
        self._thread = threading.Thread(target=self._loop, name="peripherals", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        for ep in self.endpoints:
            ep.stream.close()

    def refresh(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        last_discovery = 0.0
        while not self._stop.is_set():
            now = time.time()
            if not self.endpoints or now - last_discovery > 300:
                self._discover()
                last_discovery = now
            for ep in list(self.endpoints):
                self._poll(ep)
            if not self._applied:
                self._apply_settings()
            self._wake.wait(self.poll_seconds)
            self._wake.clear()

    def _discover(self) -> None:
        for ep in self.endpoints:
            ep.stream.close()
        try:
            self.endpoints = find_endpoints()
        except Exception as exc:
            log.warning("Logitech: scanare eșuată: %s", exc)
            self.endpoints = []
        if not self.endpoints:
            self.note = "Niciun mouse/căști Logitech HID++ găsit (sunt pornite?)"
        else:
            self.note = ""

    @staticmethod
    def _key(ep: _Endpoint) -> str:
        return f"{ep.product_id:04X}:{ep.device.index:02X}"

    def _poll(self, ep: _Endpoint) -> None:
        key = self._key(ep)
        info = self.info.get(key)
        with ep.lock:
            try:
                dev = ep.device
                if info is None:
                    name = dev.name() or ep.product or f"Logitech {ep.product_id:04X}"
                    info = PeripheralInfo(key, name, _classify(dev, name))
                    if info.kind == "mouse":
                        info.dpi_choices = dev.dpi_choices()
                        info.rate_choices = dev.report_rate_choices()
                    self.info[key] = info
                bat = dev.battery()
                info.battery, info.charging, info.voltage = (
                    (bat.percent, bat.charging, bat.voltage) if bat else (None, False, None))
                if info.kind == "mouse":
                    info.dpi = dev.dpi()
                    info.rate = dev.report_rate()
                    info.onboard_mode = dev.onboard_mode()
                info.online, info.error = True, ""
            except DeviceOffline as exc:
                if info is not None:
                    info.online, info.error = False, str(exc)
            except (HidppError, OSError) as exc:
                if info is not None:
                    info.error = str(exc)
                log.debug("Logitech %s: %s", key, exc)
            if info is not None:
                info.updated = time.time()

    # ------------------------------------------------------------ setări

    def _endpoint(self, key: str) -> Optional[_Endpoint]:
        return next((ep for ep in self.endpoints if self._key(ep) == key), None)

    def _first_mouse(self) -> Optional[str]:
        return next((k for k, i in self.info.items() if i.kind == "mouse"), None)

    def _apply_settings(self) -> None:
        mouse = self.settings.get("mouse") or {}
        key = self._first_mouse()
        if key is None:
            return
        self._applied = True
        try:
            if mouse.get("host_mode"):
                self.set_host_mode(key, True)
            if mouse.get("dpi"):
                self.set_dpi(key, int(mouse["dpi"]))
            if mouse.get("polling_rate"):
                self.set_rate(key, int(mouse["polling_rate"]))
        except Exception as exc:
            log.warning("Nu am putut aplica setările mouse-ului: %s", exc)

    def _do(self, key: str, action) -> None:
        ep = self._endpoint(key)
        if ep is None:
            raise KeyError(f"dispozitiv necunoscut: {key}")
        with ep.lock:
            action(ep.device)
        self._poll(ep)

    def set_dpi(self, key: str, dpi: int) -> None:
        self._do(key, lambda d: d.set_dpi(dpi))
        log.info("DPI %s -> %d", key, dpi)

    def set_rate(self, key: str, hz: int) -> None:
        self._do(key, lambda d: d.set_report_rate(hz))
        log.info("Polling rate %s -> %d Hz", key, hz)

    def set_host_mode(self, key: str, host: bool) -> None:
        self._do(key, lambda d: d.set_host_mode(host))

    def snapshot(self) -> Dict:
        return {"note": self.note, "devices": [i.to_dict() for i in self.info.values()]}


def battery_warnings(snapshot: Dict, already: Dict[str, bool], threshold: int = 15) -> List[str]:
    """Mesaje noi de baterie slabă (o singură dată până la următoarea încărcare)."""
    out = []
    for d in snapshot.get("devices", []):
        key, bat = d.get("id"), d.get("battery")
        if bat is None or not d.get("online"):
            continue
        if bat <= threshold and not d.get("charging"):
            if not already.get(key):
                already[key] = True
                out.append(f"{d.get('name')}: baterie {bat}%")
        elif bat > threshold + 5 or d.get("charging"):
            already[key] = False
    return out
