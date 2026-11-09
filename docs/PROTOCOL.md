# Protocolul HID ZENKABEAT (OEM „916RGB”)

Aflat prin reverse engineering pe `OemDrv.exe` din `ZENKABEAT_Keyboard_Setup_V1.0_20220823.exe`
(Inno Setup 5.3.3, extras cu `innoextract`). Adresele de mai jos sunt din `OemDrv.exe`
(PE32, image base 0x400000).

Aplicația originală **nu are suport pentru CS2 GSI**: nu importă `ws2_32.dll`, nu are server
HTTP. Folosește rețeaua doar pentru update (`URLDownloadToFileW` -> `update_version.xml`,
`Update.exe`). „Game mode” înseamnă doar preseturi de taste aprinse (`GaoshouKey1..5` din `Cfg.ini`).

## Identificare

| Câmp | Valoare | Sursă |
|---|---|---|
| VID | `0x05AC` | `Cfg.ini` `[KB] VID` |
| PID | `0x024F` | `Cfg.ini` `[KB] PID` |
| Clasa driver | `CDrv916RGB` / `CDev916RGB` | `K916RGB=1` |

## Interfețe (`CDrv916RGB::FindDev`, 0x41a560)

Enumerare cu `SetupDi*` + `HidP_GetCaps`. Toate colecțiile vendor au UsagePage `0xFF00`, Usage `1`;
se deosebesc după `FeatureReportByteLength`:

| FeatureLen | Handle | Folosire |
|---|---|---|
| `0x408` (1032) | `hDevice` (+0x28) | blocuri mari: profiluri, matrice taste, macro, tabele RGB (report ID 6) |
| `6` | `hCmd` (+0x2c) | comenzi scurte (report ID 5), ex. GetPassword `05 81 ...` |
| `0x17E` (382) | `hMusic` (+0x44) | **cadre LED în timp real** (report ID 8) |
| UsagePage `0x0C` | `hMedia` | consumer control (taste media) |

Fiecare `HidD_SetFeature`/`HidD_GetFeature` e reîncercat de 3 ori cu pauză de 200 ms.

## Cadru LED în timp real (`SendMusicData`, 0x41b440)

```
HidD_SetFeature(hMusic, buf, 382)
buf[0..3]   = 08 0A 7A 01
buf[4..381] = 378 bytes = 126 LED x 3 canale
```

* LED-ul `i` ocupă `buf[4 + i*3 + RGBIndex[c]]` pentru canalul `c` (R, G, B), cu
  `RGBIndex` din `Cfg.ini` (implicit `0,1,2`). Culorile sunt COLORREF (byte-ul mic = roșu).
  Construcția cadrului e în bucla modului Music de la 0x46b3c9.
* Indexul LED = `col * 6 + rând` (21 coloane x 6 rânduri). Rândul 0 (F1-F12) nu există pe layout-ul 68%.
* Citire inversă (`ReadEffectData`, 0x41b510): `HidD_GetFeature(hMusic, [08 15 ...], 382)`.

Ăsta e canalul folosit de AI Colors: nu scrie nimic în flash, doar afișează.

## Maparea tastelor (`Cfg.ini`, `[KBKEY]`, parser 0x498310)

```
K<n> = x1,y1,x2,y2, tip, VK, 0, LED, RGBTAB
```

* `LED` -> câmpul +0x14 al structurii de tastă (bază 0x684c58, pas 0x58), index în cadrul live.
* `RGBTAB` -> câmpul +0x4C, index în tabela de culori salvată (`rând * 21 + col`).

Tabelul complet e în `aicolors/layout.py`.

## Culori salvate per tastă (doar referință, nefolosit de AI Colors)

Varianta `CDev916` (0x419d0b): `HidD_SetFeature(h, buf, 380)` cu `buf[0]=0x0B`,
`buf[1]=slot`, apoi trei planuri de câte 126 bytes R, G, B indexate după `RGBTAB`.
Pentru `CDev916RGB` salvarea merge prin `SetLedRgbTab` / `SetLedMatrix` pe `hDevice`.
