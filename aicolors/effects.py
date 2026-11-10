"""Transformă starea jocului în culori. Aici e locul în care să te joci.

Două feluri de efecte:

* "keyboard" – efectul complet pe tastatura ZENKABEAT (fiecare tastă are rolul ei):
    rândul 1-0 = viață, coloana stângă = armură, Z../ = gloanțe,
    Home/Del/PgUp/PgDn/Right = kill-uri, WASD în culoarea echipei
* efecte de bandă (orice dispozitiv: WLED, Govee, mouse, căști, placă de bază):
    "ambient" – culoarea echipei + evenimente
    "health"  – bară de viață (pe un singur LED: culoare verde -> roșu)
    "armor"   – bară de armură
    "ammo"    – bară de gloanțe
    "team"    – doar culoarea echipei, fără evenimente

Peste toate se pun evenimentele globale (`apply_events`): bombă, flash, foc,
final de rundă, mort. Culorile sunt (R, G, B) cu valori 0-255.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence

from . import layout
from .gsi import GameState
from .protocol import LED_COUNT, RGB

# Culorile echipelor din CS2 (HUD/scoreboard: T #DE9B35, CT #5D79AE), mai saturate ca să arate bine
# pe LED-uri. Roșul rămâne rezervat pentru damage, bombă și viață mică.
T_COLOR: RGB = (255, 140, 0)
CT_COLOR: RGB = (0, 80, 255)
IDLE_COLOR: RGB = (120, 40, 255)
ARMOR_COLOR: RGB = (40, 160, 255)
HELMET_COLOR: RGB = (150, 220, 255)
AMMO_COLOR: RGB = (255, 255, 255)
KILL_COLOR: RGB = (255, 200, 0)
HS_COLOR: RGB = (255, 0, 80)
BOMB_COLOR: RGB = (255, 0, 0)
WHITE: RGB = (255, 255, 255)
FIRE_COLOR: RGB = (255, 80, 0)
DEAD_COLOR: RGB = (25, 25, 25)
OFF: RGB = (0, 0, 0)

# Numele din config / interfață -> variabila de mai sus
PALETTE_NAMES = {
    "t": "T_COLOR", "ct": "CT_COLOR", "idle": "IDLE_COLOR", "armor": "ARMOR_COLOR",
    "helmet": "HELMET_COLOR", "ammo": "AMMO_COLOR", "kill": "KILL_COLOR", "headshot": "HS_COLOR",
    "bomb": "BOMB_COLOR", "fire": "FIRE_COLOR", "dead": "DEAD_COLOR",
}


def rgb_to_hex(c: RGB) -> str:
    return "#%02x%02x%02x" % tuple(int(v) for v in c)


def hex_to_rgb(text: str) -> RGB:
    t = text.strip().lstrip("#")
    if len(t) != 6:
        raise ValueError(f"culoare invalidă: {text!r} (format #rrggbb)")
    return (int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))


def palette() -> Dict[str, str]:
    return {k: rgb_to_hex(globals()[v]) for k, v in PALETTE_NAMES.items()}


def apply_palette(colors: Dict[str, str]) -> None:
    """Schimbă culorile (din config sau din interfață) fără restart."""
    for key, value in (colors or {}).items():
        if key in PALETTE_NAMES:
            globals()[PALETTE_NAMES[key]] = hex_to_rgb(value)


BOMB_TIMER = 40.0
BOMB_END_FLASH = 3.0
ROUND_END_FLASH = 4.0
DAMAGE_FLASH = 0.45
KILL_FLASH = 0.35

# Evenimente (din config "events" / interfață, tab-ul Culori)
WIN_STYLES = ("blink", "flash", "pulse")
EVENTS: Dict[str, object] = {"damage": True, "kills": True, "win_t": "blink", "win_ct": "flash"}


def apply_event_settings(settings: Optional[Dict[str, object]]) -> None:
    for key, value in (settings or {}).items():
        if key in ("damage", "kills"):
            EVENTS[key] = bool(value)
        elif key in ("win_t", "win_ct") and value in WIN_STYLES:
            EVENTS[key] = value


def win_amount(style: object, age: float) -> float:
    """Cât de aprinsă e culoarea câștigătorilor la `age` secunde după final de rundă."""
    if style == "blink":    # pornit/oprit, de 3 ori pe secundă
        return 1.0 if int(age * 6) % 2 == 0 else 0.0
    if style == "flash":    # aprindere puternică, apoi stingere lină, la fiecare 0,8 s
        return max(0.0, 1.0 - (age % 0.8) / 0.5)
    return 0.4 + 0.5 * pulse(age, 1.5)


# ---------------------------------------------------------------- utilitare

def scale(c: RGB, k: float) -> RGB:
    return (c[0] * k, c[1] * k, c[2] * k)


def mix(a: RGB, b: RGB, t: float) -> RGB:
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def to_rgb(c: RGB) -> RGB:
    return tuple(int(round(0 if v < 0 else 255 if v > 255 else v)) for v in c)  # type: ignore[return-value]


def team_color(team: str) -> RGB:
    return T_COLOR if team == "T" else CT_COLOR if team == "CT" else IDLE_COLOR


def health_color(hp: int) -> RGB:
    if hp >= 50:
        return mix((255, 255, 0), (0, 255, 0), (hp - 50) / 50)
    return mix((255, 0, 0), (255, 255, 0), hp / 50)


def pulse(t: float, hz: float) -> float:
    """0..1 sinusoidal."""
    return 0.5 + 0.5 * math.sin(t * hz * 2 * math.pi)


def bar(n: int, fraction: float, color: RGB, empty: RGB = OFF) -> List[RGB]:
    """Bară de progres pe n LED-uri; ultimul LED parțial e estompat."""
    fraction = max(0.0, min(1.0, fraction))
    lit = fraction * n
    return [mix(empty, color, max(0.0, min(1.0, lit - i))) for i in range(n)]


def idle(now: float) -> RGB:
    return scale(IDLE_COLOR, 0.15 + 0.35 * pulse(now, 0.25))


def ammo_fraction(st: GameState) -> Optional[float]:
    w = st.active_weapon
    if w is None or w.ammo_clip_max <= 0 or w.ammo_clip < 0:
        return None
    return w.ammo_clip / w.ammo_clip_max


def ammo_empty(st: GameState) -> bool:
    w = st.active_weapon
    return w is not None and w.ammo_clip_max > 0 and (w.ammo_clip == 0 or w.state == "reloading")


# ------------------------------------------------- evenimente globale (straturi)

def apply_events(colors: List[RGB], st: GameState, now: float,
                 bottom: Optional[Sequence[int]] = None) -> List[RGB]:
    """Pune peste culori evenimentele care afectează toate LED-urile."""
    idx = range(len(colors))
    if st.bomb == "planted" and st.bomb_planted_at is not None:
        elapsed = now - st.bomb_planted_at
        remaining = max(0.0, BOMB_TIMER - elapsed)
        hz = 1.0 + 7.0 * (1 - remaining / BOMB_TIMER) ** 2  # 1 Hz -> ~8 Hz la final
        amount = 0.25 + 0.6 * pulse(elapsed, hz)
        colors = [mix(c, BOMB_COLOR, amount) for c in colors]
    elif st.bomb in ("defused", "exploded") and st.bomb_ended_at is not None:
        age = now - st.bomb_ended_at
        if age < BOMB_END_FLASH:
            color = CT_COLOR if st.bomb == "defused" else (255, 200, 120)
            colors = [mix(c, color, 1 - age / BOMB_END_FLASH) for c in colors]

    if st.round_phase == "over" and st.round_over_at is not None and st.win_team:
        age = now - st.round_over_at
        if age < ROUND_END_FLASH:
            style = EVENTS["win_t" if st.win_team == "T" else "win_ct"]
            amount = win_amount(style, age)
            target = team_color(st.win_team)
            if style == "blink":  # clipire: culoarea echipei sau stins
                colors = [target if amount else OFF for _ in colors]
            else:
                colors = [mix(c, target, amount) for c in colors]

    if EVENTS["damage"] and st.alive and st.damage_at is not None:
        age = now - st.damage_at
        if age < DAMAGE_FLASH:
            amount = min(1.0, 0.35 + st.damage / 50) * (1 - age / DAMAGE_FLASH)
            colors = [mix(c, (255, 0, 0), amount) for c in colors]
    if EVENTS["kills"] and st.kill_at is not None:
        age = now - st.kill_at
        if age < KILL_FLASH:
            colors = [mix(c, HS_COLOR if st.kill_hs else KILL_COLOR, 0.9 * (1 - age / KILL_FLASH)) for c in colors]

    if st.alive and st.burning:
        amount = (st.burning / 255) * (0.6 + 0.4 * pulse(now, 3))
        for i in (bottom if bottom is not None else idx):
            colors[i] = mix(colors[i], FIRE_COLOR, amount)
    if st.alive and st.flashed:
        colors = [mix(c, WHITE, st.flashed / 255) for c in colors]
    return colors


def is_animating(st: Optional[GameState], now: float) -> bool:
    """Are rost să redesenăm des? Dacă nu, motorul doarme până vin date noi."""
    if st is None or not st.in_game:
        return True  # „respirația” din meniu (motorul o rulează la idle_fps)
    if st.bomb == "planted":
        return True
    if st.bomb_ended_at is not None and now - st.bomb_ended_at < BOMB_END_FLASH:
        return True
    if st.round_over_at is not None and now - st.round_over_at < ROUND_END_FLASH:
        return True
    if st.damage_at is not None and now - st.damage_at < DAMAGE_FLASH:
        return True
    if st.kill_at is not None and now - st.kill_at < KILL_FLASH:
        return True
    if st.alive and (st.health <= 25 or st.burning or ammo_empty(st)):
        return True
    return False


# ------------------------------------------------- situații (tastatura fără canal live)

SCENES = ["menu", "ct", "t", "bomb", "dead", "low_hp", "win_ct", "win_t"]


def scene(st: Optional[GameState], now: float) -> str:
    """Situația din joc, pentru dispozitivele care pot doar schimba efectul (ZENKABEAT)."""
    if st is None or not st.in_game:
        return "menu"
    if st.round_phase == "over" and st.win_team and st.round_over_at is not None \
            and now - st.round_over_at < ROUND_END_FLASH:
        return "win_ct" if st.win_team == "CT" else "win_t"
    if st.bomb == "planted":
        return "bomb"
    if not st.alive:
        return "dead"
    if st.health <= 25:
        return "low_hp"
    return "ct" if st.team == "CT" else "t"


# ------------------------------------------------------- efecte de bandă

def _base(st: GameState) -> RGB:
    return DEAD_COLOR if not st.alive else team_color(st.team)


def strip_ambient(st: GameState, now: float, n: int) -> List[RGB]:
    color = _base(st)
    if st.alive and st.health <= 25:
        color = mix(color, (255, 0, 0), 0.6 * pulse(now, 2.5))
    return [color] * n


def strip_team(st: GameState, now: float, n: int) -> List[RGB]:
    return [team_color(st.team)] * n


def strip_health(st: GameState, now: float, n: int) -> List[RGB]:
    if not st.alive:
        return [DEAD_COLOR] * n
    color = health_color(st.health)
    if st.health <= 25:
        color = scale(color, 0.35 + 0.65 * pulse(now, 2.5))
    if n == 1:
        return [color]
    return bar(n, st.health / 100, color, empty=(15, 0, 0))


def strip_armor(st: GameState, now: float, n: int) -> List[RGB]:
    color = HELMET_COLOR if st.helmet else ARMOR_COLOR
    if n == 1:
        return [scale(color, st.armor / 100)]
    return bar(n, st.armor / 100, color)


def strip_ammo(st: GameState, now: float, n: int) -> List[RGB]:
    if ammo_empty(st):
        return [scale((255, 0, 0), pulse(now, 4))] * n
    frac = ammo_fraction(st)
    if frac is None:
        return [OFF] * n
    color = AMMO_COLOR if frac > 0.25 else (255, 150, 0)
    if n == 1:
        return [scale(color, 0.2 + 0.8 * frac)]
    return bar(n, frac, color)


def strip_bomb(st: GameState, now: float, n: int) -> List[RGB]:
    """Timpul rămas până explodează bomba, ca bară roșie; altfel culoarea echipei, slab."""
    if st.bomb == "planted" and st.bomb_planted_at is not None:
        remaining = max(0.0, BOMB_TIMER - (now - st.bomb_planted_at))
        return bar(n, remaining / BOMB_TIMER, BOMB_COLOR, empty=(20, 0, 0))
    return [scale(team_color(st.team), 0.3)] * n


StripEffect = Callable[[GameState, float, int], List[RGB]]

STRIP_EFFECTS: Dict[str, StripEffect] = {
    "ambient": strip_ambient,
    "team": strip_team,
    "health": strip_health,
    "armor": strip_armor,
    "ammo": strip_ammo,
    "bomb": strip_bomb,
}


def strip(st: Optional[GameState], now: float, n: int, effect: str = "ambient") -> List[RGB]:
    if n <= 0:
        return []
    if st is None or not st.in_game:
        return [to_rgb(idle(now))] * n
    try:
        fn = STRIP_EFFECTS[effect]
    except KeyError:
        raise ValueError(f"efect necunoscut: {effect!r} (alege din {', '.join(STRIP_EFFECTS)})") from None
    colors = fn(st, now, n)
    if effect == "bomb" and st.bomb == "planted":
        return [to_rgb(c) for c in colors]  # bara de timp rămâne curată, fără pulsul roșu peste ea
    if effect != "team":
        colors = apply_events(colors, st, now)
    return [to_rgb(c) for c in colors]


# ------------------------------------------------- efectul complet de tastatură

class Frame:
    def __init__(self, fill: RGB = OFF):
        self.colors: List[RGB] = [fill] * LED_COUNT

    def set(self, names: Sequence[str], color: RGB) -> None:
        for led in layout.leds(names):
            self.colors[led] = color

    def fill(self, color: RGB) -> None:
        for led in layout.ALL_LEDS:
            self.colors[led] = color

    def bar(self, names: Sequence[str], fraction: float, color: RGB, empty: RGB = OFF) -> None:
        for name, c in zip(names, bar(len(names), fraction, color, empty)):
            self.colors[layout.key(name).led] = c


BOTTOM_KEYS = layout.BOTTOM_ROW + ["LCtrl", "LWin", "LAlt", "Space", "RAlt", "Fn", "RCtrl"]


class Renderer:
    """Efectul "keyboard" pe toate cele 126 de LED-uri ale tastaturii."""

    def __init__(self, brightness: float = 1.0, base_level: float = 0.15):
        self.brightness = brightness
        self.base_level = base_level

    def render(self, st: Optional[GameState], now: float) -> List[RGB]:
        f = Frame()
        if st is None or not st.in_game:
            f.fill(idle(now))
            return self._finish(f.colors)

        tc = team_color(st.team)
        f.fill(scale(tc, self.base_level))
        f.set(layout.MOVEMENT, scale(tc, 0.6))
        if not st.alive:
            f.fill(DEAD_COLOR)
        else:
            self._health(f, st, now)
            f.bar(list(reversed(layout.LEFT_COLUMN)), st.armor / 100,
                  HELMET_COLOR if st.helmet else ARMOR_COLOR)
            self._ammo(f, st, now)
            self._kills(f, st)

        # evenimentele globale doar pe tastele care există; focul pe rândurile de jos
        leds = layout.ALL_LEDS
        sub = [f.colors[i] for i in leds]
        bottom = [leds.index(layout.key(n).led) for n in BOTTOM_KEYS]
        for led, c in zip(leds, apply_events(sub, st, now, bottom)):
            f.colors[led] = c
        return self._finish(f.colors)

    def _health(self, f: Frame, st: GameState, now: float) -> None:
        color = health_color(st.health)
        if st.health <= 25:
            color = scale(color, 0.35 + 0.65 * pulse(now, 2.5))
        f.bar(layout.NUMBER_ROW, st.health / 100, color, empty=(15, 0, 0))

    def _ammo(self, f: Frame, st: GameState, now: float) -> None:
        if ammo_empty(st):
            f.set(layout.BOTTOM_ROW, scale((255, 0, 0), pulse(now, 4)))
            return
        frac = ammo_fraction(st)
        if frac is None:
            f.set(layout.BOTTOM_ROW, OFF)
            return
        f.bar(layout.BOTTOM_ROW, frac, AMMO_COLOR if frac > 0.25 else (255, 150, 0))

    def _kills(self, f: Frame, st: GameState) -> None:
        for i, name in enumerate(layout.RIGHT_COLUMN):
            f.set([name], HS_COLOR if i < st.round_killhs else KILL_COLOR if i < st.round_kills else OFF)

    def _finish(self, colors: List[RGB]) -> List[RGB]:
        if self.brightness != 1.0:
            colors = [scale(c, self.brightness) for c in colors]
        return [to_rgb(c) for c in colors]
