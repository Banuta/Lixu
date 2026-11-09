# AI Colors: luminile PC-ului legate de CS2

Aplicație mică, cu interfață, care citește starea jocului din **Counter-Strike 2 Game State
Integration (GSI)** și colorează în timp real tot ce ai pe birou. În plus, setează **DPI-ul și
polling rate-ul** mouse-ului și arată **bateria** mouse-ului și a căștilor wireless.

| Dispozitiv | Cum îl controlează AI Colors |
|---|---|
| Tastatura ZENKABEAT | HID direct (protocol aflat prin reverse engineering, vezi [docs/PROTOCOL.md](docs/PROTOCOL.md)) |
| Benzi LED cu **WLED** (ESP32 / ESP8266) | UDP realtime, găsite automat prin mDNS |
| Benzi / lămpi **Govee** | API-ul LAN oficial, găsite automat |
| Becuri / benzi **Tuya** („Smart Life”, „Tuya Smart”) | protocolul local Tuya, prin `tinytuya` |
| **Logitech G502 LIGHTSPEED**, **G733** | lumini: LED SDK din G HUB; **baterie, DPI, polling rate**: HID++ 2.0 direct |
| **Placa de bază** (ASUS Aura, MSI Mystic Light, Gigabyte RGB Fusion, ASRock), GPU, coolere | prin serverul SDK al **OpenRGB** |
| **Memorii RAM RGB** (Kingston FURY Beast/Renegade RGB și altele) | prin **OpenRGB**; toate plăcuțele se controlează împreună |

## Instalare

### Varianta 1: AIColors.exe

Pe un PC cu Python, rulează o dată `build-exe.bat`. Rezultatul e `dist\AIColors.exe`, un singur
fișier fără consolă. Copiază-l oriunde și pornește-l cu dublu-click.

### Varianta 2: din Python

Ai nevoie de Python 3.9+ ([python.org](https://www.python.org/downloads/)).

```bat
git clone https://github.com/banuta/lixu.git
cd lixu
pip install .
aicolors
```

Sau dublu-click pe `start-aicolors.bat` (pornește fără nicio fereastră `cmd`).

## Lângă ceas

AI Colors stă în bara de lângă ceas, fără ferestre `cmd`:

* **click** pe iconiță: deschide fereastra cu setări (o poți închide oricând, AI Colors rulează mai departe);
* **click dreapta**: Deschide, **Pauză lumini** (dispozitivele revin la efectele lor), **Pornește odată
  cu Windows**, **Ieșire**;
* tooltip-ul arată dacă CS2 e conectat și câte dispozitive merg;
* primești o notificare când bateria mouse-ului sau a căștilor scade sub 15%.

Dublu-click pe `AIColors.exe` deschide și fereastra; dacă AI Colors rulează deja, doar o deschide.
Pornit cu Windows (bifa din meniu sau din Setări -> Pornire), apare direct lângă ceas, fără fereastră.
Din linia de comandă: `aicolors app --tray` (doar lângă ceas), `aicolors app --no-tray` (fără iconiță).

Fiecare dispozitiv are firul lui de lucru: un dispozitiv care nu răspunde (bec oprit, mouse adormit)
nu mai blochează interfața sau celelalte lumini.

## Interfața

| Tab | Ce poți face |
|---|---|
| **Live** | starea jocului (viață, armură, gloanțe, bombă), ce afișează fiecare dispozitiv chiar acum, și butoane de **simulare** (bombă, flash, mort ...) ca să vezi efectele fără CS2 |
| **Dispozitive** | **Scanează** (tastatură, placă de bază, memorii RAM, Logitech, WLED, Govee, Tuya, OpenRGB) și adaugă cu un click; pentru fiecare dispozitiv: activ, nume, efect, luminozitate, **Identifică** (se aprinde roșu/verde/albastru/alb), ordinea, JSON avansat |
| **Mouse & căști** | baterie (procent, se încarcă, tensiune), **DPI**, **polling rate**, mod host/onboard, „aplică la fiecare pornire” |
| **Culori** | culorile pentru T, CT, bombă, armură, kill, headshot etc. |
| **Setări** | FPS, luminozitate globală, port GSI și token, **Instalează cfg în CS2**, editor JSON, oprire |

Totul se salvează în `aicolors.json` și se aplică imediat, fără restart.

## Pregătirea fiecărui dispozitiv

* **CS2**: în Setări apasă **Instalează cfg în CS2** (sau `aicolors install-cfg`), apoi repornește CS2.
* **ZENKABEAT**: închide aplicația originală (și din tray) și conectează tastatura prin cablu.
  Unele modele (ca „BY Tech Gaming Keyboard” 05AC:024F) nu au culori live; pentru ele AI Colors
  **schimbă efectul tastaturii** după situația din joc (meniu, CT, T, bombă, mort, viață mică).
  Alegi efectele în **Dispozitive -> Efectele tastaturii ZENKABEAT**, cu butonul **Încearcă**.
  Scrie un singur byte (0xB60D, același pe care îl scrie tasta Fn), doar la schimbarea situației,
  cel mult o dată la 3 secunde, și pune înapoi efectul tău la închidere.
* **WLED**: nimic special, doar aceeași rețea. Când AI Colors se oprește, banda revine singură la
  efectul ei după 2 secunde.
* **Govee**: în Govee Home -> dispozitiv -> setări -> activează **LAN Control**.
  Pentru benzi RGBIC (ex. H619A) poți controla **segmentele** separat și le poți **grupa**;
  vezi [Govee: segmente și grupuri](#govee-segmente-și-grupuri).
* **Tuya / Smart Life**: vezi [mai jos](#becuri-tuya--smart-life).
* **Logitech, lumini**: **nu ai nevoie de G HUB**. Fără G HUB, AI Colors vorbește direct cu
  mouse-ul și căștile prin HID++ (ca Solaar). Dacă G HUB e totuși pornit, folosește SDK-ul lui
  (atunci activează în G HUB „Allow games & applications to control my illumination”).
* **Logitech, baterie / DPI / polling**: funcționează cu sau fără G HUB. Dacă G HUB e pornit,
  își poate aplica propriul profil (și per joc) peste DPI-ul setat de AI Colors. Atunci setează
  aceleași valori și în G HUB, sau bifează **Mod host** în AI Colors (mouse-ul nu mai folosește
  profilurile din memoria lui).
* **Placa de bază**: în **Setări -> OpenRGB** apasă **Descarcă OpenRGB** (din sursa oficială),
  apoi **Pornește OpenRGB (administrator)**. Se pornește minimizat, cu serverul activ. Bifează
  „pornește OpenRGB odată cu AI Colors” ca să nu mai faci asta de fiecare dată.
  Din linia de comandă: `aicolors openrgb install`, apoi `aicolors openrgb start`.
* **Memorii Kingston FURY RGB**: tot prin OpenRGB, ca placa de bază. Închide **Kingston FURY CTRL**,
  dacă îl ai. În OpenRGB apar ca „Kingston Fury DDR4/DDR5 DRAM”, câte una pe plăcuță; AI Colors le
  ia pe toate ca un singur dispozitiv (`"device_type": "dram"`). Cu efectul `health`, bara de viață
  se întinde peste toate plăcuțele.

## Becuri Tuya / Smart Life

**Da, se poate**, local, fără cloud la fiecare comandă. Becurile Tuya ascultă în rețea (portul
6668), dar comenzile sunt criptate cu o **cheie locală** unică per bec. Cheia se obține **o
singură dată** din contul tău Tuya:

1. Fă-ți cont gratuit pe [iot.tuya.com](https://iot.tuya.com) și creează un *Cloud Project*
   (Smart Home, data center Europa).
2. La *Devices -> Link App Account*, scanează QR-ul cu aplicația Smart Life. Becurile apar în proiect.
3. Din proiect (*Overview*) copiezi **Access ID** și **Access Secret** în AI Colors, la
   **Setări -> Tuya / Smart Life**, și apeși **Ia cheile din contul Tuya**. Cheile becurilor se
   salvează în `devices.json`, în folderul aplicației; Access ID/Secret nu se salvează.
   (Merge și varianta clasică: `python -m tinytuya wizard`.)
4. În AI Colors: **Dispozitive -> Scanează**. Becurile apar cu „+ Adaugă”.

Biblioteca `tinytuya` e inclusă în `AIColors.exe` și se instalează automat cu `pip install .`.

Limitări reale:
* Becurile Tuya acceptă doar câteva comenzi pe secundă. AI Colors le trimite doar culoarea de
  ambient (echipă, bombă, flash), de maxim 4 ori pe secundă. Nu vor fi la fel de rapide ca WLED.
* Dacă reîmperechezi un bec în Smart Life, cheia se schimbă: apasă din nou „Ia cheile”.
* Alternativă mai rapidă pentru unele becuri: firmware alternativ (OpenBeken / ESPHome).

## OpenRGB: zone separate (benzi pe conectorii plăcii)

O placă de bază are mai multe zone: LED-urile de pe placă și conectorii ARGB (pe Gigabyte
`D_LED1`, `D_LED2`). Cu `"zone"` fiecare linie controlează doar zona ei, cu efectul ei:

```json
{"type": "openrgb", "match": "B550M AORUS ELITE", "zone": "D_LED1", "effect": "health", "name": "Banda 1"}
{"type": "openrgb", "match": "B550M AORUS ELITE", "zone": "D_LED2", "effect": "ambient", "name": "Banda 2"}
```

`zone` e numele zonei (sau doar o parte din el) sau numărul ei. Numele exacte apar la
**Dispozitive -> Scanează**, câte un rând pe zonă, sau în OpenRGB. Dacă o zonă ARGB are 0 LED-uri,
în OpenRGB dă click dreapta pe zonă -> **Resize Zone**, pune numărul de LED-uri al benzii și
apasă **Save Profile**.

## Govee: segmente și grupuri

Le scrii direct în `aicolors.json` (sau în interfață: Dispozitive -> JSON la rândul Govee).
Câte o linie per dispozitiv:

```json
{"type": "govee", "host": "192.168.68.70", "effect": "ambient"}
{"type": "govee", "host": "192.168.68.70", "segments": 15, "effect": "health"}
{"type": "govee", "host": "192.168.68.70", "segments": 15, "groups": [[0,1,2],[3,4,5,6],[7,8],[9,10,11,12,13,14]], "effect": "health"}
{"type": "govee", "hosts": ["192.168.68.70", "192.168.68.80"], "effect": "ambient", "name": "Govee living"}
```

| Câmp | Ce face |
|---|---|
| `segments` | numărul de segmente ale benzii; fiecare segment primește culoarea lui (modul DreamView din API-ul LAN) |
| `groups` | listă de grupuri de segmente (numerotate de la 0); fiecare grup e o „lumină”: cu `health`, bara de viață merge pe grupuri, în ordinea scrisă |
| `hosts` | mai multe dispozitive Govee controlate împreună, ca un grup din aplicația Govee |
| `gradient` | `true` = Govee face trecere lină între segmente (implicit: fiecare segment culoarea lui) |
| `device_brightness` | luminozitatea dispozitivului, 1-100 |

H619A are 20 de segmente (la scanare se completează singur). Segmentele care nu apar în niciun grup
rămân stinse. Fără `segments`, toată banda are o singură
culoare (comanda clasică `colorwc`). Când AI Colors se oprește, banda iese din modul pe segmente
și revine la ce avea.

## Config (`aicolors.json`)

Se editează din interfață, dar e și un fișier simplu. Exemplu: [aicolors.example.json](aicolors.example.json).

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
| `aicolors` / `aicolors app` | aplicația cu fereastră |
| `aicolors run` | la fel, fără fereastră (interfața rămâne la http://127.0.0.1:3001) |
| `aicolors scan --write-config aicolors.json` | caută dispozitivele |
| `aicolors identify` | aprinde pe rând fiecare dispozitiv |
| `aicolors battery` | bateria mouse-ului și căștilor |
| `aicolors mouse --dpi 1600 --rate 1000` | DPI și polling rate (`--host-mode on/off`) |
| `aicolors install-cfg` | cfg-ul GSI în CS2 |
| `aicolors test` | test detaliat pentru tastatura ZENKABEAT |
| `aicolors demo --dry-run --preview` | rundă simulată, desenată în terminal |

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
