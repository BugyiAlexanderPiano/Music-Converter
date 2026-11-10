# AuraWave Genos Studio Pro

Stílus- és sample-műhely **Yamaha Genos 2**-höz. Futurisztikus, animált főablak,
három külön ablakban nyíló modullal.

| Modul | Mit tud |
|---|---|
| **Style Studio** | MIDI (és MIDI-adatot tartalmazó Roland STL) → Genos 2 `.STY`, egyedi ütemvágással szekciónként (Intro / Main / Fill / Break / Ending). A velocity-t bitpontosan átviszi, és a kész fájlt hangról hangra visszaellenőrzi. |
| **Precíziós Sample Vágó** | WAV minták mintapontos vágása nullátmeneten (zero-crossing). A vágás közvetlenül a tranziens elé kerül, így a minta késés nélkül szólal meg. Kötegelt (mappás) vágást is tud. |
| **Smart Looper & Key Mapper** | Automatikus loop-pont keresés és crossfade, hangmagasság-felismerés, okos fájlnevek (pl. `C3_Strings_Loop_Clean.wav`), billentyűzóna-térkép és `KeyMap.csv`. A loop-pontokat a WAV `smpl` chunkjába írja, ahonnan a Yamaha Expansion Manager beolvassa őket. |

## ⬇ Letöltés – nem kell hozzá Python

Kattints a gépednek megfelelő linkre, és nyisd meg a letöltött fájlt:

| Gép | Letöltés |
|---|---|
| **Windows 10 / 11** | [AuraWave-Windows.exe](https://github.com/BugyiAlexanderPiano/Music-Converter/releases/latest/download/AuraWave-Windows.exe) |
| **Windows 7** | [AuraWave-Windows7.exe](https://github.com/BugyiAlexanderPiano/Music-Converter/releases/latest/download/AuraWave-Windows7.exe) |
| **Mac M1 / M2 / M3 / M4** | [AuraWave-Mac-AppleSilicon.zip](https://github.com/BugyiAlexanderPiano/Music-Converter/releases/latest/download/AuraWave-Mac-AppleSilicon.zip) |
| **Mac Intel** | [AuraWave-Mac-Intel.zip](https://github.com/BugyiAlexanderPiano/Music-Converter/releases/latest/download/AuraWave-Mac-Intel.zip) |

**Az első megnyitáskor** a rendszer figyelmeztetést mutat, mert a program nincs
hivatalos fejlesztői tanúsítvánnyal aláírva. Ez egyszeri lépés:

* **Windows:** „A Windows megvédte a számítógépet” → **További információ** →
  **Futtatás mindenképp**.
* **Mac:** csomagold ki a zip-et, és húzd a programot az Alkalmazások mappába. Kattints
  rá jobb gombbal, majd **Megnyitás** → **Megnyitás**. Újabb macOS-en előfordulhat, hogy
  ez nem elég: ilyenkor menj a **Rendszerbeállítások → Adatvédelem és biztonság**
  menübe, és ott kattints a **Megnyitás mindenképp** gombra.

## Gyors indítás forráskódból (dupla kattintás)

| Rendszer | Indítófájl |
|---|---|
| Windows 11 / 10 / 8.1 / 7 | `INDITAS_WINDOWS.bat` |
| macOS | `INDITAS_MAC.command` (ha a Mac nem engedi megnyitni: jobb klikk → Megnyitás → Megnyitás) |

Az indítófájl ellenőrzi, hogy van-e megfelelő Python a gépen. Ha nincs, megnyitja a
letöltési oldalt, Windows 10/11-en pedig a `winget` segítségével magától telepíti. Az első
indításkor feltelepíti a numpy csomagot, ehhez egyszer kell internet. Utána csak elindítja
a programot.

* **Windows 7:** a Python **3.8.10** az utolsó verzió, ami fut rajta. A bat fájl ezt a
  letöltést nyitja meg.
* **Windows XP / Vista:** nem támogatott, mert ezeken a rendszereken a program által
  igényelt Python 3.8 és a numpy nem telepíthető.
* Python telepítésekor Windowson pipáld be az **„Add python.exe to PATH”** és a
  **„tcl/tk and IDLE”** opciót.

## Telepítés és futtatás kézzel

Python 3.8 vagy újabb kell hozzá. A grafikus felület a beépített `tkinter`-t használja.

```bash
pip install -r requirements.txt     # egyetlen kötelező csomag: numpy
python main.py
```

* **Windows / macOS:** a python.org-ról letöltött Python már tartalmazza a `tkinter`-t.
* **Linux:** `sudo apt install python3-tk`.
* Nem kötelező: `pip install sounddevice` a jobb előhallgatáshoz. Enélkül Windows-on a
  `winsound`, macOS-en az `afplay`, Linuxon az `aplay`/`paplay` szólaltatja meg a mintákat.

Tesztek: `python tests/test_engine.py`

## Használati tippek a Genos 2-höz

### Style Studio
1. Töltsd be a MIDI-t. A program automatikusan kiosztja a csatornákat: a dob a Ch 10-re
   (Rhythm 2), a basszus a Ch 11-re, a többi szólam a Ch 12–16-ra kerül. A kiosztást
   kézzel is módosíthatod.
2. Add meg a szekciókat a kezdő és záró ütemmel. Mindkét ütem beleszámít a szekcióba.
   Az ütemeket az alsó kottasávon egérrel húzva is kijelölheted.
3. Konvertálás után másold a `.sty` fájlt USB-re, a Genosön pedig nyisd meg:
   **STYLE → USB**.
4. A program CASM (akkordkezelési) blokkot nem ír, ezért a Genos a gyári alapértékeket
   használja, amelyekben a forrásakkord **C Maj7**. A dallamos szólamokat ezért C Maj7
   akkordra érdemes felvenni. Az akkordkezelést a hangszeren a **Style Creator →
   Channel / Parameter** menüben finomíthatod, és onnan mentve a Genos maga írja meg a
   pontos CASM-et.

**Roland STL:** a formátum zárt és nem dokumentált. Ha az STL fájlban van szabványos
MIDI-adat, a program közvetlenül beolvassa. Ha nincs, akkor a Roland hangszerről vagy
szoftverből exportáld a stílust MIDI-be, és azt töltsd be.

### Precíziós Sample Vágó
* A **„0 ms latency”** itt azt jelenti, hogy a minta elején nincs csend: a vágás az első
  hallható tranziens előtti utolsó nullátmenetre kerül. A program kiírja a vágás és a
  tranziens közti maradék időt, ami jellemzően 1 ms alatti.
* A fade-in alapértéke 0 ms, hogy a tranziens éles maradjon. Kattanás ennek ellenére
  sincs, mert a vágás nullpontra esik.

### Smart Looper
* A loop-pontokat emelkedő nullátmeneteken keresi, keresztkorrelációval. A crossfade a
  loop végén a loop-start előtti anyagba úszik át, így az ugrás folytonos.
* Mentéskor a program megkérdezi, hová mentsen, és felajánlja az okos fájlnevet. Az
  alaphang Yamaha oktávszámozás szerint szerepel benne (középső C = **C3**).
* A loopolt WAV-okat a **Yamaha Expansion Manager**-be húzva a loop-pontok és az
  alaphang automatikusan átjönnek. A `KeyMap.csv` megmutatja, melyik minta melyik
  billentyűzónára kerüljön.
