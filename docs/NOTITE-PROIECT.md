# Notițe de proiect (AI Colors) – ce am aflat și ce urmează

Rezumatul conversației cu utilizatorul, ca să nu se piardă nimic important.
Limba de lucru: **română**. Codul e pe branch-ul `ccr-0ddab67e-06mfdx` din `Banuta/Lixu`.

## Preferințele utilizatorului
* Arhive `.zip` **doar când cere** („fă arhiva”). Modificările se urcă oricum pe GitHub.
* Vrea totul automat, fără configurat manual; aplicația stă lângă ceas, fără ferestre `cmd`.
* Nu vrea G HUB instalat; nu vrea să riște tastatura („să nu-mi cumpăr una nouă”).
* Ultima versiune livrată: **v20** (`AIColors-v20.zip`). Versiunea aplicației în cod: 0.5.0.

## Hardware-ul utilizatorului (din diagnostic)
| Dispozitiv | Detalii |
|---|---|
| Tastatură ZENKABEAT | USB `05AC:024F` „BY Tech Gaming Keyboard”, fw 0x0101. **Fără canal live** (nu are colecția feature 382). Are colecțiile vendor `0xFF00`: feature 6 (comenzi, report 5) și feature 1032 (date, report 6). |
| Mouse | **G502 X PLUS**, receiver LIGHTSPEED `046D:C547`, HID++ la index 1. Baterie/DPI (800)/polling (1000 Hz) merg; mod onboard = host. |
| Căști | **G733**, `046D:0B1F`, HID++ la index 0xFF, colecție long pe page `0xFF43`. Baterie prin ADC (mV). |
| WLED | Perdea `192.168.68.51` (214 LED, ESP32-S2), Tv `192.168.68.57` (58 LED, ESP8266), Pc `192.168.68.72` (30 LED, ESP32) |
| Govee | **H619A** `192.168.68.70`, **20 de segmente** (confirmat și în tabela OpenRGB) |
| Tuya | bec id `00200359600194219611`, `192.168.68.71`, protocol 3.1 – lipsește local key (utilizatorului nu i se încarcă iot.tuya.com / platform.tuya.com) |
| Placă de bază | **Gigabyte B550M AORUS ELITE** (prin OpenRGB, zone `D_LED1`/`D_LED2` etc.). La primul diagnostic (alt user Windows, `rcris`) apăruse ASRock B450M Pro4 R2.0. |
| RAM | **Kingston FURY RGB** – OpenRGB nu le vede; merg doar cu pluginul SignalRGB „Kingston Hyper Fury Ram.js” |
| Altele | Logitech BRIO (cameră), Razer Seiren V3 Mini (microfon) |

## Tastatura ZENKABEAT – protocolul (aflat prin RE + teste pe tastatura lui)
* Al doilea byte din comenzi = **adresă în flash, în pași de 256 bytes**.
  * Citire: `SetFeature(cmd, 05 88 <pagină> 00 00 00 00)` apoi `GetFeature(data, 06, 1032)` → date de la offset 8.
  * Scriere pagină: `SetFeature(data, 06 08 <pagină> 00 40 00 00 00 + 1024 bytes)`.
  * Scriere profil (cea care merge, „ACCEPTAT”): `06 03 B6 00 00 00 00 00 + 254 bytes` (pagina 0xB600).
* **Sub 0xB000 e firmware-ul** (reset vector `LJMP F000`; bootloader la 0xF000). Scrierile acolo sunt blocate în `protocol.write_packet` / `profile_write_packet`.
* **Efectul activ: byte-ul 0xB60D.** Valoarea = poziția în lista aplicației originale, de la 1:
  1 Fixed_on, **2 Respire (efectul utilizatorului)**, 3 Rainbow, …, **12 Reaction (confirmat)**, …, 20 Perfect, **21 = tastatura stinsă (confirmat)**, 22 OFF.
* Fn+6/7/8/9/0 aleg direct efectele 1/2/4/5/6 (nu grupuri Game mode).
* **Paleta efectelor: 0xB800**, 21 bytes (7 culori RGB) pe efect; paleta din fabrică = ff0000 ffff00 00ff00 00ffff 0000ff ff00ff ffffff pentru fiecare efect.
* **Culori automate MERG** (utilizatorul: „da merge”): scrie paleta cu culoarea situației + reaplică efectul fix 1 (`set_mode(..., force=True)`). Paleta originală se salvează o dată în `kb_original_palette.bin` (config); o paletă uniformă rămasă e înlocuită cu cea din fabrică. `kbtest palette-reset` repune paleta din fabrică.
* **Game mode / culori pe taste: 0xBC00–0xC3FF**, 5 grupuri × 378 bytes, planuri RGB (GameRGBIndex 2,1,0), index = RGBTAB (rând*21+col). Grupurile găsite: 1 = toate tastele, 2 = CF, 3 = COD, 4 = LOL, 5 = QQ race (WASD+săgeți) – se potrivesc cu `GaoshouKey` din Cfg.ini. **Încă nu știm cum se activează** (21 stinge; la trecerea de pe efectul 20 s-a șters o listă de taste la 0xB700 – de investigat).
* Dump-ul complet al memoriei: `kb_flash_backup.bin` (64 KB) la utilizator (în `C:\Windows\System32` sau folderul AIColors).

## Alte protocoale (verificate)
* **Govee DreamView („razer”)**: `BB 00 len B0 <flag> n RGB… xor`, flag **0x01 = segmente separate** (0x00 = degrade). Enable `uwABsQEK`, disable `uwABsQAL`.
* **Logitech HID++ 2.0** fără G HUB: baterie (0x1000/0x1001/0x1004/0x1F20), DPI 0x2201, polling 0x8060/0x8061, onboard 0x8100, lumini 0x8071/0x8070 (Static, ca Solaar).
* **OpenRGB SDK** v0, zone prin `UPDATEZONELEDS` (1051).
* **Kingston FURY (pluginul SignalRGB)**: SMBus 0x60–0x63 (date) / 0x50–0x53 (SPD), registre 0x50–0x73 (12 LED × RGB), încadrare 0x53/0x44 în 0x08. **Nu îl implementăm direct** (driver kernel + risc de a strica SPD-ul).

## Ce face aplicația acum (v20)
Interfață web (Edge `--app`) + iconiță lângă ceas (Deschide / Pauză / Pornește cu Windows / Ieșire, notificări baterie), motor cu fir propriu per dispozitiv (nu se mai blochează), efecte (keyboard/ambient/team/health/armor/ammo + evenimente), dispozitive: zenkabeat (efecte + culori automate), wled, govee (segmente/grupuri/hosts), logitech (HID++ sau G HUB), openrgb (zone, RAM toate plăcuțele), tuya (chei din cont în UI), signalrgb (punte + efect „AI Colors CS2”), OpenRGB descărcat/pornit din UI, stinge luminile la oprirea Windows, `/api/game` (stare brută CS2, CORS).

## Efecte (cererea utilizatorului)
* Culorile echipelor ca în CS2 (HUD: T `#DE9B35`, CT `#5D79AE`), saturate pentru LED: **T `#FF8C00` portocaliu,
  CT `#0050FF` albastru**. Utilizatorul a cerut explicit: roșul NU pentru T, ca să nu se confunde cu damage/bombă.
  Vechile valori implicite salvate (`#ff6e00`, `#006eff`) se migrează la cele noi.
* Final de rundă: T câștigă = **clipește** (portocaliu), CT câștigă = **flash albastru** (config `events.win_t/win_ct`: blink/flash/pulse).
* Flash de damage (roșu, după cât ai pierdut), flash la kill (auriu / mov HS), efect de bandă `bomb` (timp rămas).
* Tastatura: situațiile `win_ct`/`win_t` au culoarea echipei; pauza dintre scrieri 1 s (era 3 s); scrierile
  se verifică doar la început și din 15 în 15 (calea rapidă, ~0,2 s în loc de ~1,5 s per schimbare).
  Utilizatorul spusese că luminile „par în urmă” – asta era cauza principală.

* Govee din interfață: sub rândul Govee – Segmente, Grupare (separat/2/4/5), inversează direcția (`reverse`), degrade.

## De făcut / în așteptare
1. **Firmware tastatură (culori live)** – plan sigur: (1) utilizatorul trimite `kb_flash_backup.bin`, îl analizez (handler comenzi, buffer LED, loc liber); (2) testăm citirea prin bootloader cu `sinowealth-kb-tool` (doar citire); (3) abia apoi patch + scriere. Fără pasul 2 reușit, nu scriem.
2. **Efect SignalRGB „CS2 Direct”** – început (`/api/game` gata), fișierul `aicolors/signalrgb/CS2Direct.html` nescris.
3. **Game mode pe taste** – de aflat cum se activează (rezultatul efectului 20 neraportat; lista de la 0xB700).
4. **Kingston prin SignalRGB** – de confirmat dacă efectul „AI Colors CS2” colorează memoriile.
5. **Tuya** – utilizatorului nu i se încarcă site-ul Tuya; de reluat.
6. **Stingerea la oprire** – de confirmat pe PC (plus profil „Stins” + „Set Profile on Exit” în OpenRGB; BIOS: LEDs in Soft Off States = Off).
