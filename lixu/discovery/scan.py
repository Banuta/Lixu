"""`lixu scan`: caută toate dispozitivele cu lumini, în paralel."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Tuple

from ..devices.base import Found

log = logging.getLogger(__name__)


def _sources(timeout: float, subnet: Optional[str], openrgb_host: str) -> Dict[str, Callable[[], List[Found]]]:
    from ..devices import govee, logitech, openrgb, tuya, wled, zenkabeat
    from . import motherboard

    return {
        "Tastatura ZENKABEAT": zenkabeat.discover,
        "Placa de bază": motherboard.discover,
        "Logitech (G HUB)": logitech.discover,
        "OpenRGB": lambda: openrgb.discover(openrgb_host),
        "WLED (ESP32)": lambda: wled.discover(timeout, subnet),
        "Govee (LAN)": lambda: govee.discover(timeout),
        "Tuya / Smart Life": lambda: tuya.discover(max(timeout, 4.0)),
    }


def scan(timeout: float = 2.5, subnet: Optional[str] = None,
         openrgb_host: str = "127.0.0.1") -> List[Tuple[str, List[Found], Optional[str]]]:
    sources = _sources(timeout, subnet, openrgb_host)
    results = []
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        futures = {name: pool.submit(fn) for name, fn in sources.items()}
        for name, fut in futures.items():
            try:
                results.append((name, fut.result(), None))
            except Exception as exc:
                log.debug("scan %s", name, exc_info=True)
                results.append((name, [], str(exc)))
    return results


def suggested_devices(results) -> List[dict]:
    """Config sugerat: tot ce se poate controla direct (plăcile de bază apar prin OpenRGB)."""
    return [{k: v for k, v in f.config.items() if v is not None}
            for _name, found, _err in results for f in found if f.controllable and f.config]


def format_results(results) -> str:
    lines = []
    for name, found, err in results:
        lines.append(f"== {name}")
        if err:
            lines.append(f"   eroare: {err}")
        elif not found:
            lines.append("   nimic găsit")
        for f in found:
            mark = "OK " if f.controllable else "-- "
            addr = f" [{f.address}]" if f.address else ""
            lines.append(f"   {mark}{f.name}{addr}  {f.details}")
            for note in f.notes:
                lines.append(f"        * {note}")
    return "\n".join(lines)
