"""Becuri / benzi Tuya (aplicațiile „Smart Life” și „Tuya Smart”) prin rețeaua locală.

Protocolul local Tuya (port 6668, versiunile 3.1-3.5) e criptat cu AES și o
„local key” per dispozitiv. Folosim biblioteca `tinytuya` (opțională):

    pip install tinytuya
    python -m tinytuya wizard      # o singură dată: îți ia cheile din contul Tuya IoT

Wizard-ul scrie `devices.json` cu id, cheie și nume. aicolors îl citește automat,
deci în config ajunge doar `{"type": "tuya", "id": "..."}`.

Becurile Tuya acceptă doar câteva comenzi pe secundă: aicolors le trimite doar
culoarea „ambient” și maxim ~4 schimbări/s.
"""

from __future__ import annotations

import json
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..protocol import RGB
from .base import Device, DeviceError, Found, average

log = logging.getLogger(__name__)

def _devices_json_paths() -> List[Path]:
    """Unde poate fi devices.json: wizard-ul îl scrie în folderul din care a fost rulat."""
    import os

    from ..config import user_config_path

    home = Path(os.environ.get("USERPROFILE") or Path.home())
    app_dir = Path(__file__).resolve().parents[2]
    dirs = [user_config_path().parent, Path.cwd(), app_dir, home,
            home / "Downloads", home / "Desktop", home / "Documents",
            home / "OneDrive" / "Desktop", home / "OneDrive" / "Documents", home / "OneDrive" / "Documente",
            Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"]
    out: List[Path] = []
    for d in dirs:
        p = d / "devices.json"
        if p not in out:
            out.append(p)
    return out


# Data center-ul proiectului din iot.tuya.com -> codul pentru tinytuya.
# Atenție: un cod necunoscut trimite tinytuya pe serverele din China.
REGIONS = {"eu": "Central Europe", "eu-w": "Western Europe", "us": "Western America",
           "us-e": "Eastern America", "in": "India", "sg": "Singapore", "cn": "China"}

# Coduri de eroare Tuya OpenAPI -> ce ai de făcut
TUYA_HINTS = {
    "1004": "Access Secret greșit (verifică să nu fie spații) sau ceasul PC-ului nu e sincronizat "
            "(Setări Windows -> Oră -> Sincronizează acum).",
    "1010": "Token invalid: încearcă din nou peste câteva secunde.",
    "1106": "Acces refuzat: contul Smart Life nu e legat la proiect (Devices -> Link App Account -> scanezi "
            "QR-ul) sau regiunea aleasă nu e data center-ul proiectului.",
    "28841002": "Perioada gratuită IoT Core a expirat: Cloud -> Project Management -> IoT Core -> Extend trial period.",
    "28841101": "Proiectul nu e abonat la IoT Core: tab-ul Service API -> Go to Authorize -> IoT Core -> Subscribe.",
    "28841105": "Proiectul nu are voie să folosească API-ul: tab-ul Service API -> Go to Authorize -> bifează "
                "IoT Core și Authorization Token Management.",
}


def explain_tuya_error(err) -> str:
    text = str(err)
    for code, hint in TUYA_HINTS.items():
        if re.search(rf"\b{code}\b", text):
            return f"{hint} (cod Tuya {code})"
    if "uid" in text.lower() or "device list" in text.lower():
        return ("Tuya nu găsește dispozitive în proiect: leagă contul Smart Life (Devices -> Link App Account) "
                "și verifică regiunea (data center-ul proiectului).")
    return f"Tuya a răspuns: {text}"


def fetch_cloud_keys(region: str, api_key: str, api_secret: str, device_ids: Optional[List[str]] = None) -> Path:
    """Ia cheile locale din contul Tuya IoT (ca `tinytuya wizard`) și scrie devices.json
    în folderul aplicației. Cheia/secretul API NU se salvează."""
    region = (region or "eu").strip().lower()
    if region not in REGIONS:
        raise DeviceError(f"regiune necunoscută: {region} (alege din {', '.join(REGIONS)})")
    api_key, api_secret = (api_key or "").strip(), (api_secret or "").strip()
    if not api_key or not api_secret:
        raise DeviceError("completează Access ID și Access Secret din tab-ul Overview al proiectului")
    tinytuya = _tinytuya()
    try:
        cloud = tinytuya.Cloud(apiRegion=region, apiKey=api_key, apiSecret=api_secret,
                               apiDeviceID=",".join(device_ids or []) or None)
    except Exception as exc:  # tinytuya aruncă la cheie/secret lipsă sau rețea
        raise DeviceError(explain_tuya_error(exc)) from exc
    if getattr(cloud, "error", None):
        raise DeviceError(explain_tuya_error(cloud.error))
    devices = cloud.getdevices(verbose=False)
    if isinstance(devices, dict):  # tinytuya întoarce un dict cu eroarea
        raise DeviceError(explain_tuya_error(devices))
    if not devices:
        raise DeviceError(explain_tuya_error("Unable to get uid for device list"))
    keep = [{k: d.get(k) for k in ("id", "name", "key", "ip", "version", "product_name", "mac")}
            for d in devices if isinstance(d, dict) and d.get("id")]
    path = _devices_json_paths()[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keep, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _tinytuya():
    try:
        import tinytuya  # type: ignore
    except ImportError as exc:
        raise DeviceError("Pentru becuri Tuya instalează: pip install tinytuya") from exc
    return tinytuya


def wizard_devices(path: Optional[str] = None) -> Dict[str, Dict]:
    """Dispozitivele din devices.json (creat de `python -m tinytuya wizard`), după id.
    Se citesc toate fișierele găsite; primul care are o cheie pentru un id câștigă."""
    found: Dict[str, Dict] = {}
    for p in ([Path(path)] if path else _devices_json_paths()):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for d in data if isinstance(data, list) else []:
            if isinstance(d, dict) and d.get("id") and (d["id"] not in found or not found[d["id"]].get("key")):
                found[d["id"]] = dict(d, _file=str(p))
    return found


VERSIONS = (3.3, 3.1, 3.4, 3.5)


class TuyaBulb(Device):
    kind = "tuya"
    min_interval = 0.25
    keepalive = 30.0

    def __init__(self, dev_id: str, host: Optional[str] = None, local_key: Optional[str] = None,
                 version: Optional[float] = None, name: Optional[str] = None,
                 devices_json: Optional[str] = None):
        tinytuya = _tinytuya()
        known = wizard_devices(devices_json).get(dev_id, {})
        local_key = (local_key or known.get("key") or "").strip()
        host = (host or known.get("ip") or "Auto").strip()
        if not local_key:
            raise DeviceError(f"Tuya {dev_id}: lipsește cheia locală. La Dispozitive, sub rândul Tuya: "
                              "„Încarcă devices.json” sau scrie cheia (câmpul \"key\" din devices.json).")
        super().__init__(name or known.get("name") or f"Tuya {dev_id[-6:]}", 1)
        # versiunea de protocol: cea dată, cea din devices.json, altfel le încercăm pe rând
        given = version or known.get("version")
        versions = [float(given)] if given else list(VERSIONS)
        errors = []
        for v in versions:
            bulb = tinytuya.BulbDevice(dev_id, host, local_key, version=v, persist=True, connection_timeout=2)
            bulb.set_socketTimeout(1)
            status = bulb.status()  # detectează și tipul becului (formatul culorii)
            if isinstance(status, dict) and "Error" not in status:
                self.bulb = bulb
                self.version = v
                break
            err = status.get("Error") if isinstance(status, dict) else status
            errors.append(f"{v}: {err}")
            try:
                bulb.close()
            except Exception:
                pass
        else:
            hint = " (pune IP-ul becului la Dispozitive)" if host == "Auto" else ""
            raise DeviceError(f"Tuya {dev_id} ({host}){hint} nu răspunde: " + "; ".join(errors))
        self.api_status = f"conectat pe {host}, protocol {self.version}"
        self.bulb.turn_on(nowait=True)

    def send(self, colors: Sequence[RGB]) -> None:
        r, g, b = average(colors)
        if max(r, g, b) == 0:
            r = g = b = 1  # (0,0,0) e invalid la Tuya; un minim aproape stins
        self.bulb.set_colour(r, g, b, nowait=True)

    def close(self) -> None:
        try:
            self.bulb.close()
        except Exception:
            pass


def from_config(entry: dict) -> Device:
    return TuyaBulb(entry["id"], entry.get("host"), entry.get("local_key"), entry.get("version"),
                    entry.get("name"), entry.get("devices_json"))


def discover(timeout: float = 6.0) -> List[Found]:
    try:
        tinytuya = _tinytuya()
    except DeviceError as exc:
        return [Found("tuya", "Tuya / Smart Life", details=str(exc), controllable=False)]
    try:
        scanned = tinytuya.deviceScan(False, max(1, int(timeout)), color=False, poll=False)
    except TypeError:
        scanned = tinytuya.deviceScan(False, max(1, int(timeout)))
    known = wizard_devices()
    found = []
    for ip, d in (scanned or {}).items():
        dev_id = d.get("gwId") or d.get("id") or ""
        info = known.get(dev_id, {})
        f = Found("tuya", info.get("name") or f"Tuya {dev_id[-6:]}", address=ip,
                  details=f"id {dev_id}, protocol {d.get('version', '?')}",
                  controllable=bool(info.get("key")),
                  config={"type": "tuya", "id": dev_id, "host": ip, "version": float(d.get("version") or 3.3),
                          "name": info.get("name"), "effect": "ambient"})
        if not info.get("key"):
            f.notes.append("lipsește cheia locală: Setări -> Tuya -> „Ia cheile din contul Tuya”")
        found.append(f)
    return found
