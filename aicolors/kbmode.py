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

    def set_mode(self, value: int) -> bool:
        """True dacă tastatura are acum efectul `value`."""
        if not 0 <= value <= MAX_MODE:
            raise ValueError(f"efect invalid: {value}")
        page = self._stable(protocol.SETTINGS_PAGE)
        if page[protocol.MODE_OFFSET] == value:
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

    def close(self) -> None:
        self.link.close()
