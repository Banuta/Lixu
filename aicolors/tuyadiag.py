"""Diagnostic pentru becurile Tuya: scrie tuya-diagnostic.txt (fără cheie).

Verifică, pentru fiecare bec Tuya din config:
  1. cheia (din config / devices.json) – doar dacă există și câte caractere are;
  2. ping și portul local 6668 la IP-ul salvat;
  3. căutarea Tuya în rețea (anunțurile UDP 6666/6667/7000) – ce IP și ce versiune anunță becul;
  4. citirea stării cu fiecare versiune de protocol, la IP-ul salvat și la cel găsit;
  5. un test de culoare: roșu 2 s, apoi verde 2 s.
"""

from __future__ import annotations

import hashlib
import platform
import socket
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional


def _short(text, n: int = 300) -> str:
    text = str(text)
    return text if len(text) <= n else text[:n] + "…"


def _fingerprint(key: str) -> str:
    """Amprentă scurtă a cheii (ca să vedem dacă două chei sunt la fel, fără să o arătăm)."""
    return hashlib.sha256(key.encode()).hexdigest()[:8] if key else "-"


def _ping(host: str) -> str:
    flag = "-n" if platform.system() == "Windows" else "-c"
    try:
        r = subprocess.run(["ping", flag, "2", host], capture_output=True, text=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        ok = r.returncode == 0 and ("TTL=" in r.stdout.upper())
        return "răspunde" if ok else "NU răspunde"
    except Exception as exc:
        return f"nu am putut rula ping: {exc}"


def _port(host: str, port: int = 6668) -> str:
    try:
        with socket.create_connection((host, port), timeout=2):
            return "deschis"
    except OSError as exc:
        return f"ÎNCHIS ({exc})"


def run(out_path: str = "tuya-diagnostic.txt") -> Path:
    from . import config as configmod
    from .devices import tuya

    lines: List[str] = []

    def say(text: str = "") -> None:
        print(text, flush=True)
        lines.append(text)

    say("AI Colors – diagnostic Tuya, " + time.strftime("%Y-%m-%d %H:%M:%S"))
    say(f"PC: {platform.platform()}, IP local: {tuya._local_ip()}")
    try:
        import tinytuya

        say(f"tinytuya {getattr(tinytuya, '__version__', '?')}")
    except ImportError:
        say("tinytuya NU e instalat: pip install tinytuya")
        return _write(out_path, lines)

    cfg = configmod.load()
    say(f"config: {cfg.path}")
    bulbs = [d for d in cfg.devices if d.get("type") == "tuya"]
    if not bulbs:
        say("În config nu e niciun bec Tuya (Dispozitive -> + Adaugă manual -> tuya).")

    say("")
    say("== devices.json găsite ==")
    known: Dict[str, Dict] = {}
    for p in tuya._devices_json_paths():
        if p.is_file():
            data = tuya.wizard_devices(str(p))
            say(f"{p}: {len(data)} dispozitive")
            for did, d in data.items():
                if d.get("key") and not tuya.key_ok(d["key"]):
                    say(f"   {did}: cheia {tuya.key_problem(d['key'])}")
            for did, d in data.items():
                key = d.get("key") or ""
                say(f"   {d.get('name', '?')}: id {did}, cheie {len(key)} caractere (amprentă {_fingerprint(key)}), "
                    f"ip „{d.get('ip') or ''}”, versiune {d.get('version') or '?'}")
                known.setdefault(did, d)
    if not known:
        say("niciunul (rulează `python -m tinytuya wizard` sau folosește „Încarcă devices.json…”)")

    say("")
    say("== căutare Tuya în rețea (12 s, anunțuri UDP) ==")
    scanned: Dict[str, Dict] = {}
    try:
        found = tinytuya.deviceScan(False, 12, False, False) or {}
        for ip, info in found.items():
            gw = info.get("gwId") or info.get("id")
            scanned[gw] = dict(info, ip=ip)
            say(f"   {ip}: id {gw}, versiune {info.get('version')}")
        if not found:
            say("   nimic: firewall-ul Windows blochează UDP 6666/6667 pentru Python, sau becul e offline")
    except Exception as exc:
        say(f"   eroare la căutare: {_short(exc)}")

    for entry in bulbs:
        did = entry.get("id", "")
        wiz = known.get(did, {})
        key = (entry.get("local_key") or wiz.get("key") or "").strip()
        host = (entry.get("host") or wiz.get("ip") or "").strip()
        say("")
        say(f"== bec {entry.get('name') or did} (id {did}) ==")
        say(f"cheie: {'din config' if entry.get('local_key') else 'din devices.json' if wiz.get('key') else 'LIPSEȘTE'}, "
            f"{len(key)} caractere, amprentă {_fingerprint(key)}")
        if key and not tuya.key_ok(key):
            say(f"   GREȘIT: cheia {tuya.key_problem(key)}")
            if tuya.key_ok(wiz.get("key")):
                key = wiz["key"].strip()
                say(f"   testez cu cheia din {wiz.get('_file')} (16 caractere, amprentă {_fingerprint(key)})")
        if entry.get("local_key") and wiz.get("key") and entry["local_key"].strip() != wiz["key"]:
            say("   ATENȚIE: cheia din config diferă de cea din devices.json (becul a fost re-împerecheat?)")
        if did and known and did not in known:
            say("   ATENȚIE: id-ul nu e în devices.json – becul a primit alt id (re-adăugat în Smart Life?)")
        if did in scanned:
            say(f"în rețea: anunțat de pe {scanned[did]['ip']}, versiune {scanned[did].get('version')}")
        else:
            say("în rețea: becul NU s-a anunțat în căutare")
        say(f"IP salvat: {host or '(niciunul)'}")
        hosts = [h for h in [host, scanned.get(did, {}).get("ip")] if h]
        hosts = list(dict.fromkeys(hosts))
        for h in hosts:
            say(f"  {h}: ping {_ping(h)}, port 6668 {_port(h)}")
        if not key:
            say("  fără cheie nu pot testa mai departe")
            continue
        working = None
        for h in hosts:
            if _port(h).startswith("ÎNCHIS"):
                say(f"  {h}: portul 6668 e închis, nu are rost să încerc protocoalele")
                continue
            for v in tuya.VERSIONS:
                try:
                    b = tinytuya.BulbDevice(did, h, key, version=v, connection_timeout=3)
                    b.set_socketTimeout(2)
                    tuya.fast_fail(b)
                    st = b.status()
                except Exception as exc:
                    st = {"Error": repr(exc)}
                ok = isinstance(st, dict) and "Error" not in st and "Err" not in st
                say(f"  {h} protocol {v}: {'MERGE ' + _short(st.get('dps')) if ok else _short(st)}")
                if ok and working is None:
                    working = (h, v, b)
                else:
                    try:
                        b.close()
                    except Exception:
                        pass
        if working is None:
            say("  becul nu răspunde la niciun protocol")
            continue
        h, v, b = working
        say(f"test culoare pe {h}, protocol {v}: roșu 2 s, apoi verde 2 s (uită-te la bec)")
        for name, rgb in (("roșu", (255, 0, 0)), ("verde", (0, 255, 0))):
            try:
                res = b.set_colour(*rgb)
            except Exception as exc:
                res = {"Error": repr(exc)}
            say(f"  {name}: {_short(res)}")
            time.sleep(2)
        try:
            say(f"  stare după test: {_short(b.status())}")
            b.close()
        except Exception as exc:
            say(f"  stare după test: {exc}")
        say(f"  -> în AI Colors pune IP {h} și protocolul {v} la Dispozitive, sub rândul Tuya")

    say("")
    say("Trimite fișierul ăsta (nu conține cheia).")
    return _write(out_path, lines)


def _write(out_path: str, lines: List[str]) -> Path:
    path = Path(out_path)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
