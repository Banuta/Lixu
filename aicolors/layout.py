"""Tastele tastaturii (layout 68%), extrase din secțiunea [KBKEY] a Cfg.ini original.

Fiecare linie K<n> din Cfg.ini are forma:
    x1,y1,x2,y2, tip, VK, 0, LED, RGBTAB
  * LED    – indexul în cadrul live (col * 6 + rând), folosit de modul Music
  * RGBTAB – indexul în tabela de culori salvată (rând * 21 + col)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List


@dataclass(frozen=True)
class Key:
    name: str
    vk: int
    led: int
    rgbtab: int


KEYS: List[Key] = [
    Key('Esc', 0x1B, 1, 21),
    Key('Home', 0x24, 85, 35),
    Key('1', 0x31, 7, 22),
    Key('2', 0x32, 13, 23),
    Key('3', 0x33, 19, 24),
    Key('4', 0x34, 25, 25),
    Key('5', 0x35, 31, 26),
    Key('6', 0x36, 37, 27),
    Key('7', 0x37, 43, 28),
    Key('8', 0x38, 49, 29),
    Key('9', 0x39, 55, 30),
    Key('0', 0x30, 61, 31),
    Key('-', 0xBD, 67, 32),
    Key('=', 0xBB, 73, 33),
    Key('Backspace', 0x08, 79, 34),
    Key('PgUp', 0x21, 87, 77),
    Key('Tab', 0x09, 2, 42),
    Key('Q', 0x51, 8, 43),
    Key('W', 0x57, 14, 44),
    Key('E', 0x45, 20, 45),
    Key('R', 0x52, 26, 46),
    Key('T', 0x54, 32, 47),
    Key('Y', 0x59, 38, 48),
    Key('U', 0x55, 44, 49),
    Key('I', 0x49, 50, 50),
    Key('O', 0x4F, 56, 51),
    Key('P', 0x50, 62, 52),
    Key('[', 0xDB, 68, 53),
    Key(']', 0xDD, 74, 54),
    Key('\\', 0xDC, 80, 55),
    Key('Delete', 0x2E, 86, 56),
    Key('PgDn', 0x22, 88, 98),
    Key('CapsLock', 0x14, 3, 63),
    Key('A', 0x41, 9, 64),
    Key('S', 0x53, 15, 65),
    Key('D', 0x44, 21, 66),
    Key('F', 0x46, 27, 67),
    Key('G', 0x47, 33, 68),
    Key('H', 0x48, 39, 69),
    Key('J', 0x4A, 45, 70),
    Key('K', 0x4B, 51, 71),
    Key('L', 0x4C, 57, 72),
    Key(';', 0xBA, 63, 73),
    Key("'", 0xDE, 69, 74),
    Key('Enter', 0x0D, 81, 76),
    Key('LShift', 0xA0, 4, 84),
    Key('Z', 0x5A, 10, 86),
    Key('X', 0x58, 16, 87),
    Key('C', 0x43, 22, 88),
    Key('V', 0x56, 28, 89),
    Key('B', 0x42, 34, 90),
    Key('N', 0x4E, 40, 91),
    Key('M', 0x4D, 46, 92),
    Key(',', 0xBC, 52, 93),
    Key('.', 0xBE, 58, 94),
    Key('/', 0xBF, 64, 95),
    Key('RShift', 0xA1, 70, 96),
    Key('Up', 0x26, 82, 97),
    Key('LCtrl', 0xA2, 5, 105),
    Key('LWin', 0x5B, 11, 106),
    Key('LAlt', 0xA4, 17, 107),
    Key('Space', 0x20, 35, 110),
    Key('RAlt', 0xA5, 53, 113),
    Key('Fn', 0xFA, 59, 114),
    Key('RCtrl', 0xA3, 65, 115),
    Key('Left', 0x25, 71, 116),
    Key('Down', 0x28, 83, 118),
    Key('Right', 0x27, 89, 119),
]

BY_NAME: Dict[str, Key] = {k.name.upper(): k for k in KEYS}

# Grupuri folosite de efecte.
NUMBER_ROW = list("1234567890")
QWERTY_ROW = list("QWERTYUIOP")
HOME_ROW = list("ASDFGHJKL") + [";"]
BOTTOM_ROW = list("ZXCVBNM") + [",", ".", "/"]
MOVEMENT = ["W", "A", "S", "D", "Space", "LCtrl", "LShift"]
LEFT_COLUMN = ["Esc", "Tab", "CapsLock", "LShift", "LCtrl"]
RIGHT_COLUMN = ["Home", "Delete", "PgUp", "PgDn", "Right"]
ARROWS = ["Up", "Down", "Left", "Right"]


def key(name: str) -> Key:
    try:
        return BY_NAME[name.upper()]
    except KeyError:
        raise KeyError(f"tastă necunoscută: {name}") from None


def leds(names: Iterable[str]) -> List[int]:
    return [key(n).led for n in names]


ALL_LEDS: List[int] = [k.led for k in KEYS]
