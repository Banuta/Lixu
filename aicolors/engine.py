"""Motorul: citește starea CS2, calculează culorile și le trimite la dispozitive.

Gândit să nu fure FPS din joc:
  * procesul rulează cu prioritate „below normal”, deci CS2 are mereu întâietate
  * când nu e nicio animație, doarme până vin date noi de la CS2 (plus un
    keepalive rar), deci aproape 0% CPU
  * trimite doar când se schimbă culorile; dispozitivele lente (Govee, Tuya) au limită de rată
  * interfața e o pagină web locală: cât timp e închisă, nu costă nimic
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

IDENTIFY_SECONDS = 3.2
IDENTIFY_COLORS: List[RGB] = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]


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
    error: str = ""
    identify_until: float = 0.0

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
        self.lock = threading.RLock()
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
            out.errors, out.error = 0, ""
            return True
        except Exception as exc:  # orice dispozitiv stricat nu trebuie să oprească restul
            out.errors += 1
            out.error = str(exc)
            delay = min(60.0, self.retry_after * out.errors)
            if out.errors <= 3 or out.errors % 10 == 0:
                log.warning("%s: %s (reîncerc în %.0f s)", out.label, exc, delay)
            out.next_retry = now + delay
            return False

    @staticmethod
    def _close(out: Output) -> None:
        if out.device is not None:
            try:
                out.device.close()
            except Exception:
                pass
            out.device = None

    def close(self) -> None:
        with self.lock:
            for out in self.outputs:
                self._close(out)

    def reconfigure(self, entries: Sequence[Dict[str, Any]], fps: Optional[float] = None,
                    idle_fps: Optional[float] = None, brightness: Optional[float] = None) -> None:
        """Aplică un config nou din mers. Dispozitivele neschimbate rămân conectate."""
        with self.lock:
            old = {self._identity(o.entry): o for o in self.outputs}
            new_outputs = []
            for e in entries:
                e = dict(e)
                prev = old.pop(self._identity(e), None)
                if prev is not None:
                    prev.entry = e  # efect/luminozitate noi, aceeași conexiune
                    prev.last = None
                    new_outputs.append(prev)
                else:
                    new_outputs.append(Output(e))
            for o in old.values():
                self._close(o)
            self.outputs = new_outputs
            if fps is not None:
                self.fps = max(1.0, fps)
            if idle_fps is not None:
                self.idle_fps = max(1.0, idle_fps)
            if brightness is not None:
                self.brightness = brightness
        self.store.changed.set()

    @staticmethod
    def _identity(entry: Dict[str, Any]) -> tuple:
        """Câmpurile care cer reconectare când se schimbă."""
        keys = ("type", "host", "port", "id", "target", "zones", "match", "device_type", "index",
                "leds", "local_key", "version", "rgb_order", "dll")
        return tuple(str(entry.get(k)) for k in keys)

    def identify(self, index: int) -> None:
        with self.lock:
            self.outputs[index].identify_until = time.time() + IDENTIFY_SECONDS
            self.outputs[index].next_retry = 0.0
        self.store.changed.set()

    # ------------------------------------------------------------ randare

    def frame_for(self, out: Output, st: Optional[GameState], now: float) -> List[RGB]:
        dev = out.device
        assert dev is not None
        if now < out.identify_until:
            phase = int((IDENTIFY_SECONDS - (out.identify_until - now)) / IDENTIFY_SECONDS * len(IDENTIFY_COLORS))
            return [IDENTIFY_COLORS[min(phase, len(IDENTIFY_COLORS) - 1)]] * dev.led_count
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
        with self.lock:
            for out in self.outputs:
                self._tick_one(out, st, now)

    def _tick_one(self, out: Output, st: Optional[GameState], now: float) -> None:
        if not self._ensure(out, now):
            return
        dev = out.device
        assert dev is not None
        since = now - out.last_sent
        if since < dev.min_interval:
            return
        try:
            frame = self.frame_for(out, st, now)
            if frame == out.last and since < dev.keepalive:
                return
            dev.send(frame)
            out.last, out.last_sent, out.error = frame, now, ""
            self.frames += 1
        except ValueError as exc:  # efect greșit în config
            log.error("%s: %s", out.label, exc)
            out.error = str(exc)
            out.next_retry = now + 3600
            self._close(out)
        except Exception as exc:
            log.warning("%s nu mai răspunde (%s); îl redeschid.", out.label, exc)
            out.error = str(exc)
            self._close(out)
            out.next_retry = now + 1.0

    def next_delay(self, now: float) -> float:
        st = self.store.get() if self.store.updates else None
        with self.lock:
            identifying = any(now < o.identify_until for o in self.outputs)
            keepalives = [o.device.keepalive for o in self.outputs if o.device is not None] or [1.0]
        if identifying:
            return 1.0 / 10
        if effects.is_animating(st, now):
            return 1.0 / (self.fps if st is not None and st.in_game else self.idle_fps)
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

    # ------------------------------------------------------------ pentru interfață

    def snapshot(self) -> List[Dict[str, Any]]:
        with self.lock:
            result = []
            for i, o in enumerate(self.outputs):
                result.append({
                    "index": i,
                    "type": o.entry.get("type"),
                    "name": o.label,
                    "effect": o.effect,
                    "connected": o.device is not None,
                    "leds": o.device.led_count if o.device else None,
                    "error": o.error,
                    "colors": [effects.rgb_to_hex(c) for c in (o.last or [])],
                })
            return result
