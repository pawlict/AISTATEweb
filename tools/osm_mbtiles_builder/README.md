# OSM MBTiles Builder — Polska (offline)

Samodzielny program, który pobiera dane **OpenStreetMap dla Polski** z
Geofabrik i generuje wektorową mapę offline w formacie **MBTiles**
(schemat **OpenMapTiles**) przy pomocy `tilemaker`.

Jakość mapy jest zbliżona do tej, którą widzisz na
[openstreetmap.org](https://www.openstreetmap.org). Użytkownik wybiera
poziom „ostrości" (szczegółowości), a program dobiera odpowiednie
parametry i szacuje rozmiar wyniku.

Całość jest świadomie **osobnym narzędziem** — nie importuje niczego
z AISTATE i nie wymaga jego konfiguracji.

## Spis treści

- [Wymagania](#wymagania)
- [Szybki start](#szybki-start)
- [Presety szczegółowości](#presety-szczegółowości)
- [Użycie builder.py](#użycie-builderpy)
- [Podgląd mapy (viewer)](#podgląd-mapy-viewer)
- [Struktura katalogu](#struktura-katalogu)
- [Rozwiązywanie problemów](#rozwiązywanie-problemów)
- [Licencje](#licencje)

## Wymagania

- **Python 3.9+** (tylko biblioteka standardowa — nic do instalowania przez pip)
- **tilemaker** — generator kafelków wektorowych
  - Debian/Ubuntu: `sudo apt install -y tilemaker`
  - macOS (Homebrew): `brew install tilemaker`
  - Inne systemy: https://github.com/systemed/tilemaker
- **Miejsce na dysku**: dla presetu *Szczegółowy* potrzeba ok. **10 GB**
  (PBF ~1.5 GB + przestrzeń robocza tilemakera + plik wyjściowy ~1.5–2 GB)
- **Internet** — tylko przy pierwszym uruchomieniu, do pobrania danych OSM
  z Geofabrik (~1.5 GB)

## Szybki start

```bash
cd tools/osm_mbtiles_builder

# Interaktywnie — zapyta o preset
python builder.py

# Albo od razu z parametrem:
python builder.py --preset detailed --output poland.mbtiles

# Podejrzyj wygenerowaną mapę w przeglądarce:
python serve.py poland.mbtiles
# → otwórz http://127.0.0.1:8080
```

Program przeprowadzi Cię przez wszystkie kroki:

1. Wybór presetu szczegółowości (pokaże rekomendację i szacowany rozmiar).
2. Sprawdzenie, czy `tilemaker` jest zainstalowany.
3. Pobranie `poland-latest.osm.pbf` z Geofabrik (z paskiem postępu).
4. Uruchomienie `tilemaker` i wygenerowanie pliku `.mbtiles`.
5. (Opcjonalnie) usunięcie tymczasowego PBF.

## Presety szczegółowości

| Preset | Zoom | Co widać | Szacowany rozmiar `.mbtiles` |
|---|---|---|---|
| **Podgląd** (`preview`) | 0–8 | granice państw, autostrady, duże miasta | ~60 MB |
| **Standardowy** (`standard`) | 0–11 | drogi główne, miasta, główne POI | ~350 MB |
| **Szczegółowy** (`detailed`) ⭐ | 0–14 | ulice, budynki, wszystkie POI — pełne OSM | ~1.8 GB |
| **Maksymalny** (`maximum`) | 0–15 | numery domów, detale budynków | ~4.2 GB |

⭐ **Rekomendowany preset**: `detailed` — daje jakość porównywalną
z otwartą mapą na openstreetmap.org przy akceptowalnym rozmiarze.

Rozmiary są szacunkowe — faktyczny rezultat zależy od zagęszczenia
danych OSM w danym regionie i wersji tilemakera.

## Użycie builder.py

```bash
# Tryb interaktywny (domyślny):
python builder.py

# Wskaż preset z linii poleceń:
python builder.py --preset standard
python builder.py --preset detailed -o /data/maps/poland-detailed.mbtiles

# Użyj już pobranego PBF, nie pobieraj ponownie:
python builder.py --preset detailed --pbf ~/Downloads/poland-latest.osm.pbf

# Zatrzymaj PBF po zakończeniu (domyślnie jest usuwany, jeśli był pobrany):
python builder.py --preset standard --keep-pbf

# W pełni nieinteraktywnie (dobre do skryptów / cronów):
python builder.py --preset standard --output poland.mbtiles --non-interactive

# Wypisz dostępne presety:
python builder.py --list-presets

# Ręcznie wskaż pliki konfiguracji tilemakera
# (gdy auto-detect nie znajduje ich w /usr/share/tilemaker):
python builder.py \
    --preset detailed \
    --tilemaker-config  ~/tilemaker/resources/config-openmaptiles.json \
    --tilemaker-process ~/tilemaker/resources/process-openmaptiles.lua
```

Wszystkie opcje: `python builder.py --help`.

## Podgląd mapy (viewer)

Żeby sprawdzić wynikowy plik, uruchom wbudowany serwer HTTP:

```bash
python serve.py poland.mbtiles
```

Serwer startuje na `http://127.0.0.1:8080` i udostępnia:

- `GET /` — przeglądarka mapy ([MapLibre GL JS](https://maplibre.org/))
- `GET /style.json` — minimalny styl OpenMapTiles bez zewnętrznych czcionek/ikon
  (działa w pełni offline, bez etykiet)
- `GET /tiles/metadata` — metadane TileJSON
- `GET /tiles/{z}/{x}/{y}.pbf` — wektorowe kafelki (gzip)

Inne flagi:

```bash
python serve.py poland.mbtiles --host 0.0.0.0 --port 9000
```

**Uwaga o etykietach**: wbudowany styl (`style.json`) celowo nie
renderuje tekstu, żeby cały podgląd działał bez zewnętrznych zasobów
(fonty `.pbf` z OpenMapTiles są dużym osobnym pakietem). Jeśli chcesz
etykiety miast, ulic itd., ustaw w `style.json`:

```json
"glyphs": "https://fonts.openmaptiles.org/{fontstack}/{range}.pbf"
```

(to wymaga już dostępu do sieci przy rendowaniu).

## Struktura katalogu

```
tools/osm_mbtiles_builder/
├── builder.py        # CLI: pobiera PBF i woła tilemaker
├── serve.py          # prosty serwer HTTP serwujący .mbtiles
├── viewer.html       # MapLibre GL JS viewer
├── style.json        # styl kartograficzny (OpenMapTiles, offline-friendly)
└── README.md         # ten plik
```

Żaden plik nie importuje AISTATE — wrzuć katalog gdziekolwiek,
skopiuj, wysyłaj, i będzie działał samodzielnie.

## Rozwiązywanie problemów

### `Nie znaleziono programu tilemaker w PATH`

Zainstaluj tilemaker:
- Debian/Ubuntu: `sudo apt install -y tilemaker`
- macOS: `brew install tilemaker`

### `Znaleziono tilemaker, ale nie mogę zlokalizować plików konfiguracji OpenMapTiles`

Niektóre paczki instalują tilemakera bez gotowej konfiguracji
OpenMapTiles. Sklonuj repozytorium i wskaż pliki ręcznie:

```bash
git clone https://github.com/systemed/tilemaker ~/tilemaker
python builder.py --preset detailed \
    --tilemaker-config  ~/tilemaker/resources/config-openmaptiles.json \
    --tilemaker-process ~/tilemaker/resources/process-openmaptiles.lua
```

### Pobieranie jest wolne / zerwane

Geofabrik miewa chwilowe spadki. Pobierz plik ręcznie z
https://download.geofabrik.de/europe/poland.html i uruchom builder
z flagą `--pbf`:

```bash
python builder.py --preset detailed --pbf ~/Downloads/poland-latest.osm.pbf
```

### Przeglądarka mapy jest pusta / biała

1. Sprawdź, czy `serve.py` coś wypisuje w konsoli przy poruszaniu mapą
   (powinno logować GET-y do `/tiles/...`).
2. Upewnij się, że `mbtiles` ma dane — `python serve.py plik.mbtiles`
   wypisze `minzoom`/`maxzoom`/`bounds` na starcie.
3. Mapa startuje wycentrowana na Polsce (lat 52.0, lon 19.13) i zoom 6
   — pozbieraj do dużych zoomów, żeby zobaczyć ulice (preset *Podgląd*
   kończy się na z=8).

### tilemaker zjada cały RAM / pada

Tilemaker domyślnie trzyma dużo w pamięci. Dla dużych obszarów lub
niewielu GB RAM użyj mniejszego presetu, np. `standard` zamiast
`detailed`. Można też ograniczyć rozmiar pamięci przez flagi samego
tilemakera — przekaż je modyfikując listę `cmd` w `builder.py`
(funkcja `run_tilemaker`).

## Licencje

- **Dane OSM**: [Open Database License (ODbL)](https://www.openstreetmap.org/copyright).
  Przy publikowaniu map lub raportów zawierających tę mapę **musisz
  podać atrybucję**: „© OpenStreetMap contributors".
- **tilemaker**: [FTWPL](https://github.com/systemed/tilemaker/blob/master/LICENSE)
- **MapLibre GL JS**: [BSD 3-Clause](https://github.com/maplibre/maplibre-gl-js/blob/main/LICENSE.txt)
- **Ten program**: ta sama licencja co projekt AISTATE (MIT).
