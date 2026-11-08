# Cum e făcut lixu (și cum îl modifici)

```
CS2 --HTTP POST JSON--> gsi.py --GameState--> engine.py --culori--> devices/*.py --> hardware
                                                  |
                                              effects.py
```

| Fișier | Ce face | Cât de des îl modifici |
|---|---|---|
| `lixu/effects.py` | starea jocului -> culori. **Aici te joci.** | des |
| `lixu/layout.py` | tastele ZENKABEAT și grupurile de taste (rânduri, coloane) | uneori |
| `lixu/gsi.py` | serverul HTTP pentru CS2 și `GameState` (viață, armură, bombă ...) | dacă vrei date noi din joc |
| `lixu/engine.py` | bucla principală: când redesenează, cui trimite, reconectare | rar |
| `lixu/config.py` | citirea `lixu.json` | rar |
| `lixu/devices/` | un fișier per tip de dispozitiv | când adaugi hardware |
| `lixu/discovery/` | `scan`: mDNS, placa de bază, agregarea rezultatelor | rar |
| `lixu/protocol.py`, `lixu/hid_win.py` | protocolul HID al tastaturii ZENKABEAT | aproape niciodată |

## Schimbi culori

În `lixu/effects.py`, sus de tot:

```python
T_COLOR: RGB = (255, 110, 0)    # teroriști
CT_COLOR: RGB = (0, 110, 255)   # counter-teroriști
BOMB_COLOR: RGB = (255, 0, 0)
```

## Schimbi ce taste arată ce (tastatura)

În `lixu/layout.py` sunt grupurile:

```python
NUMBER_ROW = list("1234567890")      # viață
LEFT_COLUMN = ["Esc", "Tab", "CapsLock", "LShift", "LCtrl"]   # armură
BOTTOM_ROW = list("ZXCVBNM") + [",", ".", "/"]                 # gloanțe
RIGHT_COLUMN = ["Home", "Delete", "PgUp", "PgDn", "Right"]     # kill-uri
```

Clasa `Renderer` din `effects.py` le folosește. Ca să muți viața pe `QWERTY_ROW`, schimbi
`layout.NUMBER_ROW` în `_health`.

## Adaugi un efect nou

O funcție care primește `(stare, timp, număr_de_LED-uri)` și întoarce o listă de culori,
înregistrată în `STRIP_EFFECTS`:

```python
def strip_money(st, now, n):
    # bara de bani: $16000 = plin
    return bar(n, st.money / 16000, (0, 255, 80))

STRIP_EFFECTS["money"] = strip_money
```

Apoi în `lixu.json`: `{"type": "wled", "host": "...", "effect": "money"}`.

Câmpuri utile din `GameState` (`gsi.py`): `team`, `health`, `armor`, `helmet`, `flashed`,
`burning`, `money`, `round_kills`, `round_killhs`, `active_weapon` (`ammo_clip`, `ammo_clip_max`,
`name`), `bomb`, `round_phase`, `win_team`, `map_phase`, plus `raw` (tot JSON-ul de la CS2).

Dacă efectul tău se mișcă în timp (folosește `now`), adaugă condiția și în `is_animating`.
Altfel motorul îl redesenează doar când vin date noi.

## Adaugi un dispozitiv nou

1. `lixu/devices/altceva.py`:
   ```python
   from .base import Device, Found

   class AltcevaDevice(Device):
       kind = "altceva"
       min_interval = 0.05   # cât de des acceptă comenzi
       keepalive = 2.0

       def __init__(self, host):
           super().__init__(f"Altceva {host}", led_count=10)
           ...

       def send(self, colors):     # listă de led_count culori (R, G, B) 0-255
           ...

   def from_config(entry):
       return AltcevaDevice(entry["host"])

   def discover():               # opțional, pentru `lixu scan`
       return [Found("altceva", "Nume", address="...", config={"type": "altceva", "host": "..."})]
   ```
2. În `lixu/devices/__init__.py` adaugi `"altceva": "lixu.devices.altceva"` în `FACTORIES`
   (și un număr de LED-uri în `DRY_RUN_LEDS`).
3. Dacă are `discover()`, îl adaugi în `_sources` din `lixu/discovery/scan.py`.

## De ce e ușor pe CPU

`Engine.run()` (în `engine.py`): după fiecare cadru întreabă `effects.is_animating()`.
Dacă nu e nicio animație, așteaptă pe `StateStore.changed` (un `threading.Event` setat de
serverul GSI) până la cel mai scurt keepalive. Deci nu consumă nimic între evenimente.
Fiecare dispozitiv primește un cadru doar dacă s-a schimbat.
