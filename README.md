# Lixu: luminile PC-ului legate de CS2

Aplicație mică, cu interfață, care citește starea jocului din **Counter-Strike 2 Game State
Integration (GSI)** și colorează în timp real tot ce ai pe birou. În plus, setează **DPI-ul și
polling rate-ul** mouse-ului și arată **bateria** mouse-ului și a căștilor wireless.

| Dispozitiv | Cum îl controlează lixu |
|---|---|
| Tastatura ZENKABEAT | HID direct (protocol aflat prin reverse engineering, vezi [docs/PROTOCOL.md](docs/PROTOCOL.md)) |
| Benzi LED cu **WLED** (ESP32 / ESP8266) | UDP realtime, găsite automat prin mDNS |
| Benzi / lămpi **Govee** | API-ul LAN oficial, găsite automat |
| Becuri / benzi **Tuya** („Smart Life”, „Tuya Smart”) | protocolul local Tuya, prin `tinytuya` |
| **Logitech G502 LIGHTSPEED**, **G733** | lumini: LED SDK din G HUB; **baterie, DPI, polling rate**: HID++ 2.0 direct |
| **Placa de bază** (ASUS Aura, MSI Mystic Light, Gigabyte RGB Fusion, ASRock), RAM, GPU, coolere | prin serverul SDK al **OpenRGB** |

## Instalare

### Varianta 1: Lixu.exe

Pe un PC cu Python, rulează o dată `build-exe.bat`. Rezultatul e `dist\Lixu.exe`, un singur
fișier fără consolă. Copiază-l oriunde și pornește-l cu dublu-click.

### Varianta 2: din Python

Ai nevoie de Python 3.9+ ([python.org](https://www.python.org/downloads/)).

```bat
git clone https://github.com/banuta/lixu.git
cd lixu
pip install .[tuya]
lixu
```

Sau dublu-click pe `start-lixu.bat`.

`lixu` fără argumente pornește aplicația și deschide interfața într-o fereastră proprie
(Edge/Chrome în mod aplicație). Poți închide fereastra oricând: lixu rulează mai departe în
fundal. Pornește-l din nou ca să redeschizi fereastra. Ca să-l oprești de tot, folosește
**Setări -> Oprește lixu**.

## Interfața

| Tab | Ce poți face |
|---|---|
| **Live** | starea jocului (viață, armură, gloanțe, bombă), ce afișează fiecare dispozitiv chiar acum, și butoane de **simulare** (bombă, flash, mort ...) ca să vezi efectele fără CS2 |
| **Dispozitive** | **Scanează** (tastatură, placă de bază, Logitech, WLED, Govee, Tuya, OpenRGB) și adaugă cu un click; pentru fiecare dispozitiv: activ, nume, efect, luminozitate, **Identifică** (se aprinde roșu/verde/albastru/alb), ordinea, JSON avansat |
| **Mouse & căști** | baterie (procent, se încarcă, tensiune), **DPI**, **polling rate**, mod host/onboard, „aplică la fiecare pornire” |
| **Culori** | culorile pentru T, CT, bombă, armură, kill, headshot etc. |
| **Setări** | FPS, luminozitate globală, port GSI și token, **Instalează cfg în CS2**, editor JSON, oprire |

Totul se salvează în `lixu.json` și se aplică imediat, fără restart.

## Pregătirea fiecărui dispozitiv

* **CS2**: în Setări apasă **Instalează cfg în CS2** (sau `lixu install-cfg`), apoi repornește CS2.
* **ZENKABEAT**: închide aplicația originală (și din tray) și conectează tastatura prin cablu.
* **WLED**: nimic special, doar aceeași rețea. Când lixu se oprește, banda revine singură la
  efectul ei după 2 secunde.
* **Govee**: în Govee Home -> dispozitiv -> setări -> activează **LAN Control**.
* **Tuya / Smart Life**: vezi [mai jos](#becuri-tuya--smart-life).
* **Logitech, lumini**: G HUB pornit, iar în G HUB -> Settings activat „Allow games &
  applications to control my illumination”.
* **Logitech, baterie / DPI / polling**: funcționează cu sau fără G HUB. Dacă G HUB e pornit,
  își poate aplica propriul profil (și per joc) peste DPI-ul setat de lixu. Atunci setează
  aceleași valori și în G HUB, sau bifează **Mod host** în lixu (mouse-ul nu mai folosește
  profilurile din memoria lui).
* **Placa de bază**: instalează [OpenRGB](https://openrgb.org), pornește-l, apoi în tab-ul
  *SDK Server* apasă *Start Server* (sau `OpenRGB.exe --server --startminimized`).

## Becuri Tuya / Smart Life

**Da, se poate**, local, fără cloud la fiecare comandă. Becurile Tuya ascultă în rețea (portul
6668), dar comenzile sunt criptate cu o **cheie locală** unică per bec. Cheia se obține **o
singură dată** din contul tău Tuya:

1. Fă-ți cont gratuit pe [iot.tuya.com](https://iot.tuya.com) și creează un *Cloud Project*
   (Smart Home, data center Europa).
2. La *Devices -> Link App Account*, scanează QR-ul cu aplicația Smart Life. Becurile apar în proiect.
3. În folderul lixu rulează:
   ```bat
   pip install tinytuya
   python -m tinytuya wizard
   ```
   Wizard-ul cere API Key/Secret din proiect și scrie `devices.json` cu cheile.
4. În lixu: **Dispozitive -> Scanează**. Becurile apar cu „+ Adaugă”.

Limitări reale:
* Becurile Tuya acceptă doar câteva comenzi pe secundă. Lixu le trimite doar culoarea de
  ambient (echipă, bombă, flash), de maxim 4 ori pe secundă. Nu vor fi la fel de rapide ca WLED.
* Dacă reîmperechezi un bec în Smart Life, cheia se schimbă și rulezi din nou wizard-ul.
* Alternativă mai rapidă pentru unele becuri: firmware alternativ (OpenBeken / ESPHome).

## Config (`lixu.json`)

Se editează din interfață, dar e și un fișier simplu. Exemplu: [lixu.example.json](lixu.example.json).

| Efect | Ce arată |
|---|---|
| `keyboard` | doar tastatura: viață pe 1-0, armură pe stânga, gloanțe pe Z../, kill-uri pe dreapta, WASD în culoarea echipei |
| `ambient` | culoarea echipei; pulsează roșu sub 25 HP |
| `team` | doar culoarea echipei, fără evenimente |
| `health` / `armor` / `ammo` | bară de viață / armură / gloanțe |

Peste toate (în afară de `team`) se pun evenimentele: bombă plantată (puls roșu tot mai rapid),
defuzată/explodată, final de rundă, flashbang, foc, mort.

## Linia de comandă

| Comandă | Ce face |
|---|---|
| `lixu` / `lixu app` | aplicația cu fereastră |
| `lixu run` | la fel, fără fereastră (interfața rămâne la http://127.0.0.1:3001) |
| `lixu scan --write-config lixu.json` | caută dispozitivele |
| `lixu identify` | aprinde pe rând fiecare dispozitiv |
| `lixu battery` | bateria mouse-ului și căștilor |
| `lixu mouse --dpi 1600 --rate 1000` | DPI și polling rate (`--host-mode on/off`) |
| `lixu install-cfg` | cfg-ul GSI în CS2 |
| `lixu test` | test detaliat pentru tastatura ZENKABEAT |
| `lixu demo --dry-run --preview` | rundă simulată, desenată în terminal |

## Consum (FPS)

* Procesul rulează cu prioritate *below normal*, deci CS2 are mereu întâietate la CPU.
* Când nu se întâmplă nimic, motorul doarme până vin date noi de la CS2. Redesenează la 30 fps
  doar în animații (bombă, viață mică) și trimite doar când se schimbă culorile.
* Bateria se citește o dată pe minut.
* Interfața e doar o pagină: când fereastra e închisă sau minimizată, nu mai cere nimic.

Măsurat cu 6 dispozitive simulate, pe un nucleu de server la 2,1 GHz: **~0,2% dintr-un nucleu**
când nu se mișcă nimic și **~2,7%** în timpul animației de bombă. Pentru și mai puțin: Setări
-> FPS animații 15.

## Cum îl modifici

Vezi [docs/ARHITECTURA.md](docs/ARHITECTURA.md): cum e împărțit codul, cum schimbi efectele,
cum adaugi un dispozitiv și cum modifici interfața.
