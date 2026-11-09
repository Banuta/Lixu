"""Protocolul HID al tastaturii ZENKABEAT (OEM "916RGB"), aflat prin reverse
engineering pe OemDrv.exe (vezi docs/PROTOCOL.md).

Tastatura expune mai multe colecții HID pe vendor usage page 0xFF00 / usage 1,
pe care aplicația originală le deosebește după FeatureReportByteLength:

  * 0x408 (1032)  -> "hDevice": blocuri mari de date (profiluri, macro-uri, matrice)
  * 6             -> "hCmd":    comenzi scurte (report ID 5)
  * 0x17E (382)   -> "hMusic":  cadre LED în timp real (report ID 8)

Pentru efecte live (CS2) folosim doar canalul "hMusic": un cadru cu culoarea
fiecăruia dintre cele 126 de LED-uri, exact cum face modul "Music" din aplicația
originală. Nu scrie nimic în memoria flash a tastaturii.
"""

from __future__ import annotations

from typing import Iterable, Sequence, Tuple

RGB = Tuple[int, int, int]

VENDOR_ID = 0x05AC
PRODUCT_ID = 0x024F

VENDOR_USAGE_PAGE = 0xFF00
VENDOR_USAGE = 0x0001

FEATURE_LEN_DATA = 0x408
FEATURE_LEN_CMD = 6
FEATURE_LEN_STREAM = 0x17E

# Matricea de LED-uri: 21 de coloane x 6 rânduri, index = col * 6 + rând.
LED_ROWS = 6
LED_COLS = 21
LED_COUNT = LED_ROWS * LED_COLS  # 126
FRAME_DATA_LEN = LED_COUNT * 3  # 378

# Comenzi pe interfețele „hCmd” (report 5) și „hDevice” (report 6), din
# CDrv916RGB::GetLedRgbTab (0x41b210) și SetLedRgbTab (0x41b160):
#   citire: SetFeature(hCmd, 05 88 <tabel> 00 00 00 00), apoi GetFeature(hDevice, 06 ..., 1032)
#   scriere: SetFeature(hDevice, 06 08 <tabel> 00 40 00 00 00 + 1024 bytes)
CMD_REPORT_ID = 0x05
DATA_REPORT_ID = 0x06
CMD_READ = 0x88
CMD_WRITE = 0x08
TABLE_RGB = 0xB8


# Al doilea byte e o ADRESĂ din memoria tastaturii (în pași de 256 bytes).
# Sub 0xB000 e codul tastaturii (firmware): o scriere acolo ar strica tastatura.
WRITE_MIN_PAGE = 0xB0


def read_request(table: int) -> bytes:
    return bytes((CMD_REPORT_ID, CMD_READ, table, 0, 0, 0, 0))


# Efectul activ (aflat cu `kbtest learn`): un byte la 0xB60D, scris de tastatură la fiecare Fn.
SETTINGS_PAGE = 0xB6
MODE_OFFSET = 0x0D
PROFILE_OP = 0x03     # SetProfile din aplicația originală: 06 03 <pagină> 00.. + 254 bytes
PROFILE_LEN = 254


def profile_write_packet(page: int, data: bytes) -> bytes:
    if not WRITE_MIN_PAGE <= page <= 0xFC:
        raise ValueError(f"scriere refuzată la adresa {page << 8:#06x}: e zona de cod a tastaturii")
    if len(data) != PROFILE_LEN:
        raise ValueError(f"profilul are exact {PROFILE_LEN} bytes")
    return (bytes((DATA_REPORT_ID, PROFILE_OP, page, 0, 0, 0, 0, 0)) + bytes(data)).ljust(FEATURE_LEN_DATA, b"\x00")


def write_packet(page: int, data: bytes, op: int = CMD_WRITE) -> bytes:
    """Pachet de scriere 1024 bytes la adresa page*256. Refuză zona de cod."""
    if not WRITE_MIN_PAGE <= page <= 0xFC:
        raise ValueError(f"scriere refuzată la adresa {page << 8:#06x}: e zona de cod a tastaturii")
    if len(data) != 1024:
        raise ValueError("se scriu exact 1024 bytes")
    return bytes((DATA_REPORT_ID, op, page, 0x00, 0x40, 0, 0, 0)) + bytes(data)


STREAM_REPORT_ID = 0x08
# Header-ul exact folosit de CDrv916RGB::SendMusicData (0x41b440).
STREAM_HEADER = bytes((STREAM_REPORT_ID, 0x0A, 0x7A, 0x01))

# Ordinea canalelor în cadru: pentru culoarea (R, G, B), byte-ul canalului i
# ajunge la offsetul led*3 + order[i]. Echivalentul cheii RGBIndex din Cfg.ini
# (implicit 0,1,2).
DEFAULT_RGB_ORDER: Tuple[int, int, int] = (0, 1, 2)


def led_position(led: int) -> Tuple[int, int]:
    """Returnează (rând, coloană) pentru un index de LED."""
    if not 0 <= led < LED_COUNT:
        raise ValueError(f"index LED invalid: {led}")
    return led % LED_ROWS, led // LED_ROWS


def led_index(row: int, col: int) -> int:
    if not (0 <= row < LED_ROWS and 0 <= col < LED_COLS):
        raise ValueError(f"poziție invalidă: rând={row}, coloană={col}")
    return col * LED_ROWS + row


def parse_rgb_order(text: str) -> Tuple[int, int, int]:
    parts = tuple(int(p.strip()) for p in text.split(","))
    if len(parts) != 3 or sorted(parts) != [0, 1, 2]:
        raise ValueError("ordinea RGB trebuie să fie o permutare a lui 0,1,2 (ex. 0,1,2 sau 2,1,0)")
    return parts  # type: ignore[return-value]


def _clamp(v: float) -> int:
    v = int(round(v))
    return 0 if v < 0 else 255 if v > 255 else v


def encode_frame(colors: Sequence[RGB], order: Sequence[int] = DEFAULT_RGB_ORDER) -> bytes:
    """Transformă 126 de culori (R, G, B) în cei 378 de bytes ai cadrului."""
    if len(colors) != LED_COUNT:
        raise ValueError(f"cadrul trebuie să aibă {LED_COUNT} culori, are {len(colors)}")
    data = bytearray(FRAME_DATA_LEN)
    for led, color in enumerate(colors):
        base = led * 3
        for channel in range(3):
            data[base + order[channel]] = _clamp(color[channel])
    return bytes(data)


def build_stream_packet(colors: Sequence[RGB], order: Sequence[int] = DEFAULT_RGB_ORDER) -> bytes:
    """Feature report complet (382 bytes) pentru canalul de cadre LED."""
    packet = STREAM_HEADER + encode_frame(colors, order)
    return packet.ljust(FEATURE_LEN_STREAM, b"\x00")


def solid_frame(color: RGB) -> list:
    return [tuple(color) for _ in range(LED_COUNT)]


def hexdump(data: Iterable[int], width: int = 16) -> str:
    data = bytes(data)
    lines = []
    for off in range(0, len(data), width):
        chunk = data[off : off + width]
        lines.append(f"{off:04x}  " + " ".join(f"{b:02x}" for b in chunk))
    return "\n".join(lines)
