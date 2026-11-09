"""Logitech HID++ 2.0: baterie, DPI, polling rate, mod onboard.

Este protocolul pe care îl folosesc G HUB și Solaar. Un mesaj „lung”:
    [0x11, device_index, feature_index, (funcție << 4) | sw_id, parametri ... ] = 20 bytes
Fiecare funcționalitate are un ID fix (ex. 0x2201 = DPI); indexul ei pe dispozitiv
se află întrebând feature-ul ROOT (index 0).

Transportul e abstract (write/read), deci codul se poate testa fără hardware.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Tuple

REPORT_SHORT = 0x10
REPORT_LONG = 0x11
LONG_LEN = 20
SW_ID = 0x0B  # ID-ul nostru de software, ca să nu confundăm răspunsurile cu cele pentru G HUB

ROOT = 0x0000
DEVICE_NAME = 0x0005
BATTERY_STATUS = 0x1000
BATTERY_VOLTAGE = 0x1001
UNIFIED_BATTERY = 0x1004
ADC_MEASUREMENT = 0x1F20
ADJUSTABLE_DPI = 0x2201
REPORT_RATE = 0x8060
EXTENDED_REPORT_RATE = 0x8061
ONBOARD_PROFILES = 0x8100
COLOR_LED_EFFECTS = 0x8070
RGB_EFFECTS = 0x8071
EFFECT_STATIC = 0x0001

ERRORS = {
    1: "unknown", 2: "invalid argument", 3: "out of range", 4: "hardware error",
    5: "logitech internal", 6: "invalid feature index", 7: "invalid function", 8: "busy",
    9: "unsupported",
}

# tensiune (mV) -> procent, pentru acumulatori Li-ion 3,7 V (tabel din Solaar)
VOLTAGE_CURVE = [(4186, 100), (4067, 90), (3989, 80), (3922, 70), (3859, 60), (3811, 50),
                 (3778, 40), (3751, 30), (3717, 20), (3671, 10), (3646, 5), (3579, 2), (3500, 0)]

EXT_RATES_HZ = [125, 250, 500, 1000, 2000, 4000, 8000]


class Transport(Protocol):
    def write(self, data: bytes) -> None: ...
    def read(self, timeout: float) -> Optional[bytes]: ...


class HidppError(Exception):
    def __init__(self, code: int, protocol: str = "2.0"):
        self.code = code
        super().__init__(f"HID++ {protocol} eroare {code}: {ERRORS.get(code, '?')}")


class DeviceOffline(TimeoutError):
    pass


@dataclass
class Battery:
    percent: Optional[int]
    charging: bool
    voltage: Optional[int] = None
    source: str = ""


def voltage_to_percent(mv: int) -> int:
    if mv >= VOLTAGE_CURVE[0][0]:
        return 100
    for (v_hi, p_hi), (v_lo, p_lo) in zip(VOLTAGE_CURVE, VOLTAGE_CURVE[1:]):
        if mv >= v_lo:
            return int(round(p_lo + (p_hi - p_lo) * (mv - v_lo) / (v_hi - v_lo)))
    return 0


def parse_dpi_list(data: bytes) -> List[int]:
    """Lista de DPI din getSensorDpiList; valorile 0xE000|pas descriu un interval."""
    raw = []
    for i in range(1, len(data) - 1, 2):
        v = (data[i] << 8) | data[i + 1]
        if v == 0:
            break
        raw.append(v)
    out: List[int] = []
    j = 0
    while j < len(raw):
        v = raw[j]
        if v >> 13 == 0b111 and out and j + 1 < len(raw):
            step = v & 0x1FFF
            out.extend(range(out[-1] + step, raw[j + 1] + 1, step))
            j += 2
        else:
            out.append(v)
            j += 1
    return out


class HidppDevice:
    def __init__(self, transport: Transport, index: int = 0xFF, timeout: float = 0.8, sw_id: int = SW_ID):
        self.transport = transport
        self.index = index
        self.timeout = timeout
        self.sw_id = sw_id & 0x0F
        self._features: Dict[int, Optional[int]] = {ROOT: 0}

    # ------------------------------------------------------------ transport

    def request(self, feature_index: int, function: int, params: bytes = b"",
                timeout: Optional[float] = None) -> bytes:
        func = ((function & 0x0F) << 4) | self.sw_id
        msg = bytes((REPORT_LONG, self.index, feature_index, func)) + bytes(params)
        self.transport.write(msg.ljust(LONG_LEN, b"\x00")[:LONG_LEN])
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DeviceOffline(f"dispozitivul {self.index:#04x} nu răspunde (oprit sau în sleep?)")
            r = self.transport.read(remaining)
            if not r or len(r) < 5 or r[0] not in (REPORT_SHORT, REPORT_LONG) or r[1] != self.index:
                continue
            if r[2] == 0xFF and r[3] == feature_index and r[4] == func:
                raise HidppError(r[5] if len(r) > 5 else 0)
            if r[2] == 0x8F and r[3] == feature_index and r[4] == func:
                raise HidppError(r[5] if len(r) > 5 else 0, "1.0")
            if r[2] == feature_index and r[3] == func:
                return bytes(r[4:])

    def ping(self, timeout: float = 0.4) -> Optional[Tuple[int, int]]:
        """Versiunea protocolului, sau None dacă nu e un dispozitiv HID++ 2.0 activ."""
        try:
            r = self.request(0, 1, bytes((0, 0, 0x5A)), timeout=timeout)
        except (HidppError, DeviceOffline):
            return None
        return (r[0], r[1]) if len(r) > 2 and r[2] == 0x5A else None

    def feature(self, feature_id: int) -> Optional[int]:
        if feature_id not in self._features:
            r = self.request(0, 0, feature_id.to_bytes(2, "big"))
            self._features[feature_id] = r[0] or None
        return self._features[feature_id]

    def call(self, feature_id: int, function: int, params: bytes = b"") -> bytes:
        idx = self.feature(feature_id)
        if idx is None:
            raise HidppError(9)
        return self.request(idx, function, params)

    def has(self, feature_id: int) -> bool:
        try:
            return self.feature(feature_id) is not None
        except HidppError:
            return False

    # ------------------------------------------------------------ informații

    def name(self) -> str:
        if not self.has(DEVICE_NAME):
            return ""
        length = self.call(DEVICE_NAME, 0)[0]
        name = b""
        while len(name) < length:
            chunk = self.call(DEVICE_NAME, 1, bytes((len(name),)))
            if not chunk.strip(b"\x00"):
                break
            name += chunk[: length - len(name)]
        return name.rstrip(b"\x00").decode("utf-8", "replace")

    def battery(self) -> Optional[Battery]:
        if self.has(UNIFIED_BATTERY):
            r = self.call(UNIFIED_BATTERY, 1)
            return Battery(r[0], r[2] in (1, 2, 3), source="unified")
        if self.has(BATTERY_STATUS):
            r = self.call(BATTERY_STATUS, 0)
            return Battery(r[0] or None, r[2] in (1, 2, 3, 4), source="status")
        if self.has(BATTERY_VOLTAGE):
            r = self.call(BATTERY_VOLTAGE, 0)
            mv = (r[0] << 8) | r[1]
            return Battery(voltage_to_percent(mv), bool(r[2] & 0x80), mv, "voltage")
        if self.has(ADC_MEASUREMENT):
            r = self.call(ADC_MEASUREMENT, 0)
            mv = (r[0] << 8) | r[1]
            if not r[2] & 0x01:
                return None
            return Battery(voltage_to_percent(mv), bool(r[2] & 0x02), mv, "adc")
        return None

    # ------------------------------------------------------------ DPI

    def dpi(self) -> Optional[int]:
        if not self.has(ADJUSTABLE_DPI):
            return None
        r = self.call(ADJUSTABLE_DPI, 2, b"\x00")
        return (r[1] << 8) | r[2]

    def dpi_choices(self) -> List[int]:
        if not self.has(ADJUSTABLE_DPI):
            return []
        return parse_dpi_list(self.call(ADJUSTABLE_DPI, 1, b"\x00"))

    def set_dpi(self, dpi: int) -> None:
        choices = self.dpi_choices()
        if choices and dpi not in choices:
            dpi = min(choices, key=lambda c: abs(c - dpi))
        self.call(ADJUSTABLE_DPI, 3, bytes((0, dpi >> 8, dpi & 0xFF)))

    # ------------------------------------------------------------ polling rate

    def report_rate(self) -> Optional[int]:
        """Polling rate curent în Hz."""
        if self.has(EXTENDED_REPORT_RATE):
            i = self.call(EXTENDED_REPORT_RATE, 2)[0]
            return EXT_RATES_HZ[i] if i < len(EXT_RATES_HZ) else None
        if self.has(REPORT_RATE):
            ms = self.call(REPORT_RATE, 1)[0]
            return int(round(1000 / ms)) if ms else None
        return None

    def report_rate_choices(self) -> List[int]:
        if self.has(EXTENDED_REPORT_RATE):
            r = self.call(EXTENDED_REPORT_RATE, 1)
            flags = (r[0] << 8) | r[1]
            return [hz for bit, hz in enumerate(EXT_RATES_HZ) if flags & (1 << bit)]
        if self.has(REPORT_RATE):
            mask = self.call(REPORT_RATE, 0)[0]
            return sorted(int(round(1000 / (bit + 1))) for bit in range(8) if mask & (1 << bit))
        return []

    def set_report_rate(self, hz: int) -> None:
        if self.has(EXTENDED_REPORT_RATE):
            choices = self.report_rate_choices() or EXT_RATES_HZ
            hz = min(choices, key=lambda c: abs(c - hz))
            self.call(EXTENDED_REPORT_RATE, 3, bytes((EXT_RATES_HZ.index(hz),)))
        elif self.has(REPORT_RATE):
            ms = max(1, int(round(1000 / hz)))
            self.call(REPORT_RATE, 2, bytes((ms,)))
        else:
            raise HidppError(9)

    # ------------------------------------------------------------ memorie onboard

    def onboard_mode(self) -> Optional[str]:
        if not self.has(ONBOARD_PROFILES):
            return None
        return {1: "onboard", 2: "host"}.get(self.call(ONBOARD_PROFILES, 2)[0], "?")

    def set_host_mode(self, host: bool = True) -> None:
        """host=True: PC-ul controlează DPI/polling; False: profilurile din memoria mouse-ului."""
        if self.has(ONBOARD_PROFILES):
            self.call(ONBOARD_PROFILES, 1, bytes((2 if host else 1,)))


    # ------------------------------------------------------------ lumini (fără G HUB)

    def light_feature(self) -> Optional[int]:
        if self.has(RGB_EFFECTS):
            return RGB_EFFECTS
        if self.has(COLOR_LED_EFFECTS):
            return COLOR_LED_EFFECTS
        return None

    def light_zones(self) -> List[Tuple[int, int]]:
        """[(zonă, indexul efectului Static în zona aceea)] – structurile din Solaar."""
        feat = self.light_feature()
        zones: List[Tuple[int, int]] = []
        if feat == RGB_EFFECTS:
            count = self.call(RGB_EFFECTS, 0, bytes((0xFF, 0xFF, 0x00)))[2]
            for z in range(count):
                n = self.call(RGB_EFFECTS, 0, bytes((z, 0xFF, 0x00)))[4]
                for e in range(n):
                    info = self.call(RGB_EFFECTS, 0, bytes((z, e, 0x00)))
                    if (info[2] << 8 | info[3]) == EFFECT_STATIC:
                        zones.append((z, info[1]))
                        break
        elif feat == COLOR_LED_EFFECTS:
            count = self.call(COLOR_LED_EFFECTS, 0)[0]
            for z in range(count):
                n = self.call(COLOR_LED_EFFECTS, 1, bytes((z, 0xFF, 0x00)))[3]
                for e in range(n):
                    info = self.call(COLOR_LED_EFFECTS, 2, bytes((z, e, 0x00)))
                    if (info[2] << 8 | info[3]) == EFFECT_STATIC:
                        zones.append((z, info[1]))
                        break
        return zones

    def take_light_control(self, host: bool = True) -> None:
        """host=True: PC-ul controlează luminile; False: dispozitivul (profilul lui)."""
        feat = self.light_feature()
        if feat == RGB_EFFECTS:
            self.call(RGB_EFFECTS, 5, bytes((0x01, 0x01 if host else 0x00)))
        elif feat == COLOR_LED_EFFECTS:
            self.call(COLOR_LED_EFFECTS, 8, bytes((0x01 if host else 0x00,)))

    def set_zone_static(self, zone: int, effect_index: int, color) -> None:
        r, g, b = (int(c) & 0xFF for c in color)
        params = bytes((effect_index, r, g, b, 0, 0, 0, 0, 0, 0, 0))  # index + 10 parametri (culoare, ramp=0)
        if self.light_feature() == RGB_EFFECTS:
            self.call(RGB_EFFECTS, 1, bytes((zone,)) + params + b"\x01")
        else:
            self.call(COLOR_LED_EFFECTS, 3, bytes((zone,)) + params)
