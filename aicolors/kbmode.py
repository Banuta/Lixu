"""Schimbarea efectului activ al tastaturii ZENKABEAT (firmware fără canal live).

Efectul activ e un byte la 0xB60D (găsit cu `kbtest learn`; tastatura îl scrie
singură la fiecare Fn). Îl schimbăm cu comanda de profil a aplicației originale
(06 03 B6 + 254 bytes) și verificăm prin recitire; dacă nu e acceptată, folosim
scrierea de pagină (06 08 B4 00 40 + 1024 bytes). Zona de cod e blocată de protocol.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from . import protocol

log = logging.getLogger(__name__)

MAX_MODE = 0x20


class KbModeWriter:
    def __init__(self, link=None):
        if link is None:
            from .kblearn import KbLink

            link = KbLink()
        self.link = link
        self.method: Optional[str] = None  # "profile" sau "page", după prima scriere reușită
        self.writes = 0

    def _stable(self, page: int) -> bytes:
        a = self.link.read_page(page << 8)
        b = self.link.read_page(page << 8)
        if a != b:
            raise OSError("citiri instabile ale memoriei tastaturii")
        return a

    def current(self) -> int:
        return self._stable(protocol.SETTINGS_PAGE)[protocol.MODE_OFFSET]

    def _via_profile(self, page: bytes, value: int) -> bool:
        new = bytearray(page)
        new[protocol.MODE_OFFSET] = value
        self.link.data.set_feature(protocol.profile_write_packet(protocol.SETTINGS_PAGE,
                                                                 bytes(new[:protocol.PROFILE_LEN])))
        time.sleep(0.25)
        now = self._stable(protocol.SETTINGS_PAGE)
        return now[protocol.MODE_OFFSET] == value and now[protocol.PROFILE_LEN:] == page[protocol.PROFILE_LEN:]

    def _via_page(self, value: int) -> bool:
        base = self._stable(0xB4)
        off = (protocol.SETTINGS_PAGE << 8) + protocol.MODE_OFFSET - 0xB400
        mod = bytearray(base)
        mod[off] = value
        self.link.data.set_feature(protocol.write_packet(0xB4, bytes(mod)))
        time.sleep(0.25)
        return self._stable(0xB4) == bytes(mod)

    def set_mode(self, value: int, force: bool = False) -> bool:
        """True dacă tastatura are acum efectul `value`. force=True rescrie efectul chiar dacă e
        același (tastatura își reîncarcă atunci setările, inclusiv paleta)."""
        if not 0 <= value <= MAX_MODE:
            raise ValueError(f"efect invalid: {value}")
        page = self._stable(protocol.SETTINGS_PAGE)
        if page[protocol.MODE_OFFSET] == value and not force:
            return True
        order = ["profile", "page"] if self.method != "page" else ["page"]
        for method in order:
            ok = self._via_profile(page, value) if method == "profile" else self._via_page(value)
            self.writes += 1
            if ok:
                if self.method != method:
                    log.info("Tastatura acceptă scrierea efectului prin metoda %s", method)
                self.method = method
                return True
            if method == "profile":
                # profilul nu a mers: poate a schimbat efectul, dar a stricat restul paginii -> oprim
                now = self._stable(protocol.SETTINGS_PAGE)
                if now[protocol.MODE_OFFSET] == value:
                    raise OSError("efectul s-a schimbat, dar restul profilului diferă; opresc scrierile")
                page = now
        return False

    # ------------------------------------------------------------ paleta

    def read_palette(self) -> bytes:
        return self._stable(PALETTE_PAGE)

    def write_palette(self, table: bytes) -> bool:
        """Scrie paleta (1024 bytes la 0xB800) și verifică prin recitire; nu scrie dacă e deja la fel."""
        if len(table) != PALETTE_LEN:
            raise ValueError("paleta are 1024 bytes")
        if self._stable(PALETTE_PAGE) == table:
            return True
        self.link.data.set_feature(protocol.write_packet(PALETTE_PAGE, table))
        self.writes += 1
        time.sleep(0.25)
        return self._stable(PALETTE_PAGE) == table

    def close(self) -> None:
        self.link.close()


# ---------------------------------------------------------------------- paleta (culorile efectelor)

PALETTE_PAGE = 0xB8
PALETTE_LEN = 1024
GROUP = 21  # 7 culori x 3 bytes pe efect


def palette_groups(table: bytes) -> int:
    n = 0
    while (n + 1) * GROUP <= len(table) and any(table[n * GROUP:(n + 1) * GROUP]):
        n += 1
    return n


# Paleta din fabrică (citită de pe tastatura utilizatorului înainte de orice scriere):
# fiecare efect are aceleași 7 culori.
FACTORY_GROUP = bytes.fromhex("ff0000" "ffff00" "00ff00" "00ffff" "0000ff" "ff00ff" "ffffff")


def is_uniform(table: bytes, groups: int) -> bool:
    """Toate culorile din palete sunt la fel (adică paleta a rămas de la AI Colors, nu e a ta)."""
    if groups == 0:
        return False
    first = table[:3]
    return table[:groups * GROUP] == first * (groups * 7)


def factory_palette(table: bytes, groups: int) -> bytes:
    out = bytearray(table)
    for g in range(groups):
        out[g * GROUP:(g + 1) * GROUP] = FACTORY_GROUP
    return bytes(out)


def original_palette_path():
    from .config import user_config_path

    return user_config_path().parent / "kb_original_palette.bin"


def load_original_palette(current: bytes) -> bytes:
    """Paleta „ta”: salvată o singură dată și refolosită, ca o paletă rămasă de la o închidere
    forțată (ex. toată roșie) să nu fie luată drept a ta. Fără fișier și cu paleta uniformă:
    paleta din fabrică."""
    path = original_palette_path()
    try:
        saved = path.read_bytes()
        if len(saved) == PALETTE_LEN:
            return saved
    except OSError:
        pass
    groups = palette_groups(current)
    original = factory_palette(current, groups) if is_uniform(current, groups) else current
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(original)
    except OSError:
        pass
    return original


def fill_palette(table: bytes, color, groups: int) -> bytes:
    """Toate cele 7 culori ale primelor `groups` efecte = `color`; restul tabelei neatins."""
    out = bytearray(table)
    rgb = bytes(int(c) & 0xFF for c in color)
    for g in range(groups):
        out[g * GROUP:(g + 1) * GROUP] = rgb * 7
    return bytes(out)
