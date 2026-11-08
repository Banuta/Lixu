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
    colors: Dict[str, str] = field(default_factory=dict)
    peripherals: Dict[str, Any] = field(default_factory=lambda: {"enabled": True, "poll_seconds": 60})
    ui_port: int = 3001
    path: Optional[Path] = None

    @property
    def active_devices(self) -> List[Dict[str, Any]]:
        return [d for d in self.devices if d.get("enabled", True)]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gsi": {"host": self.host, "port": self.port, "token": self.token},
            "fps": self.fps,
            "idle_fps": self.idle_fps,
            "brightness": self.brightness,
            "colors": self.colors,
            "peripherals": self.peripherals,
            "ui_port": self.ui_port,
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
    devices = [dict(d) for d in data.get("devices", DEFAULT_DEVICES)]
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
        colors=dict(data.get("colors") or {}),
        peripherals=dict(data.get("peripherals") or {"enabled": True, "poll_seconds": 60}),
        ui_port=int(data.get("ui_port", 3001)),
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
