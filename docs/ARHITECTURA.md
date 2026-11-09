# Cum e făcut AI Colors (și cum îl modifici)

```
CS2 --HTTP POST JSON--> gsi.py --GameState--> engine.py --culori--> devices/*.py --> hardware
                                                  |
                                              effects.py

interfața (ui/index.html) <--/api/*--> app.py --> engine / config / peripherals
mouse & căști <--HID++ 2.0--> peripherals/logitech.py (baterie, DPI, polling rate)
```

| Fișier | Ce face | Cât de des îl modifici |
|---|---|---|
| `aicolors/effects.py` | starea jocului -> culori. **Aici te joci.** | des |
| `aicolors/ui/index.html` | interfața: un singur fișier HTML + CSS + JS, fără biblioteci | des |
| `aicolors/app.py` | leagă totul și expune API-ul pentru interfață (`/api/state`, `/api/config` ...) | când adaugi un buton nou |
| `aicolors/peripherals/hidpp.py` | protocolul Logitech HID++ 2.0 (baterie, DPI, polling, mod onboard) | rar |
| `aicolors/peripherals/logitech.py` | găsește mouse-ul/căștile și le citește o dată pe minut | rar |
| `aicolors/layout.py` | tastele ZENKABEAT și grupurile de taste (rânduri, coloane) | uneori |
| `aicolors/gsi.py` | serverul HTTP pentru CS2 și `GameState` (viață, armură, bombă ...) | dacă vrei date noi din joc |
| `aicolors/engine.py` | bucla principală: când redesenează, cui trimite, reconectare | rar |
| `aicolors/config.py` | citirea `aicolors.json` | rar |
| `aicolors/devices/` | un fișier per tip de dispozitiv | când adaugi hardware |
| `aicolors/discovery/` | `scan`: mDNS, placa de bază, agregarea rezultatelor | rar |
| `aicolors/protocol.py`, `aicolors/hid_win.py` | protocolul HID al tastaturii ZENKABEAT | aproape niciodată |

## Schimbi culori

În `aicolors/effects.py`, sus de tot:

```python
T_COLOR: RGB = (255, 110, 0)    # teroriști
CT_COLOR: RGB = (0, 110, 255)   # counter-teroriști
BOMB_COLOR: RGB = (255, 0, 0)
```

## Schimbi ce taste arată ce (tastatura)

În `aicolors/layout.py` sunt grupurile:

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

Apoi în `aicolors.json`: `{"type": "wled", "host": "...", "effect": "money"}`.

Câmpuri utile din `GameState` (`gsi.py`): `team`, `health`, `armor`, `helmet`, `flashed`,
`burning`, `money`, `round_kills`, `round_killhs`, `active_weapon` (`ammo_clip`, `ammo_clip_max`,
`name`), `bomb`, `round_phase`, `win_team`, `map_phase`, plus `raw` (tot JSON-ul de la CS2).

Dacă efectul tău se mișcă în timp (folosește `now`), adaugă condiția și în `is_animating`.
Altfel motorul îl redesenează doar când vin date noi.

## Adaugi un dispozitiv nou

1. `aicolors/devices/altceva.py`:
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

   def discover():               # opțional, pentru `aicolors scan`
       return [Found("altceva", "Nume", address="...", config={"type": "altceva", "host": "..."})]
   ```
2. În `aicolors/devices/__init__.py` adaugi `"altceva": "aicolors.devices.altceva"` în `FACTORIES`
   (și un număr de LED-uri în `DRY_RUN_LEDS`).
3. Dacă are `discover()`, îl adaugi în `_sources` din `aicolors/discovery/scan.py`.

## Modifici interfața

`aicolors/ui/index.html` e HTML simplu. Variabilele de culoare sunt sus, în `:root`; textele sunt
direct în HTML sau în obiectul `LABELS` din JavaScript. Pornește `aicolors run --dry-run` și
reîncarcă pagina (F5) după fiecare modificare.

Un buton nou care face ceva în aplicație:
1. în `app.py`, în `routes` din `make_ui_handler`, adaugi `"/api/ceva": lambda: app.ceva(data)`
2. în `index.html`: `await api("/api/ceva", {parametri})`

Toate cererile POST trebuie să aibă antetul `X-AIColors: 1` (funcția `api()` îl pune singură). Așa
o pagină web străină nu poate schimba setările.

## Altă funcție pentru mouse

`HidppDevice` (în `peripherals/hidpp.py`) are `call(feature_id, funcție, parametri)`. ID-urile
feature-urilor HID++ 2.0 sunt publice (le găsești în Solaar, `lib/logitech_receiver/hidpp20_constants.py`).
De exemplu, 0x2201 e DPI-ul, cu funcțiile 1 = listă, 2 = citește, 3 = setează.

## De ce e ușor pe CPU

`Engine.run()` (în `engine.py`): după fiecare cadru întreabă `effects.is_animating()`.
Dacă nu e nicio animație, așteaptă pe `StateStore.changed` (un `threading.Event` setat de
serverul GSI) până la cel mai scurt keepalive. Deci nu consumă nimic între evenimente.
Fiecare dispozitiv primește un cadru doar dacă s-a schimbat.
