# Lixu: luminile PC-ului legate de CS2

Program mic care citește starea jocului din **Counter-Strike 2 Game State Integration (GSI)**
și colorează în timp real:

| Dispozitiv | Cum îl controlează lixu |
|---|---|
| Tastatura ZENKABEAT | HID direct (protocol aflat prin reverse engineering, vezi [docs/PROTOCOL.md](docs/PROTOCOL.md)) |
| Benzi LED cu **WLED** (ESP32 / ESP8266) | UDP realtime (DRGB/DNRGB), găsite automat prin mDNS |
| Benzi / lămpi **Govee** | API-ul LAN oficial (UDP), găsite automat |
| **Logitech G502**, **G733** și alte Logitech G | Logitech LED SDK din G HUB |
| **Placa de bază** (ASUS Aura, MSI Mystic Light, Gigabyte RGB Fusion, ASRock), RAM, GPU, coolere | prin serverul SDK al **OpenRGB** |

Nu are interfață grafică și nicio dependență în afară de Python. E gândit să nu fure FPS
(vezi [Consum](#consum-fps)).

## Instalare (Windows)

Ai nevoie de Python 3.9+ ([python.org](https://www.python.org/downloads/)).

```bat
git clone https://github.com/banuta/lixu.git
cd lixu
pip install .
```

## Pași

1. **Găsește dispozitivele** și scrie config-ul:
   ```bat
   lixu scan --write-config lixu.json
   ```
   Pentru benzi WLED care nu apar, adaugă subrețeaua: `lixu scan --subnet 192.168.1.0/24 ...`
2. **Vezi care e care**: fiecare dispozitiv se aprinde roșu, verde, albastru, alb:
   ```bat
   lixu identify
   ```
3. **Instalează cfg-ul în CS2** (găsește singur folderul din Steam):
   ```bat
   lixu install-cfg
   ```
4. **Pornește**, apoi intră în CS2:
   ```bat
   lixu run
   ```
   Sau dublu-click pe `start-lixu.bat`, care pornește minimizat, cu prioritate scăzută.

### Ce trebuie pregătit pe fiecare dispozitiv

* **ZENKABEAT**: închide aplicația originală (și din tray) și conectează tastatura prin cablu.
  Test detaliat: `lixu test` (dacă roșul iese albastru, pune `"rgb_order": "2,1,0"` în config).
* **WLED**: nimic special. ESP32 trebuie să fie în aceeași rețea. Când lixu se oprește,
  banda revine singură la efectul ei după 2 secunde.
* **Govee**: în aplicația Govee Home -> dispozitiv -> setări -> activează **LAN Control**.
  Nu toate modelele au LAN API; cele care nu au nu apar la scan.
* **Logitech G502 / G733**: **G HUB** trebuie să ruleze, iar în G HUB -> Settings trebuie activat
  „Allow games & applications to control my illumination”. Pentru G733 și mouse-ul wireless,
  receiver-ul trebuie să fie conectat.
* **Placa de bază**: instalează [OpenRGB](https://openrgb.org), pornește-l, apoi în tab-ul
  *SDK Server* apasă *Start Server* (sau pornește-l cu `OpenRGB.exe --server --startminimized`).
  `lixu scan` afișează apoi tot ce vede OpenRGB. Dacă folosești OpenRGB și pentru Logitech,
  închide G HUB, ca să nu se certe între ele.

## Config (`lixu.json`)

Exemplu complet: [lixu.example.json](lixu.example.json).

```json
{
  "gsi": {"port": 3000, "token": null},
  "fps": 30,
  "devices": [
    {"type": "zenkabeat", "effect": "keyboard"},
    {"type": "wled", "host": "192.168.1.60", "effect": "health"},
    {"type": "govee", "host": "192.168.1.70", "effect": "ambient"},
    {"type": "logitech", "target": "mouse", "effect": "ambient"},
    {"type": "logitech", "target": "headset", "effect": "health"},
    {"type": "openrgb", "device_type": "motherboard", "effect": "ambient", "brightness": 0.7}
  ]
}
```

Fiecare dispozitiv poate avea `"effect"`, `"brightness"` (0-1) și `"enabled": false`.

| Efect | Ce arată |
|---|---|
| `keyboard` | doar tastatura: viață pe 1-0, armură pe stânga, gloanțe pe Z../, kill-uri pe dreapta, WASD în culoarea echipei |
| `ambient` | culoarea echipei (T portocaliu, CT albastru); pulsează roșu sub 25 HP |
| `team` | doar culoarea echipei, fără evenimente |
| `health` | bară de viață verde -> roșu (pe un dispozitiv cu un singur LED: culoarea vieții) |
| `armor` | bară de armură |
| `ammo` | bară de gloanțe, roșu clipitor când e gol |

Peste toate (în afară de `team`) se pun evenimentele: bombă plantată (puls roșu tot mai rapid),
defuzată/explodată (flash), final de rundă (flash în culoarea câștigătorilor), flashbang (alb),
foc (portocaliu), mort (gri).

Opțiuni pentru dispozitive:

| Tip | Câmpuri |
|---|---|
| `zenkabeat` | `rgb_order` |
| `wled` | `host`, `leds` (altfel citit din WLED), `port`, `timeout` |
| `govee` | `host`, `device_brightness` (1-100) |
| `logitech` | `target`: `all` / `mouse` / `headset` / `keyboard` / `mousemat` / `speaker`, `zones` (implicit `[0, 1]`), `dll` |
| `openrgb` | `host`, `port`, `device_type` (`motherboard`, `dram`, `gpu`, `ledstrip`, `mouse`, `headset` ...), `match` (parte din nume), `index` |

## Consum (FPS)

* Procesul își pune singur prioritatea *below normal*, așa că CS2 are mereu întâietate la CPU.
* Când nu se întâmplă nimic, motorul doarme până vin date noi de la CS2. Altfel trimite doar
  un keepalive rar (0,5-10 s, în funcție de dispozitiv).
* Redesenează la 30 fps doar în animații (bombă, viață mică, flash-uri). Trimite doar când se
  schimbă culorile, iar Govee e limitat la 10 comenzi/s.
* Nu are GUI. Rețeaua e UDP, plus o conexiune TCP locală la OpenRGB.

Măsurat cu 6 dispozitive (`lixu demo --dry-run`), pe un nucleu de server la 2,1 GHz:
**~0,2% dintr-un nucleu** când nu se mișcă nimic și **~2,3%** în timpul animației de bombă.
Dacă vrei și mai puțin, pune `"fps": 15` în config.

## Test fără hardware / fără CS2

```bash
python -m lixu demo --dry-run --preview                       # rundă simulată, desenată în terminal
python -m lixu demo --dry-run --config lixu.example.json      # toate dispozitivele simulate
python -m unittest discover -s tests                          # teste
```

## Cum îl modifici

Vezi [docs/ARHITECTURA.md](docs/ARHITECTURA.md): cum e împărțit codul, cum schimbi culorile,
cum adaugi un efect nou sau un dispozitiv nou.
