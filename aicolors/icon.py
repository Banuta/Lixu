"""Iconița AI Colors, desenată din cod (fără fișiere binare de mână).

Un cerc împărțit pe diagonală: portocaliu (T) și albastru (CT), cu margine netedă.
`write_ico(path)` scrie un .ico cu 16/24/32/48/256 px, folosit de bara de lângă ceas,
de interfață (favicon) și de AIColors.exe.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import List, Tuple

T = (255, 110, 0)
CT = (0, 110, 255)
SIZES = (16, 24, 32, 48, 256)


def pixels(size: int) -> List[Tuple[int, int, int, int]]:
    """RGBA, rând cu rând de sus în jos."""
    out = []
    c = (size - 1) / 2
    r = size / 2 - 0.5
    ring = max(1.0, size / 16)
    for y in range(size):
        for x in range(size):
            d = math.hypot(x - c, y - c)
            alpha = max(0.0, min(1.0, r - d + 0.5))
            if alpha <= 0:
                out.append((0, 0, 0, 0))
                continue
            base = T if (x - c) + (y - c) < 0 else CT
            # inel interior mai deschis + centru întunecat, ca să se vadă pe fundal închis și deschis
            if d > r - ring:
                color = tuple(min(255, int(v * 0.7 + 255 * 0.3)) for v in base)
            elif d < r * 0.38:
                color = (24, 26, 32)
            else:
                color = base
            out.append((color[0], color[1], color[2], int(alpha * 255)))
    return out


def _bmp_image(size: int) -> bytes:
    px = pixels(size)
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    rows = []
    for y in range(size - 1, -1, -1):  # BMP: de jos în sus, BGRA
        rows.append(b"".join(bytes((b, g, r, a)) for r, g, b, a in px[y * size:(y + 1) * size]))
    mask_row = ((size + 31) // 32) * 4
    return header + b"".join(rows) + b"\x00" * mask_row * size


def ico_bytes(sizes=SIZES) -> bytes:
    images = [_bmp_image(s) for s in sizes]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for s, img in zip(sizes, images):
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(img), offset)
        offset += len(img)
    return out + b"".join(images)


def write_ico(path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = ico_bytes()
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)
    return path


if __name__ == "__main__":  # python -m aicolors.icon  -> regenerează aicolors/ui/aicolors.ico
    print(write_ico(Path(__file__).resolve().parent / "ui" / "aicolors.ico"))
