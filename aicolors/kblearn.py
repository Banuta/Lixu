"""`aicolors kbtest learn`: aflăm unde ține tastatura efectul activ.

Programul citește TOATĂ memoria tastaturii (64 KB) înainte și după fiecare pas,
iar tu schimbi efectul / culoarea / luminozitatea direct de pe tastatură (Fn + ...).
Arată exact ce adrese s-au schimbat. DOAR CITIRE: nu scrie nimic în tastatură.

Protocol (confirmat pe tastatura ta):
    SetFeature(interfața de comenzi, 05 88 <adresă/256> 00 00 00 00)
    GetFeature(interfața de date, raport 06, 1032 bytes) -> 06 88 ... + 1024 bytes de la offset 8
Adresele 0x0000-... conțin codul tastaturii (firmware); B800 = paleta, BC00/C000 = culori per tastă.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

from . import protocol

PAGE = 1024
FLASH = 64 * 1024
# Zona în care NU avem voie să scriem niciodată (codul tastaturii). Paleta e la 0xB800.
CODE_LIMIT = 0xB000

STEPS = [
    "Schimbă EFECTUL de lumină de pe tastatură (combinația cu Fn pe care o folosești de obicei)",
    "Schimbă din nou EFECTUL, pe altul",
    "Schimbă CULOAREA efectului (Fn + ..., dacă tastatura are)",
    "Schimbă LUMINOZITATEA (Fn + săgeți sau ce folosești tu)",
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

    def read_page(self, address: int) -> bytes:
        """1024 bytes de la `address` (multiplu de 256)."""
        hi = address >> 8
        for attempt in range(3):
            try:
                self.cmd.set_feature(bytes((protocol.CMD_REPORT_ID, protocol.CMD_READ, hi, 0, 0, 0, 0)))
                time.sleep(0.02)
                raw = self.data.get_feature(protocol.DATA_REPORT_ID, protocol.FEATURE_LEN_DATA)
                if len(raw) >= 8 + PAGE and raw[1] == protocol.CMD_READ:
                    return bytes(raw[8:8 + PAGE])
            except OSError:
                if attempt == 2:
                    raise
            time.sleep(0.1)
        raise OSError(f"citire eșuată la {address:#06x}")

    def dump(self) -> bytes:
        return b"".join(self.read_page(a) for a in range(0, FLASH, PAGE))

    def close(self) -> None:
        self.cmd.close()
        self.data.close()


def changed_runs(a: bytes, b: bytes) -> List[Tuple[int, int]]:
    """Intervale [start, end) de adrese diferite (unite dacă sunt la <8 bytes distanță)."""
    runs: List[Tuple[int, int]] = []
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            if runs and i - runs[-1][1] < 8:
                runs[-1] = (runs[-1][0], i + 1)
            else:
                runs.append((i, i + 1))
    return runs


def describe(a: bytes, b: bytes, limit: int = 30) -> List[str]:
    runs = changed_runs(a, b)
    if not runs:
        return ["  nimic nu s-a schimbat în memoria tastaturii"]
    out = [f"  {sum(e - s for s, e in runs)} bytes schimbați în {len(runs)} zone:"]
    for s, e in runs[:limit]:
        zone = "COD!" if s < CODE_LIMIT else "date"
        out.append(f"  {s:#06x}-{e - 1:#06x} ({zone}): {a[s:e][:24].hex(' ')} -> {b[s:e][:24].hex(' ')}")
    if len(runs) > limit:
        out.append(f"  ... încă {len(runs) - limit} zone")
    return out


def run() -> int:
    if sys.platform != "win32":
        print("Funcționează doar pe Windows.")
        return 1
    print(__doc__)
    out_txt = Path("kblearn.txt")
    backup = Path("kb_flash_backup.bin")
    log: List[str] = []
    link = KbLink()
    try:
        print("Citesc memoria tastaturii (câteva secunde)...")
        current = link.dump()
        if not backup.exists():
            backup.write_bytes(current)
        log.append(f"Memorie citită: {len(current)} bytes. Backup: {backup.resolve()}")
        log.append(f"  paleta B800: {current[0xB800:0xB800 + 21].hex(' ')}")
        nonempty = [a for a in range(0xB000, FLASH, PAGE) if any(x not in (0x00, 0xFF) for x in current[a:a + PAGE])]
        log.append("  pagini de date cu conținut: " + ", ".join(f"{a:#06x}" for a in nonempty))
        print("\n".join(log))
        for idx, step in enumerate(STEPS, 1):
            ans = input(f"\nPasul {idx}/{len(STEPS)}: {step}.\n"
                        "Așteaptă 3 secunde după schimbare, apoi apasă Enter (s + Enter = sari): ")
            if ans.strip().lower() == "s":
                log.append(f"\nPasul {idx} ({step}): sărit")
                continue
            print("Citesc...")
            new = link.dump()
            lines = [f"\nPasul {idx} ({step}):"] + describe(current, new)
            print("\n".join(lines))
            log.extend(lines)
            Path(f"kb_flash_pas{idx}.bin").write_bytes(new)
            current = new
    finally:
        link.close()
        out_txt.write_text("\n".join(log), encoding="utf-8")
    print(f"\nGata. Trimite-mi conținutul fișierului {out_txt.resolve()}")
    return 0


def dump_pages(link: Optional[KbLink] = None) -> bytes:  # pentru alte unelte
    own = link is None
    link = link or KbLink()
    try:
        return link.dump()
    finally:
        if own:
            link.close()
