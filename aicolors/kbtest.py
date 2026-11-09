"""`aicolors kbtest`: test controlat pentru scrierea paletei de culori a tastaturii ZENKABEAT.

Tabela 0xB8 = paletele de câte 7 culori ale efectelor hardware (21 bytes pe efect).
Pași:
  read     citește tabela și salvează un backup (kb_backup_rgbtab.bin)    - fără risc
  red      scrie o singură dată paleta cu toate culorile roșii             - 1 scriere
  check    după ce scoți și bagi la loc cablul: a rămas roșu?            - fără risc
  restore  scrie înapoi backup-ul                                          - 1 scriere
  mode N   schimbă efectul activ (byte-ul de la 0xB60D) în N, ca tasta Fn   - 1 scriere

Cu „check” aflăm dacă tabela stă în memorie temporară (dispare la reconectare:
putem schimba culorile des) sau în flash (rămâne: o schimbăm doar la evenimente rare).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List, Tuple

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


def _read_page(link, page: int) -> bytes:
    a = link.read_page(page << 8)
    b = link.read_page(page << 8)
    if a != b:
        raise SystemExit("Citiri diferite ale aceleiași pagini; nu scriu nimic. Mai încearcă o dată.")
    return a


def set_mode(value: int) -> int:
    """Schimbă efectul activ. Încearcă întâi comanda de profil a aplicației originale,
    apoi scrierea generală de pagină, și verifică prin recitire."""
    from .kblearn import KbLink

    if not 0 <= value <= 0x20:
        print("Valoare de efect neobișnuită; folosește un număr între 0 și 32.")
        return 1
    link = KbLink()
    try:
        page = _read_page(link, protocol.SETTINGS_PAGE)
        old = page[protocol.MODE_OFFSET]
        print(f"Efectul activ acum: {old}  (adresa 0xB60D)")
        if old == value:
            print("E deja setat; nu scriu nimic.")
            return 0
        Path(f"kb_page_B600_backup_{int(time.time())}.bin").write_bytes(page)
        if not _confirm(f"Schimb efectul din {old} în {value} (un singur byte, ca tasta Fn)."):
            print("Anulat.")
            return 1
        new = bytearray(page)
        new[protocol.MODE_OFFSET] = value
        attempts = [
            ("comanda de profil (06 03 B6)",
             protocol.profile_write_packet(protocol.SETTINGS_PAGE, bytes(new[:protocol.PROFILE_LEN]))),
        ]
        for label, packet in attempts:
            link.data.set_feature(packet)
            time.sleep(0.3)
            now = _read_page(link, protocol.SETTINGS_PAGE)
            if now[protocol.MODE_OFFSET] == value and now[protocol.PROFILE_LEN:] == page[protocol.PROFILE_LEN:]:
                print(f"ACCEPTAT prin {label}: tastatura are acum efectul {value}.")
                print("S-a schimbat efectul pe tastatură? Spune-mi da/nu.")
                print(f"Ca să revii: python -m aicolors kbtest mode {old}")
                return 0
            if now[protocol.MODE_OFFSET] == value:
                diff = sum(1 for x, y in zip(now, page) if x != y)
                print(f"Efectul s-a schimbat în {value}, dar încă {diff - 1} bytes din pagină diferă de backup.\n"
                      "Nu mai scriu nimic. Trimite-mi tot textul de aici.")
                return 1
            print(f"{label}: tastatura nu a acceptat scrierea (efect citit: {now[protocol.MODE_OFFSET]}).")
        # A doua variantă: scrierea generală de 1024 bytes (ca la paletă), pe pagina 0xB400 care conține 0xB60D
        if _confirm("Încerc și a doua metodă (scrierea întregii pagini 0xB400, ca la paletă)?"):
            base = _read_page(link, 0xB4)
            off = (protocol.SETTINGS_PAGE << 8) + protocol.MODE_OFFSET - 0xB400
            mod = bytearray(base)
            mod[off] = value
            link.data.set_feature(protocol.write_packet(0xB4, bytes(mod)))
            time.sleep(0.3)
            now = _read_page(link, 0xB4)
            if now == bytes(mod):
                print(f"ACCEPTAT prin scrierea de pagină: efectul e acum {value}. S-a schimbat pe tastatură?")
                print(f"Ca să revii: python -m aicolors kbtest mode {old}")
                return 0
            print(f"Nici scrierea de pagină nu a fost acceptată (efect citit: {now[off]}).")
        print("Trimite-mi tot textul de aici.")
        return 1
    finally:
        link.close()


GAME_GROUPS = 5
GAME_PLANE = 126           # 126 de LED-uri pe plan de culoare
GAME_RGB_INDEX = (2, 1, 0)  # GameRGBIndex din Cfg.ini: planul pentru R, G, B


def decode_game_groups(data: bytes) -> List[List[Tuple[str, Tuple[int, int, int]]]]:
    """Grupurile Game mode ca planuri RGB: grup g, canal c -> data[(g*3 + GAME_RGB_INDEX[c])*126 + RGBTAB]."""
    from .layout import KEYS

    groups = []
    for g in range(GAME_GROUPS):
        lit = []
        for k in KEYS:
            rgb = tuple(data[(g * 3 + GAME_RGB_INDEX[c]) * GAME_PLANE + k.rgbtab]
                        if (g * 3 + GAME_RGB_INDEX[c]) * GAME_PLANE + k.rgbtab < len(data) else 0 for c in range(3))
            if any(rgb):
                lit.append((k.name, rgb))
        groups.append(lit)
    return groups


def game_dump() -> int:
    """Doar citire: ce conține memoria Game mode (0xBC00-0xC3FF)."""
    from .kblearn import KbLink

    link = KbLink()
    try:
        data = link.read_page(0xBC00) + link.read_page(0xC000)
    finally:
        link.close()
    lines = [f"Game mode, memoria 0xBC00 (2048 bytes): {sum(1 for b in data if b)} bytes nenuli"]
    for g, lit in enumerate(decode_game_groups(data)):
        keys = ", ".join(f"{n}=#{r:02x}{gg:02x}{b:02x}" for n, (r, gg, b) in lit[:30])
        lines.append(f"  grup {g + 1}: {len(lit)} taste aprinse" + (f": {keys}" if lit else ""))
    nz = [i for i, b in enumerate(data) if b]
    if nz:
        runs, start, prev = [], nz[0], nz[0]
        for i in nz[1:]:
            if i - prev > 4:
                runs.append((start, prev))
                start = i
            prev = i
        runs.append((start, prev))
        lines.append("  zone nenule: " + ", ".join(f"{0xBC00 + a:#06x}-{0xBC00 + b:#06x}" for a, b in runs[:20]))
        lines.append("  primii bytes: " + data[:96].hex(" "))
    Path("kbgame.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines) + f"\n\nTrimite-mi textul de mai sus (e și în {Path('kbgame.txt').resolve()}).")
    return 0


def _ask(text: str) -> bool:
    try:
        return input(f"{text} (scrie d = da / n = nu, apoi Enter): ").strip().lower() in ("d", "da", "y")
    except EOFError:
        return False


def color_test(static_mode: int = 1) -> int:
    """Poate tastatura să-și schimbe singură culorile? Scrie paleta, reaplică efectul fix, întreabă."""
    from .kbmode import KbModeWriter, fill_palette, palette_groups

    w = KbModeWriter()
    report: List[str] = []
    try:
        orig_mode = w.current()
        orig_pal = w.read_palette()
        groups = palette_groups(orig_pal)
        Path("kb_color_backup_palette.bin").write_bytes(orig_pal)
        print(f"Efectul tău: {orig_mode}; palete găsite: {groups}. Backup: kb_color_backup_palette.bin")
        if not _confirm("Testul schimbă efectul și culorile tastaturii de câteva ori, apoi pune totul înapoi."):
            print("Anulat.")
            return 1
        w.set_mode(static_mode)
        fixed = _ask(f"Am pus efectul {static_mode}. E o singură culoare FIXĂ, fără animație?")
        report.append(f"efect {static_mode} = fix: {fixed}")

        w.write_palette(fill_palette(orig_pal, (255, 0, 0), groups))
        w.set_mode(static_mode, force=True)
        red = _ask("Am scris paleta ROȘIE și am reaplicat efectul. S-a făcut tastatura ROȘIE?")
        report.append(f"roșu prin reaplicare: {red}")
        method = "force" if red else None
        if not red:
            w.set_mode(2 if static_mode != 2 else 3)
            w.set_mode(static_mode)
            red = _ask("Am comutat pe alt efect și înapoi. ACUM e ROȘIE?")
            report.append(f"roșu prin comutare: {red}")
            method = "toggle" if red else None
        if method:
            w.write_palette(fill_palette(orig_pal, (0, 90, 255), groups))
            if method == "force":
                w.set_mode(static_mode, force=True)
            else:
                w.set_mode(2 if static_mode != 2 else 3)
                w.set_mode(static_mode)
            blue = _ask("Am scris paleta ALBASTRĂ. S-a făcut ALBASTRĂ?")
            report.append(f"albastru ({method}): {blue}")
        report.append(f"metodă: {method}; scrieri: {w.writes}")
    finally:
        try:
            w.write_palette(Path("kb_color_backup_palette.bin").read_bytes())
            w.set_mode(orig_mode, force=True)
            print("Am pus înapoi paleta și efectul tău.")
        except Exception as exc:
            print(f"ATENȚIE: nu am putut pune înapoi totul ({exc}). Rulează: python -m aicolors kbtest mode {orig_mode}")
        w.close()
    Path("kbcolor.txt").write_text("\n".join(report), encoding="utf-8")
    print("\nRezultat:\n" + "\n".join(report) + f"\n\nTrimite-mi textul de mai sus (e și în {Path('kbcolor.txt').resolve()}).")
    return 0


def _confirm(text: str) -> bool:
    print(text)
    try:
        return input("Scrie da și apasă Enter ca să continui: ").strip().lower() == "da"
    except EOFError:
        return False


def run(step: str, value: int = -1) -> int:
    if sys.platform != "win32":
        print("Testul funcționează doar pe Windows.")
        return 1
    if step == "game":
        return game_dump()
    if step == "color":
        return color_test(value if value >= 0 else 1)
    if step == "mode":
        if value < 0:
            print("Scrie și numărul efectului, de exemplu: python -m aicolors kbtest mode 5")
            return 1
        return set_mode(value)
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

    print("Pași: learn, read, red, check, restore, mode N")
    return 1
