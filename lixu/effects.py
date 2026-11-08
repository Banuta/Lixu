"""Transformă starea jocului într-un cadru de 126 de culori.

Straturi, de jos în sus:
  1. fundal în culoarea echipei (T portocaliu, CT albastru); în meniu: „respirație” mov
  2. WASD/Space/Ctrl/Shift mai luminoase
  3. viață pe rândul de cifre 1-0 (verde -> galben -> roșu), pulsează sub 25 HP
  4. armură pe coloana din stânga (Esc, Tab, Caps, LShift, LCtrl)
  5. muniție pe rândul de jos Z../ (alb, roșu clipitor când e goală)
  6. kill-uri în rundă pe coloana din dreapta (Home, Del, PgUp, PgDn, Right)
  7. bombă plantată: puls roșu tot mai rapid (40 s); defuzată/explodată: flash
  8. final de rundă: flash în culoarea echipei câștigătoare
  9. mort: tot gri închis
 10. flash (flashbang) și foc: amestec spre alb / portocaliu
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

from . import layout
from .gsi import GameState
from .protocol import LED_COUNT, RGB

T_COLOR: RGB = (255, 110, 0)
CT_COLOR: RGB = (0, 110, 255)
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

BOMB_TIMER = 40.0


def scale(c: RGB, k: float) -> RGB:
    return (c[0] * k, c[1] * k, c[2] * k)


def mix(a: RGB, b: RGB, t: float) -> RGB:
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def team_color(team: str) -> RGB:
    return T_COLOR if team == "T" else CT_COLOR if team == "CT" else IDLE_COLOR


def health_color(hp: int) -> RGB:
    if hp >= 50:
        return mix((255, 255, 0), (0, 255, 0), (hp - 50) / 50)
    return mix((255, 0, 0), (255, 255, 0), hp / 50)


def pulse(t: float, hz: float) -> float:
    """0..1 sinusoidal."""
    return 0.5 + 0.5 * math.sin(t * hz * 2 * math.pi)


class Frame:
    def __init__(self, fill: RGB = OFF):
        self.colors: List[RGB] = [fill] * LED_COUNT

    def set(self, names: Sequence[str], color: RGB) -> None:
        for led in layout.leds(names):
            self.colors[led] = color

    def fill(self, color: RGB) -> None:
        for led in layout.ALL_LEDS:
            self.colors[led] = color

    def blend_all(self, color: RGB, amount: float) -> None:
        for led in layout.ALL_LEDS:
            self.colors[led] = mix(self.colors[led], color, amount)

    def bar(self, names: Sequence[str], fraction: float, color: RGB, empty: RGB = OFF) -> None:
        """Bară de progres pe o listă de taste; ultima tastă parțială e estompată."""
        fraction = max(0.0, min(1.0, fraction))
        lit = fraction * len(names)
        for i, name in enumerate(names):
            amount = max(0.0, min(1.0, lit - i))
            led = layout.key(name).led
            self.colors[led] = mix(empty, color, amount)

    def as_rgb(self) -> List[RGB]:
        return [tuple(int(round(max(0, min(255, v)))) for v in c) for c in self.colors]  # type: ignore[misc]


class Renderer:
    def __init__(self, brightness: float = 1.0, base_level: float = 0.15):
        self.brightness = brightness
        self.base_level = base_level

    def render(self, st: Optional[GameState], now: float) -> List[RGB]:
        f = Frame()
        if st is None or not st.in_game:
            f.fill(scale(IDLE_COLOR, 0.15 + 0.35 * pulse(now, 0.25)))
            return self._finish(f)

        tc = team_color(st.team)
        f.fill(scale(tc, self.base_level))
        f.set(layout.MOVEMENT, scale(tc, 0.6))

        if not st.alive:
            f.fill(DEAD_COLOR)
        else:
            self._health(f, st, now)
            self._armor(f, st)
            self._ammo(f, st, now)
            self._kills(f, st)

        self._bomb(f, st, now)
        self._round_over(f, st, now)

        if st.alive and st.burning:
            for name in layout.BOTTOM_ROW + ["LCtrl", "LWin", "LAlt", "Space", "RAlt", "Fn", "RCtrl"]:
                led = layout.key(name).led
                f.colors[led] = mix(f.colors[led], FIRE_COLOR,
                                    (st.burning / 255) * (0.6 + 0.4 * pulse(now, 3)))
        if st.alive and st.flashed:
            f.blend_all(WHITE, st.flashed / 255)
        return self._finish(f)

    def _health(self, f: Frame, st: GameState, now: float) -> None:
        color = health_color(st.health)
        if st.health <= 25:
            color = scale(color, 0.35 + 0.65 * pulse(now, 2.5))
        f.bar(layout.NUMBER_ROW, st.health / 100, color, empty=(15, 0, 0))

    def _armor(self, f: Frame, st: GameState) -> None:
        color = HELMET_COLOR if st.helmet else ARMOR_COLOR
        f.bar(list(reversed(layout.LEFT_COLUMN)), st.armor / 100, color, empty=OFF)

    def _ammo(self, f: Frame, st: GameState, now: float) -> None:
        w = st.active_weapon
        if w is None or w.ammo_clip_max <= 0 or w.ammo_clip < 0:
            f.set(layout.BOTTOM_ROW, OFF)
            return
        if w.ammo_clip == 0 or w.state == "reloading":
            f.set(layout.BOTTOM_ROW, scale((255, 0, 0), pulse(now, 4)))
            return
        frac = w.ammo_clip / w.ammo_clip_max
        color = AMMO_COLOR if frac > 0.25 else (255, 150, 0)
        f.bar(layout.BOTTOM_ROW, frac, color)

    def _kills(self, f: Frame, st: GameState) -> None:
        for i, name in enumerate(layout.RIGHT_COLUMN):
            if i < st.round_killhs:
                f.set([name], HS_COLOR)
            elif i < st.round_kills:
                f.set([name], KILL_COLOR)
            else:
                f.set([name], OFF)

    def _bomb(self, f: Frame, st: GameState, now: float) -> None:
        if st.bomb == "planted" and st.bomb_planted_at is not None:
            elapsed = now - st.bomb_planted_at
            remaining = max(0.0, BOMB_TIMER - elapsed)
            # 1 Hz la plantare -> ~8 Hz în ultimele secunde
            hz = 1.0 + 7.0 * (1 - remaining / BOMB_TIMER) ** 2
            amount = pulse(elapsed, hz)
            for led in layout.ALL_LEDS:
                f.colors[led] = mix(f.colors[led], BOMB_COLOR, 0.25 + 0.6 * amount)
        elif st.bomb in ("defused", "exploded") and st.bomb_ended_at is not None:
            age = now - st.bomb_ended_at
            if age < 3:
                color = CT_COLOR if st.bomb == "defused" else (255, 200, 120)
                f.blend_all(color, 1 - age / 3)

    def _round_over(self, f: Frame, st: GameState, now: float) -> None:
        if st.round_phase != "over" or st.round_over_at is None or not st.win_team:
            return
        age = now - st.round_over_at
        if age < 4:
            f.blend_all(team_color(st.win_team), 0.4 + 0.5 * pulse(age, 1.5))

    def _finish(self, f: Frame) -> List[RGB]:
        if self.brightness != 1.0:
            f.colors = [scale(c, self.brightness) for c in f.colors]
        return f.as_rgb()
