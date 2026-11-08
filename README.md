# Lixu: lumini CS2 pe tastatura ZENKABEAT

Înlocuiește aplicația OEM (`OemDrv.exe` din `ZENKABEAT_Keyboard_Setup_V1.0`) cu un program mic
care citește starea jocului din **Counter-Strike 2 Game State Integration (GSI)** și colorează
tastatura în timp real.

Aplicația originală nu are suport pentru GSI. Protocolul tastaturii a fost aflat prin reverse
engineering și e descris în [docs/PROTOCOL.md](docs/PROTOCOL.md).

## Ce afișează

| Taste | Ce arată |
|---|---|
| fundal | culoarea echipei: T portocaliu, CT albastru; în meniu, mov care „respiră” |
| W A S D, Space, Ctrl, Shift | culoarea echipei, mai aprinsă |
| `1` ... `0` | viața (verde -> galben -> roșu), pulsează sub 25 HP |
| Esc, Tab, Caps, LShift, LCtrl | armura (albastru deschis dacă ai cască) |
| `Z` ... `/` | gloanțele din încărcător; roșu clipitor când e gol sau reîncarci |
| Home, Del, PgUp, PgDn, Right | kill-urile din rundă (galben; roz pentru headshot) |
| toată tastatura | bombă plantată: puls roșu tot mai rapid; defuzată: flash albastru; explodată: flash |
| toată tastatura | final de rundă: flash în culoarea echipei câștigătoare |
| toată tastatura | mort: gri închis; flashbang: alb; foc: portocaliu jos |

Efectele sunt în `lixu/effects.py` și se pot modifica ușor.

## Instalare (Windows)

Ai nevoie de Python 3.9+ ([python.org](https://www.python.org/downloads/)). Nu sunt alte dependențe.

```bat
git clone https://github.com/banuta/lixu.git
cd lixu
pip install .
```

1. **Închide aplicația ZENKABEAT** (și din tray). Altfel se luptă cu lixu pe aceeași interfață.
2. Conectează tastatura **prin cablu**.
3. Verifică dacă e găsită:
   ```bat
   lixu probe
   ```
   Trebuie să apară o linie cu `feature=382 cadre LED (folosită de lixu)`.
4. Testează luminile:
   ```bat
   lixu test
   ```
   Tastatura se face roșie, verde, albastră, albă, apoi aprinde rând cu rând și tastă cu tastă.
   Dacă roșul iese albastru, rulează cu `--rgb-order 2,1,0` (și folosește aceeași opțiune la `run`).
5. Instalează cfg-ul GSI în CS2 (găsește singur folderul din Steam):
   ```bat
   lixu install-cfg
   ```
   Sau manual cu `--cs2-dir "...\Counter-Strike Global Offensive\game\csgo\cfg"`.
   Fișierul scris e `gamestate_integration_lixu.cfg`.
6. Pornește lixu, apoi CS2:
   ```bat
   lixu run
   ```

Opțiuni utile pentru `run`: `--port 3000`, `--token SECRET` (același și la `install-cfg`),
`--brightness 0.6`, `--fps 30`.

## Test fără tastatură / fără CS2

```bash
python -m lixu demo --dry-run --preview   # simulează o rundă și o desenează în terminal
python -m lixu run --dry-run              # server GSI fără să trimită la tastatură
python -m unittest discover -s tests      # teste
```

## Structura

| Fișier | Rol |
|---|---|
| `lixu/protocol.py` | construirea pachetelor HID (cadru de 126 LED-uri) |
| `lixu/hid_win.py` | acces HID pe Windows prin ctypes (`hid.dll`, `setupapi.dll`) |
| `lixu/device.py` | deschiderea tastaturii, backend dry-run și previzualizare |
| `lixu/layout.py` | cele 68 de taste și indexurile lor LED |
| `lixu/gsi.py` | serverul HTTP pentru CS2 GSI și starea jocului |
| `lixu/effects.py` | starea jocului -> culori |
| `lixu/cs2cfg.py` | găsirea CS2 și scrierea cfg-ului |

## Limitări cunoscute

* Doar Windows. Pe Linux ar trebui un backend `hidraw`.
* Protocolul e extras din binar, nu testat încă pe tastatură. Dacă `test` nu aprinde nimic,
  rulează `lixu -v probe` și trimite output-ul.
* Când lixu se oprește, tastatura poate rămâne pe ultimul cadru până la reconectare sau
  până schimbi efectul din tastatură (Fn + ...).
