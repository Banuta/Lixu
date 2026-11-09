"""Descarcă și pornește OpenRGB (pentru placa de bază și memoriile RGB).

Nu includem OpenRGB în AI Colors; îl descărcăm, la cerere, direct din sursele oficiale
(Codeberg, openrgb.org) în %APPDATA%/aicolors/OpenRGB și îl pornim ca administrator
(accesul la SMBus-ul plăcii cere drepturi de administrator) cu serverul SDK activ.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import socket
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from .config import user_config_path

log = logging.getLogger(__name__)

CODEBERG_API = "https://codeberg.org/api/v1/repos/OpenRGB/OpenRGB/releases?limit=10"
RELEASES_PAGE = "https://openrgb.org/releases.html"
ALLOWED_HOSTS = {"codeberg.org", "openrgb.org", "www.openrgb.org", "gitlab.com"}
SERVER_ARGS = "--server --startminimized"


def install_dir() -> Path:
    return user_config_path().parent / "OpenRGB"


def find_exe() -> Optional[Path]:
    candidates = [install_dir()]
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        if os.environ.get(env):
            candidates.append(Path(os.environ[env]) / "OpenRGB")
    for base in candidates:
        if base.is_dir():
            for exe in base.rglob("OpenRGB.exe"):
                return exe
    return None


def server_running(host: str = "127.0.0.1", port: int = 6742) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "AIColors"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _is_windows_zip(name: str) -> bool:
    n = name.lower()
    return n.endswith(".zip") and "windows" in n and "64" in n and "32" not in n.replace("x64", "")


def pick_from_codeberg(releases: list) -> Optional[str]:
    for rel in releases:
        if rel.get("draft"):
            continue
        for asset in rel.get("assets", []):
            if _is_windows_zip(asset.get("name", "")):
                return asset.get("browser_download_url")
    return None


def pick_from_page(html: str, base: str = RELEASES_PAGE) -> Optional[str]:
    for href in re.findall(r'href="([^"]+)"', html):
        if _is_windows_zip(href.rsplit("/", 1)[-1]):
            return urllib.parse.urljoin(base, href)
    return None


def latest_url() -> str:
    try:
        url = pick_from_codeberg(json.loads(_get(CODEBERG_API)))
        if url:
            return url
    except (OSError, ValueError) as exc:
        log.debug("Codeberg: %s", exc)
    try:
        url = pick_from_page(_get(RELEASES_PAGE).decode("utf-8", "replace"))
        if url:
            return url
    except OSError as exc:
        log.debug("openrgb.org: %s", exc)
    raise RuntimeError("Nu am găsit link-ul de descărcare. Descarcă manual de pe openrgb.org și dezarhivează în "
                       f"{install_dir()}")


def install() -> Path:
    url = latest_url()
    host = urllib.parse.urlparse(url).hostname or ""
    if host not in ALLOWED_HOSTS:
        raise RuntimeError(f"refuz să descarc de pe {host}")
    log.info("Descarc OpenRGB: %s", url)
    data = _get(url, timeout=120)
    target = install_dir()
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():  # fără căi absolute sau ../
            p = Path(member)
            if p.is_absolute() or ".." in p.parts:
                raise RuntimeError(f"arhivă suspectă: {member}")
        z.extractall(target)
    exe = find_exe()
    if exe is None:
        raise RuntimeError("arhiva descărcată nu conține OpenRGB.exe")
    return exe


def start(exe: Optional[Path] = None) -> None:
    """Pornește OpenRGB ca administrator, minimizat, cu serverul SDK activ (Windows va cere confirmare)."""
    exe = exe or find_exe()
    if exe is None:
        raise RuntimeError("OpenRGB nu e instalat; apasă întâi „Descarcă OpenRGB”")
    if sys.platform != "win32":
        raise RuntimeError("pornirea automată e doar pe Windows")
    import ctypes

    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(exe), SERVER_ARGS, str(exe.parent), 7)
    if rc <= 32:
        raise RuntimeError(f"Windows nu a pornit OpenRGB (cod {rc}); ai refuzat cererea de administrator?")


def status() -> dict:
    exe = find_exe()
    return {"installed": str(exe) if exe else None, "running": server_running(), "folder": str(install_dir())}
