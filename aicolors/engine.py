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
from dataclasses import dataclass, field
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
    last: Optional[List[RGB]] = None          # ultimul cadru trimis efectiv
    last_sent: float = 0.0
    submitted: Optional[List[RGB]] = None     # ultimul cadru predat firului dispozitivului
    submitted_at: float = 0.0
    next_retry: float = 0.0
    errors: int = 0
    error: str = ""
    identify_until: float = 0.0
    # firul propriu al dispozitivului: un dispozitiv lent nu blochează restul
    lock: threading.Lock = field(default_factory=threading.Lock)
    wake: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None
    pending: Optional[List[RGB]] = None
    connecting: bool = False
    closed: bool = False

    @property
    def effect(self) -> str:
        return self.entry.get("effect") or ("keyboard" if self.entry.get("type") == "zenkabeat" else "ambient")

    @property
    def label(self) -> str:
        dev = self.device
        return dev.name if dev else self.entry.get("name") or self.entry.get("type", "?")


class Engine:
    """workers=True (aplicația): fiecare dispozitiv are firul lui pentru conectare și trimitere,
    deci un dispozitiv care nu răspunde nu blochează nici interfața, nici celelalte lumini.
    workers=False (teste, comenzi simple): totul pe firul apelantului."""

    def __init__(self, entries: Sequence[Dict[str, Any]], store: StateStore, fps: float = 30.0,
                 idle_fps: float = 10.0, brightness: float = 1.0, dry_run: bool = False,
                 preview: bool = False, retry_after: float = 5.0, workers: bool = False):
        self.lock = threading.RLock()
        self.outputs = [Output(dict(e)) for e in entries]
        self.store = store
        self.fps = max(1.0, fps)
        self.idle_fps = max(1.0, idle_fps)
        self.brightness = brightness
        self.dry_run = dry_run
        self.preview = preview
        self.retry_after = retry_after
        self.workers = workers
        self.keyboard = Renderer()
        self.stop_event = threading.Event()
        self.frames = 0
        self.paused = False

    # ------------------------------------------------------------ conectare și trimitere

    def _connect(self, out: Output) -> None:
        try:
            dev = create_device(out.entry, dry_run=self.dry_run, preview=self.preview)
        except Exception as exc:  # orice dispozitiv stricat nu trebuie să oprească restul
            out.errors += 1
            out.error = str(exc)
            delay = min(60.0, self.retry_after * out.errors)
            if out.errors <= 3 or out.errors % 10 == 0:
                log.warning("%s: %s (reîncerc în %.0f s)", out.label, exc, delay)
            out.next_retry = time.time() + delay
            return
        with out.lock:
            if out.closed or self.paused:
                try:
                    dev.close()
                except Exception:
                    pass
                return
            out.device = dev
            out.errors, out.error = 0, ""
            out.submitted = None
        log.info("Conectat: %s (%d LED-uri, efect %s)", dev.name, dev.led_count, out.effect)
        self.store.changed.set()

    def _send(self, out: Output, frame: List[RGB]) -> None:
        with out.lock:
            dev = out.device
            if dev is None:
                return
            try:
                dev.send(frame)
                out.last, out.last_sent, out.error = frame, time.time(), ""
                self.frames += 1
                return
            except ValueError as exc:  # efect greșit în config
                log.error("%s: %s", out.label, exc)
                out.error = str(exc)
                out.next_retry = time.time() + 3600
            except Exception as exc:
                log.warning("%s nu mai răspunde (%s); îl redeschid.", out.label, exc)
                out.error = str(exc)
                out.next_retry = time.time() + 1.0
            self._close_locked(out)

    @staticmethod
    def _close_locked(out: Output) -> None:
        if out.device is not None:
            try:
                out.device.close()
            except Exception:
                pass
            out.device = None
            out.submitted = None

    def _close(self, out: Output) -> None:
        with out.lock:
            self._close_locked(out)

    def _worker(self, out: Output) -> None:
        try:
            while not out.closed and not self.stop_event.is_set():
                out.wake.wait(0.5)
                out.wake.clear()
                if out.closed or self.stop_event.is_set():
                    break
                if self.paused:
                    continue
                if out.device is None:
                    if out.connecting:
                        self._connect(out)
                        out.connecting = False
                    continue
                frame, out.pending = out.pending, None
                if frame is not None:
                    self._send(out, frame)
        finally:
            self._close(out)

    def _start_worker(self, out: Output) -> None:
        out.thread = threading.Thread(target=self._worker, args=(out,), daemon=True,
                                      name=f"dev-{out.entry.get('type')}")
        out.thread.start()

    def _stop_output(self, out: Output) -> None:
        out.closed = True
        out.wake.set()
        if out.thread is None:
            self._close(out)

    def close(self) -> None:
        with self.lock:
            outs = list(self.outputs)
        for out in outs:
            self._stop_output(out)
        for out in outs:
            if out.thread is not None:
                out.thread.join(5)

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
                    prev.submitted = None
                    dev = prev.device
                    if dev is not None and hasattr(dev, "modes"):
                        dev.modes = dict(e.get("modes") or getattr(dev, "DEFAULT_MODES", {}))
                    new_outputs.append(prev)
                else:
                    new_outputs.append(Output(e))
            removed = list(old.values())
            self.outputs = new_outputs
            if fps is not None:
                self.fps = max(1.0, fps)
            if idle_fps is not None:
                self.idle_fps = max(1.0, idle_fps)
            if brightness is not None:
                self.brightness = brightness
        for o in removed:
            self._stop_output(o)
        self.store.changed.set()

    @staticmethod
    def _identity(entry: Dict[str, Any]) -> tuple:
        """Câmpurile care cer reconectare când se schimbă."""
        keys = ("type", "host", "port", "id", "target", "zones", "match", "device_type", "index",
                "leds", "local_key", "version", "rgb_order", "dll", "hosts", "segments", "groups", "gradient",
                "backend", "all", "zone")
        return tuple(str(entry.get(k)) for k in keys)

    def keyboard_preview(self, value) -> dict:
        """Butonul „Încearcă” pentru tastatura ZENKABEAT în modul efecte."""
        for o in list(self.outputs):
            if getattr(o.device, "scene_based", False):
                with o.lock:
                    dev = o.device
                    if dev is None:
                        break
                    dev.preview(value)
                    if value is None:
                        o.submitted = None  # „Revino” reaplică situația curentă
                    return {"ok": True, "mode": dev.current, "original": dev.original}
        raise RuntimeError("tastatura ZENKABEAT nu e conectată în modul efecte")

    def identify(self, index: int) -> None:
        out = self.outputs[index]
        out.identify_until = time.time() + IDENTIFY_SECONDS
        out.next_retry = 0.0
        self.store.changed.set()

    # ------------------------------------------------------------ randare

    def frame_for(self, out: Output, st: Optional[GameState], now: float, dev: Optional[Device] = None) -> List[RGB]:
        dev = dev or out.device
        assert dev is not None
        if getattr(dev, "scene_based", False):
            return ["identify" if now < out.identify_until else effects.scene(st, now)]
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

    def set_paused(self, paused: bool) -> None:
        """Pauză: închide dispozitivele (revin la efectele lor) până la reluare."""
        self.paused = paused
        for out in list(self.outputs):
            if paused:
                self._close(out)
                out.last = None
            else:
                out.next_retry = 0.0
            out.wake.set()
        self.store.changed.set()

    def tick(self, now: Optional[float] = None) -> None:
        if self.paused:
            return
        now = time.time() if now is None else now
        st = self.store.get() if self.store.updates else None
        with self.lock:
            outs = list(self.outputs)
        for out in outs:
            if out.closed:
                continue
            if self.workers and out.thread is None:
                self._start_worker(out)
            self._tick_one(out, st, now)

    def _tick_one(self, out: Output, st: Optional[GameState], now: float) -> None:
        dev = out.device
        if dev is None:
            if now < out.next_retry or out.connecting:
                return
            if self.workers:
                out.connecting = True
                out.wake.set()
                return
            self._connect(out)
            dev = out.device
            if dev is None:
                return
        since = now - out.submitted_at
        if since < dev.min_interval:
            return
        try:
            frame = self.frame_for(out, st, now, dev)
        except ValueError as exc:  # efect greșit în config
            log.error("%s: %s", out.label, exc)
            out.error = str(exc)
            out.next_retry = now + 3600
            self._close(out)
            return
        if frame == out.submitted and since < dev.keepalive:
            return
        out.submitted, out.submitted_at = frame, now
        if self.workers:
            out.pending = frame
            out.wake.set()
        else:
            self._send(out, frame)

    def next_delay(self, now: float) -> float:
        if self.paused:
            return 1.0
        st = self.store.get() if self.store.updates else None
        outs = list(self.outputs)
        identifying = any(now < o.identify_until for o in outs)
        keepalives = [d.keepalive for d in (o.device for o in outs) if d is not None] or [1.0]
        if identifying:
            return 1.0 / 10
        if effects.is_animating(st, now):
            return 1.0 / (self.fps if st is not None and st.in_game else self.idle_fps)
        return max(0.05, min(min(keepalives), 1.0))

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
        """Fără blocări: interfața primește starea chiar dacă un dispozitiv e ocupat."""
        result = []
        for i, o in enumerate(list(self.outputs)):
            dev, last = o.device, o.last
            result.append({
                "index": i,
                "type": o.entry.get("type"),
                "name": o.label,
                "effect": o.effect,
                "connected": dev is not None,
                "leds": dev.led_count if dev else None,
                "error": o.error,
                "colors": [effects.rgb_to_hex(c) for c in (last or []) if isinstance(c, tuple)],
                "scene": last[0] if last and isinstance(last[0], str) else None,
                "mode": getattr(dev, "current", None),
                "original_mode": getattr(dev, "original", None),
            })
        return result
