"""`aicolors kbtest learn`: aflăm unde ține tastatura efectul activ și culorile per tastă.

Tu schimbi setări în aplicația originală ZENKABEAT (poate rămâne deschisă), iar
programul citește memoria tastaturii înainte și după fiecare pas și arată exact ce
bytes s-au schimbat. DOAR CITIRE: nu scrie nimic în tastatură.

Citirile folosesc protocolul confirmat de diagnostic:
    SetFeature(interfața de comenzi, 05 <0x80|op> <adresă> 00 00 00 00)
    GetFeature(interfața de date, raport 06, 1032 bytes) -> 06 <0x80|op> ... date de la offset 8
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import protocol

# (nume, op, adresă) – op fără bitul 0x80
READS: List[Tuple[str, int, int]] = [
    ("profil0", 0x03, 0), ("profil1", 0x03, 1), ("profil2", 0x03, 2), ("profil3", 0x03, 3),
    ("paleta_B8", 0x08, 0xB8),
    ("matrice_BC", 0x09, 0xBC), ("matrice_C0", 0x09, 0xC0),
]

STEPS = [
    "În ZENKABEAT alege efectul „Fixed_on” (lumină fixă) și așteaptă 2 secunde",
    "Alege efectul „Respire”",
    "Alege efectul „Game mode”",
    "În Game mode alege „Color 1”",
    "Alege „Color 2”",
    "Alege „Color 3”",
    "Dacă poți colora taste în Game mode: colorează câteva taste altfel (altfel scrie s)",
    "Pune înapoi efectul tău preferat",
]


class KbLink:
    def __init__(self) -> None:
        from . import hid_win

        ifaces = hid_win.enumerate_interfaces(protocol.VENDOR_ID, protocol.PRODUCT_ID)
        try:
            cmd = next(i for i in ifaces if i.usage_page == protocol.VENDOR_USAGE_PAGE
                       and i.feature_len == protocol.FEATURE_LEN_CMD)
            data = next(i for i in ifaces if i.usage_page == protocol.VENDOR_USAGE_PAGE
                        and i.feature_len == protocol.FEATURE_LEN_DATA)
        except StopIteration:
            raise SystemExit("Nu găsesc tastatura (trebuie pe cablu).")
        self.cmd = hid_win.HidHandle(cmd)
        self.data = hid_win.HidHandle(data)

    def read(self, op: int, addr: int) -> bytes:
        self.cmd.set_feature(bytes((protocol.CMD_REPORT_ID, 0x80 | op, addr, 0, 0, 0, 0)))
        time.sleep(0.03)
        raw = self.data.get_feature(protocol.DATA_REPORT_ID, protocol.FEATURE_LEN_DATA)
        if len(raw) < 8 or raw[1] != (0x80 | op):
            raise OSError(f"răspuns neașteptat: {raw[:8].hex(' ')}")
        return bytes(raw)

    def close(self) -> None:
        self.cmd.close()
        self.data.close()


def snapshot(link: KbLink) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {}
    for name, op, addr in READS:
        try:
            out[name] = link.read(op, addr).hex()
        except OSError as exc:
            out[name] = None
            out[name + "_eroare"] = str(exc)
        time.sleep(0.02)
    return out


def diff(old: Dict[str, Optional[str]], new: Dict[str, Optional[str]]) -> List[str]:
    lines = []
    for name, _op, _addr in READS:
        a, b = old.get(name), new.get(name)
        if a is None or b is None:
            if a != b:
                lines.append(f"  {name}: citire {'reușită' if b else 'eșuată'} acum")
            continue
        ba, bb = bytes.fromhex(a), bytes.fromhex(b)
        changed = [i for i in range(min(len(ba), len(bb))) if ba[i] != bb[i]]
        if not changed:
            continue
        shown = ", ".join(f"[{i}] {ba[i]:02x}->{bb[i]:02x}" for i in changed[:40])
        more = f" ... (+{len(changed) - 40})" if len(changed) > 40 else ""
        lines.append(f"  {name}: {len(changed)} bytes: {shown}{more}")
    return lines or ["  nimic nu s-a schimbat în memoria citită"]


def run() -> int:
    if sys.platform != "win32":
        print("Funcționează doar pe Windows.")
        return 1
    print(__doc__)
    link = KbLink()
    out_txt = Path("kblearn.txt")
    out_raw = Path("kblearn_raw.json")
    log: List[str] = []
    raw: Dict[str, Dict] = {}
    try:
        current = snapshot(link)
        raw["0_inceput"] = current
        log.append("Stare inițială citită. Citiri: " + ", ".join(
            f"{n}={'OK' if current.get(n) else 'EȘUAT'}" for n, _o, _a in READS))
        for n, _o, _a in READS:
            if current.get(n):
                log.append(f"  {n} primii bytes: {current[n][:64]}")
        print("\n".join(log))
        for idx, step in enumerate(STEPS, 1):
            ans = input(f"\nPasul {idx}/{len(STEPS)}: {step}.\nApoi apasă Enter (sau scrie s + Enter ca să sari): ")
            if ans.strip().lower() == "s":
                log.append(f"\nPasul {idx} ({step}): sărit")
                continue
            time.sleep(0.5)
            new = snapshot(link)
            raw[f"{idx}_{step[:30]}"] = new
            lines = [f"\nPasul {idx} ({step}):"] + diff(current, new)
            print("\n".join(lines))
            log.extend(lines)
            current = new
    finally:
        link.close()
        out_txt.write_text("\n".join(log), encoding="utf-8")
        out_raw.write_text(json.dumps(raw, indent=1), encoding="utf-8")
    print(f"\nGata. Trimite-mi conținutul fișierului {out_txt.resolve()}")
    return 0
