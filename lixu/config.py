"""Fișierul de configurare lixu.json.

Exemplu complet: lixu.example.json. Poate fi generat cu `lixu scan --write-config`.
Se caută, în ordine: --config, ./lixu.json, %APPDATA%/lixu/lixu.json (~/.config/lixu/lixu.json).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_DEVICES: List[Dict[str, Any]] = [{"type": "zenkabeat", "effect": "keyboard"}]


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 3000
    token: Optional[str] = None
    fps: float = 30.0
    idle_fps: float = 10.0
    brightness: float = 1.0
    devices: List[Dict[str, Any]] = field(default_factory=lambda: [dict(d) for d in DEFAULT_DEVICES])
    path: Optional[Path] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gsi": {"host": self.host, "port": self.port, "token": self.token},
            "fps": self.fps,
            "idle_fps": self.idle_fps,
            "brightness": self.brightness,
            "devices": self.devices,
        }


def user_config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "lixu" / "lixu.json"


def find_config(explicit: Optional[str] = None) -> Optional[Path]:
    if explicit:
        return Path(explicit)
    for p in (Path.cwd() / "lixu.json", user_config_path()):
        if p.is_file():
            return p
    return None


def from_dict(data: Dict[str, Any], path: Optional[Path] = None) -> Config:
    gsi = data.get("gsi", {})
    devices = [d for d in data.get("devices", DEFAULT_DEVICES) if d.get("enabled", True)]
    for d in devices:
        if "type" not in d:
            raise ValueError(f"dispozitiv fără \"type\" în config: {d}")
    return Config(
        host=gsi.get("host", "127.0.0.1"),
        port=int(gsi.get("port", 3000)),
        token=gsi.get("token"),
        fps=float(data.get("fps", 30.0)),
        idle_fps=float(data.get("idle_fps", 10.0)),
        brightness=float(data.get("brightness", 1.0)),
        devices=devices,
        path=path,
    )


def load(explicit: Optional[str] = None) -> Config:
    path = find_config(explicit)
    if path is None:
        return Config()
    with open(path, encoding="utf-8") as fh:
        return from_dict(json.load(fh), path)


def save(cfg: Config, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
