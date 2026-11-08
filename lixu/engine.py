"""Motorul: citește starea CS2, calculează culorile și le trimite la dispozitive.

Gândit să nu fure FPS din joc:
  * procesul rulează cu prioritate „below normal”, deci CS2 are mereu întâietate
  * când nu e nicio animație, doarme până vin date noi de la CS2 (plus un
    keepalive rar), deci aproape 0% CPU
  * trimite doar când se schimbă culorile; dispozitivele lente (Govee) au limită de rată
  * fără interfață grafică; rețeaua e UDP (WLED, Govee) sau un socket TCP deschis o dată
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from . import effects
from .devices import Device, create_device
from .effects import Renderer, scale, to_rgb
from .gsi import GameState, StateStore
from .protocol import LED_COUNT, RGB

log = logging.getLogger(__name__)


def lower_priority() -> None:
    try:
        if sys.platform == "win32":
            import ctypes

            BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
            kernel32 = ctypes.windll.kernel32
            kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS)
        else:
            os.nice(5)
    except (OSError, AttributeError):
        pass


@dataclass
class Output:
    entry: Dict[str, Any]
    device: Optional[Device] = None
    last: Optional[List[RGB]] = None
    last_sent: float = 0.0
    next_retry: float = 0.0
    errors: int = 0

    @property
    def effect(self) -> str:
        return self.entry.get("effect") or ("keyboard" if self.entry.get("type") == "zenkabeat" else "ambient")

    @property
    def label(self) -> str:
        return self.device.name if self.device else self.entry.get("name") or self.entry.get("type", "?")


class Engine:
    def __init__(self, entries: Sequence[Dict[str, Any]], store: StateStore, fps: float = 30.0,
                 idle_fps: float = 10.0, brightness: float = 1.0, dry_run: bool = False,
                 preview: bool = False, retry_after: float = 5.0):
        self.outputs = [Output(dict(e)) for e in entries]
        self.store = store
        self.fps = max(1.0, fps)
        self.idle_fps = max(1.0, idle_fps)
        self.brightness = brightness
        self.dry_run = dry_run
        self.preview = preview
        self.retry_after = retry_after
        self.keyboard = Renderer()
        self.stop_event = threading.Event()
        self.frames = 0

    # ------------------------------------------------------------ dispozitive

    def _ensure(self, out: Output, now: float) -> bool:
        if out.device is not None:
            return True
        if now < out.next_retry:
            return False
        try:
            out.device = create_device(out.entry, dry_run=self.dry_run, preview=self.preview)
            log.info("Conectat: %s (%d LED-uri, efect %s)", out.device.name, out.device.led_count, out.effect)
            out.errors = 0
            return True
        except Exception as exc:  # orice dispozitiv stricat nu trebuie să oprească restul
            out.errors += 1
            delay = min(60.0, self.retry_after * out.errors)
            if out.errors <= 3 or out.errors % 10 == 0:
                log.warning("%s: %s (reîncerc în %.0f s)", out.label, exc, delay)
            out.next_retry = now + delay
            return False

    def close(self) -> None:
        for out in self.outputs:
            if out.device is not None:
                try:
                    out.device.close()
                except Exception:
                    pass
                out.device = None

    # ------------------------------------------------------------ randare

    def frame_for(self, out: Output, st: Optional[GameState], now: float) -> List[RGB]:
        dev = out.device
        assert dev is not None
        if out.effect == "keyboard" and dev.led_count == LED_COUNT:
            colors = self.keyboard.render(st, now)
        else:
            colors = dev.map_strip(effects.strip(st, now, dev.strip_length, out.effect))
        k = self.brightness * float(out.entry.get("brightness", 1.0))
        if k != 1.0:
            colors = [to_rgb(scale(c, k)) for c in colors]
        return colors

    def tick(self, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        st = self.store.get() if self.store.updates else None
        for out in self.outputs:
            if not self._ensure(out, now):
                continue
            dev = out.device
            assert dev is not None
            since = now - out.last_sent
            if since < dev.min_interval:
                continue
            try:
                frame = self.frame_for(out, st, now)
                if frame == out.last and since < dev.keepalive:
                    continue
                dev.send(frame)
                out.last, out.last_sent = frame, now
                self.frames += 1
            except ValueError as exc:  # efect greșit în config
                log.error("%s: %s", out.label, exc)
                out.next_retry = now + 3600
                dev.close()
                out.device = None
            except Exception as exc:
                log.warning("%s nu mai răspunde (%s); îl redeschid.", out.label, exc)
                try:
                    dev.close()
                except Exception:
                    pass
                out.device = None
                out.next_retry = now + 1.0

    def next_delay(self, now: float) -> float:
        st = self.store.get() if self.store.updates else None
        if effects.is_animating(st, now):
            return 1.0 / (self.fps if st is not None and st.in_game else self.idle_fps)
        keepalives = [o.device.keepalive for o in self.outputs if o.device is not None] or [1.0]
        return max(0.05, min(keepalives))

    def run(self) -> None:
        lower_priority()
        try:
            while not self.stop_event.is_set():
                start = time.time()
                self.tick(start)
                delay = self.next_delay(start) - (time.time() - start)
                if delay > 0 and self.store.changed.wait(delay):
                    self.store.changed.clear()
        finally:
            self.close()

    def stop(self) -> None:
        self.stop_event.set()
        self.store.changed.set()
