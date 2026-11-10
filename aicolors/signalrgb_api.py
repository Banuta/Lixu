"""API-ul local SignalRGB (cere SignalRGB Pro): http://127.0.0.1:16038/api/v1

Folosit ca AI Colors să pornească singur efectul „AI Colors CS2” în SignalRGB și să pună
înapoi efectul tău la ieșire. Formatul (din biblioteca `signalrgb` de pe PyPI):
    GET   /api/v1/lighting                      -> data: {id, attributes: {name, enabled, global_brightness}}
    GET   /api/v1/lighting/effects              -> data: {items: [{id, attributes: {name}}]}
    POST  /api/v1/lighting/effects/{id}/apply
    PATCH /api/v1/lighting/enabled              {"enabled": bool}
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional, Tuple

DEFAULT_PORT = 16038
EFFECT_NAME = "AI Colors CS2"


class SignalRGBError(RuntimeError):
    pass


class SignalRGBApi:
    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT, timeout: float = 2.0):
        self.base = f"http://{host}:{port}/api/v1"
        self.timeout = timeout

    def _call(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 402, 403):
                raise SignalRGBError("API-ul SignalRGB cere SignalRGB Pro (și să fie activat)") from exc
            raise SignalRGBError(f"SignalRGB a răspuns {exc.code} la {path}") from exc
        except OSError as exc:
            raise SignalRGBError(f"SignalRGB nu răspunde pe {self.base} (e pornit?): {exc}") from exc
        try:
            return json.loads(text) if text.strip() else {}
        except ValueError:
            return {}

    def current(self) -> Tuple[Optional[str], Optional[str]]:
        """(id, nume) efectului activ."""
        data = (self._call("GET", "/lighting").get("data") or {})
        return data.get("id"), (data.get("attributes") or {}).get("name")

    def effects(self) -> List[Tuple[str, str]]:
        items = ((self._call("GET", "/lighting/effects").get("data") or {}).get("items") or [])
        return [(e.get("id"), (e.get("attributes") or {}).get("name", "")) for e in items if e.get("id")]

    def find(self, name: str = EFFECT_NAME) -> Optional[str]:
        for eid, ename in self.effects():
            if ename.strip().lower() == name.lower():
                return eid
        return None

    def apply(self, effect_id: str) -> None:
        self._call("POST", f"/lighting/effects/{urllib.parse.quote(effect_id, safe='')}/apply")

    def set_enabled(self, enabled: bool) -> None:
        self._call("PATCH", "/lighting/enabled", {"enabled": bool(enabled)})
