"""`aicolors kbtest`: test controlat pentru scrierea paletei de culori a tastaturii ZENKABEAT.

Tabela 0xB8 = paletele de câte 7 culori ale efectelor hardware (21 bytes pe efect).
Pași:
  read     citește tabela și salvează un backup (kb_backup_rgbtab.bin)    - fără risc
  red      scrie o singură dată paleta cu toate culorile roșii             - 1 scriere
  check    după ce scoți și bagi la loc cablul: a rămas roșu?            - fără risc
  restore  scrie înapoi backup-ul                                          - 1 scriere

Cu „check” aflăm dacă tabela stă în memorie temporară (dispare la reconectare:
putem schimba culorile des) sau în flash (rămâne: o schimbăm doar la evenimente rare).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List

from . import protocol

BACKUP = Path("kb_backup_rgbtab.bin")
TABLE_LEN = 1024
GROUP = 21  # 7 culori x 3 bytes
HEADER_LEN = 8  # 06 88 00 00 00 00 00 00 la citire


def _interfaces():
    from . import hid_win

    ifaces = hid_win.enumerate_interfaces(protocol.VENDOR_ID, protocol.PRODUCT_ID)
    try:
        cmd = next(i for i in ifaces if i.usage_page == protocol.VENDOR_USAGE_PAGE
                   and i.feature_len == protocol.FEATURE_LEN_CMD)
        data = next(i for i in ifaces if i.usage_page == protocol.VENDOR_USAGE_PAGE
                    and i.feature_len == protocol.FEATURE_LEN_DATA)
    except StopIteration:
        raise SystemExit("Nu găsesc tastatura (trebuie pe cablu, iar aplicația ZENKABEAT închisă).")
    return hid_win, cmd, data


def read_table() -> bytes:
    hid_win, cmd, data = _interfaces()
    with hid_win.HidHandle(cmd) as hc, hid_win.HidHandle(data) as hd:
        hc.set_feature(protocol.read_request(protocol.TABLE_RGB))
        time.sleep(0.02)
        raw = hd.get_feature(protocol.DATA_REPORT_ID, protocol.FEATURE_LEN_DATA)
    if len(raw) < HEADER_LEN + TABLE_LEN or raw[1] != protocol.CMD_READ:
        raise SystemExit(f"Răspuns neașteptat de la tastatură: {raw[:16].hex(' ')}")
    return bytes(raw[HEADER_LEN:HEADER_LEN + TABLE_LEN])


def write_table(table: bytes) -> None:
    packet = protocol.write_packet(protocol.TABLE_RGB, table)
    hid_win, _cmd, data = _interfaces()
    with hid_win.HidHandle(data) as hd:
        hd.set_feature(packet)


def palette_groups(table: bytes) -> int:
    """Câte palete (grupuri de 21 bytes nenule) sunt la începutul tabelei."""
    n = 0
    while (n + 1) * GROUP <= len(table) and any(table[n * GROUP:(n + 1) * GROUP]):
        n += 1
    return n


def colors_of(table: bytes, groups: int) -> List[List[str]]:
    return [[f"#{table[g * GROUP + i]:02x}{table[g * GROUP + i + 1]:02x}{table[g * GROUP + i + 2]:02x}"
             for i in range(0, GROUP, 3)] for g in range(groups)]


def all_red(table: bytes, groups: int) -> bytes:
    out = bytearray(table)
    for g in range(groups):
        for i in range(0, GROUP, 3):
            out[g * GROUP + i:g * GROUP + i + 3] = b"\xff\x00\x00"
    return bytes(out)


def is_all_red(table: bytes, groups: int) -> bool:
    return groups > 0 and table[:groups * GROUP] == b"\xff\x00\x00" * (groups * GROUP // 3)


def _confirm(text: str) -> bool:
    print(text)
    try:
        return input("Scrie da și apasă Enter ca să continui: ").strip().lower() == "da"
    except EOFError:
        return False


def run(step: str) -> int:
    if sys.platform != "win32":
        print("Testul funcționează doar pe Windows.")
        return 1
    if step == "read":
        table = read_table()
        groups = palette_groups(table)
        if not BACKUP.exists():
            BACKUP.write_bytes(table)
            print(f"Backup salvat: {BACKUP.resolve()}")
        else:
            print(f"Backup-ul există deja ({BACKUP.resolve()}), nu îl suprascriu.")
        print(f"{groups} palete de efecte găsite. Primele:")
        for g, cols in enumerate(colors_of(table, min(groups, 5))):
            print(f"  efect {g + 1:2}: {' '.join(cols)}")
        print("\nPasul următor: python -m aicolors kbtest red")
        return 0

    if step == "red":
        if not BACKUP.exists():
            print("Rulează întâi: python -m aicolors kbtest read  (face backup-ul)")
            return 1
        backup = BACKUP.read_bytes()
        groups = palette_groups(backup)
        if groups == 0:
            print("Backup-ul nu conține palete; nu scriu nimic.")
            return 1
        if not _confirm(f"Scriu O SINGURĂ DATĂ în tastatură paleta cu toate culorile roșii ({groups} efecte).\n"
                        "Backup-ul e salvat, iar cu „kbtest restore” revii la culorile tale."):
            print("Anulat.")
            return 1
        write_table(all_red(backup, groups))
        time.sleep(0.2)
        ok = is_all_red(read_table(), groups)
        print("Scris și verificat: tabela din tastatură e acum roșie." if ok else
              "Am trimis scrierea, dar la recitire tabela NU e roșie (tastatura a ignorat-o).")
        print("\nUită-te la tastatură: s-a făcut roșie (sau și-a schimbat culorile efectului)?\n"
              "Apoi scoate cablul tastaturii, așteaptă 5 secunde, bagă-l la loc și rulează:\n"
              "  python -m aicolors kbtest check")
        return 0

    if step == "check":
        if not BACKUP.exists():
            print("Nu există backup; rulează întâi kbtest read.")
            return 1
        groups = palette_groups(BACKUP.read_bytes())
        table = read_table()
        if is_all_red(table, groups):
            print("REZULTAT: după reconectare paleta a RĂMAS roșie -> se salvează în memoria permanentă.\n"
                  "Vom schimba culorile tastaturii doar la evenimente (echipă, bombă, moarte), nu continuu.")
        elif table == BACKUP.read_bytes():
            print("REZULTAT: după reconectare paleta a REVENIT la cea veche -> stă în memorie temporară.\n"
                  "Putem schimba culorile des, fără să uzăm tastatura.")
        else:
            print("REZULTAT: tabela nu e nici roșie, nici ca backup-ul. Trimite-mi și primele culori:")
            for g, cols in enumerate(colors_of(table, min(groups, 5))):
                print(f"  efect {g + 1:2}: {' '.join(cols)}")
        print("\nLa final: python -m aicolors kbtest restore")
        return 0

    if step == "restore":
        if not BACKUP.exists():
            print("Nu există backup.")
            return 1
        backup = BACKUP.read_bytes()
        if read_table() == backup:
            print("Tastatura are deja paleta originală; nu scriu nimic.")
            return 0
        write_table(backup)
        time.sleep(0.2)
        print("Paleta originală a fost scrisă înapoi." if read_table() == backup else
              "Am scris backup-ul, dar recitirea diferă. Trimite-mi mesajul ăsta.")
        return 0

    print("Pași: read, red, check, restore")
    return 1
