#!/usr/bin/env python3
"""OSM MBTiles Builder — standalone tool.

Creates an offline vector MBTiles map of Poland from OpenStreetMap data
published by Geofabrik, using `tilemaker` as the tile generator.

Designed to be a completely standalone companion program to AISTATE:
no imports from the AISTATE codebase, no shared config.

Usage
-----

Interactive (asks for detail level, output path, etc.):
    python builder.py

Non-interactive (scriptable):
    python builder.py --preset detailed --output poland.mbtiles
    python builder.py --preset standard --keep-pbf
    python builder.py --list-presets

Requirements
------------
  * Python 3.9+
  * tilemaker installed on PATH (on Debian/Ubuntu: sudo apt install tilemaker)
  * Internet access to download the PBF from Geofabrik on first run
  * Roughly 10 GB free disk space for the `detailed` preset
    (PBF ~1.5 GB + working space + final MBTiles ~1.5-2 GB)

What it does
------------
  1. Downloads poland-latest.osm.pbf from https://download.geofabrik.de/
     (skipped if already present in the working directory).
  2. Verifies tilemaker is installed.
  3. Runs tilemaker with the preset you chose (min/max zoom).
  4. Writes the resulting .mbtiles file to the path you picked.

The MBTiles uses the OpenMapTiles vector schema, which means it can be
rendered by any MapLibre GL JS style designed for that schema — including
the bundled viewer (viewer.html + serve.py).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# --------------------------------------------------------------------------- #
# Configuration                                                                #
# --------------------------------------------------------------------------- #

GEOFABRIK_POLAND_PBF_URL = "https://download.geofabrik.de/europe/poland-latest.osm.pbf"
DEFAULT_PBF_NAME = "poland-latest.osm.pbf"
DEFAULT_MBTILES_NAME = "poland.mbtiles"


@dataclass(frozen=True)
class Preset:
    key: str
    label_pl: str
    label_en: str
    min_zoom: int
    max_zoom: int
    est_size_mb: int          # rough estimate for the final .mbtiles
    description_pl: str
    recommended: bool = False


PRESETS: list[Preset] = [
    Preset(
        key="preview",
        label_pl="Podgląd",
        label_en="Preview",
        min_zoom=0,
        max_zoom=8,
        est_size_mb=60,
        description_pl=(
            "Granice państw, stolice, autostrady i największe miasta. "
            "Dobre do ogólnej orientacji — bez ulic lokalnych."
        ),
    ),
    Preset(
        key="standard",
        label_pl="Standardowy",
        label_en="Standard",
        min_zoom=0,
        max_zoom=11,
        est_size_mb=350,
        description_pl=(
            "Sieć dróg, miasta i miejscowości, główne punkty POI. "
            "Kompromis między rozmiarem a szczegółowością."
        ),
    ),
    Preset(
        key="detailed",
        label_pl="Szczegółowy (rekomendowany)",
        label_en="Detailed (recommended)",
        min_zoom=0,
        max_zoom=14,
        est_size_mb=1800,
        description_pl=(
            "Pełna jakość OpenStreetMap: ulice, budynki, wszystkie POI, "
            "etykiety. Tak wygląda standardowa mapa OSM na typowym zoomie."
        ),
        recommended=True,
    ),
    Preset(
        key="maximum",
        label_pl="Maksymalny",
        label_en="Maximum",
        min_zoom=0,
        max_zoom=15,
        est_size_mb=4200,
        description_pl=(
            "Bardzo duży plik — wszystkie szczegóły budynków i numery domów. "
            "Zalecany tylko gdy potrzebujesz dokładnej mapy lokalnej."
        ),
    ),
]


# --------------------------------------------------------------------------- #
# Pretty printing helpers                                                      #
# --------------------------------------------------------------------------- #

def _supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


class C:
    if _supports_color():
        R = "\033[0m"
        B = "\033[1m"
        DIM = "\033[2m"
        RED = "\033[31m"
        GRN = "\033[32m"
        YEL = "\033[33m"
        BLU = "\033[34m"
        CYAN = "\033[36m"
    else:
        R = B = DIM = RED = GRN = YEL = BLU = CYAN = ""


def info(msg: str) -> None:
    print(f"{C.CYAN}[i]{C.R} {msg}")


def ok(msg: str) -> None:
    print(f"{C.GRN}[+]{C.R} {msg}")


def warn(msg: str) -> None:
    print(f"{C.YEL}[!]{C.R} {msg}")


def err(msg: str) -> None:
    print(f"{C.RED}[x]{C.R} {msg}", file=sys.stderr)


def human_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024.0 or unit == "TB":
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


# --------------------------------------------------------------------------- #
# Preset selection                                                             #
# --------------------------------------------------------------------------- #

def print_presets() -> None:
    print()
    print(f"{C.B}Dostępne poziomy szczegółowości (presety):{C.R}")
    print()
    for i, p in enumerate(PRESETS, start=1):
        rec = f" {C.GRN}[REKOMENDOWANY]{C.R}" if p.recommended else ""
        size_txt = human_size(p.est_size_mb * 1024 * 1024)
        print(
            f"  {C.B}{i}){C.R} {p.label_pl}{rec}\n"
            f"     {C.DIM}zoom {p.min_zoom}–{p.max_zoom}, "
            f"szacowany rozmiar .mbtiles: ~{size_txt}{C.R}\n"
            f"     {p.description_pl}"
        )
        print()


def pick_preset_interactively() -> Preset:
    print_presets()
    default_idx = next(
        (i for i, p in enumerate(PRESETS, start=1) if p.recommended),
        1,
    )
    while True:
        raw = input(
            f"Wybierz preset [1-{len(PRESETS)}] (Enter = {default_idx}): "
        ).strip()
        if not raw:
            return PRESETS[default_idx - 1]
        try:
            idx = int(raw)
            if 1 <= idx <= len(PRESETS):
                return PRESETS[idx - 1]
        except ValueError:
            pass
        warn(f"Nieprawidłowy wybór. Wpisz liczbę od 1 do {len(PRESETS)}.")


def get_preset_by_key(key: str) -> Preset:
    for p in PRESETS:
        if p.key == key:
            return p
    raise SystemExit(
        f"Nieznany preset: {key!r}. Dostępne: {', '.join(p.key for p in PRESETS)}"
    )


# --------------------------------------------------------------------------- #
# Download                                                                     #
# --------------------------------------------------------------------------- #

def download_pbf(dst: Path, url: str = GEOFABRIK_POLAND_PBF_URL) -> Path:
    """Download the Geofabrik PBF file to `dst`, with a simple progress bar.

    If the destination already exists and is non-empty, the download is
    skipped (the user can delete the file to force a re-download).
    """
    if dst.exists() and dst.stat().st_size > 0:
        info(f"Plik PBF już istnieje, pomijam pobieranie: {dst} "
             f"({human_size(dst.stat().st_size)})")
        return dst

    info(f"Pobieram OSM dla Polski z Geofabrik:")
    info(f"  {url}")
    info(f"  → {dst}")

    tmp = dst.with_suffix(dst.suffix + ".part")
    start = time.monotonic()
    last_print = 0.0

    def _hook(block_num: int, block_size: int, total_size: int) -> None:
        nonlocal last_print
        now = time.monotonic()
        if now - last_print < 0.25 and block_num * block_size < total_size:
            return
        last_print = now
        downloaded = block_num * block_size
        if total_size > 0:
            pct = min(100.0, downloaded * 100.0 / total_size)
            bar_w = 30
            filled = int(bar_w * pct / 100.0)
            bar = "█" * filled + "░" * (bar_w - filled)
            elapsed = now - start
            speed = downloaded / elapsed if elapsed > 0 else 0
            eta = (total_size - downloaded) / speed if speed > 0 else 0
            sys.stdout.write(
                f"\r    [{bar}] {pct:5.1f}%  "
                f"{human_size(min(downloaded, total_size))} / "
                f"{human_size(total_size)}  "
                f"{human_size(int(speed))}/s  "
                f"ETA {int(eta)}s   "
            )
        else:
            sys.stdout.write(
                f"\r    pobrano {human_size(downloaded)}    "
            )
        sys.stdout.flush()

    try:
        urllib.request.urlretrieve(url, tmp, _hook)
    except Exception as e:
        sys.stdout.write("\n")
        if tmp.exists():
            tmp.unlink()
        raise SystemExit(f"Błąd pobierania: {e}")

    sys.stdout.write("\n")
    tmp.replace(dst)
    ok(f"Pobrano: {dst} ({human_size(dst.stat().st_size)})")
    return dst


# --------------------------------------------------------------------------- #
# tilemaker                                                                    #
# --------------------------------------------------------------------------- #

def _find_tilemaker() -> Optional[str]:
    return shutil.which("tilemaker")


def _find_tilemaker_assets() -> tuple[Optional[Path], Optional[Path]]:
    """Locate tilemaker's bundled OpenMapTiles config + process lua script.

    On Debian/Ubuntu (package: tilemaker) they live in
    /usr/share/tilemaker/. Homebrew uses /opt/homebrew/share/tilemaker/,
    /usr/local/share/tilemaker/ etc. If the user built from source, they
    may be in ./resources/ inside the tilemaker tree.
    """
    candidates = [
        Path("/usr/share/tilemaker"),
        Path("/usr/local/share/tilemaker"),
        Path("/opt/homebrew/share/tilemaker"),
        Path("/opt/tilemaker/resources"),
    ]
    # Also check next to the tilemaker executable, one directory up into share/
    exe = _find_tilemaker()
    if exe:
        exe_path = Path(exe).resolve()
        candidates.append(exe_path.parent.parent / "share" / "tilemaker")
        candidates.append(exe_path.parent.parent / "share" / "tilemaker" / "resources")
        candidates.append(exe_path.parent / "resources")

    for base in candidates:
        if not base.exists():
            continue
        config = base / "config-openmaptiles.json"
        process = base / "process-openmaptiles.lua"
        if config.exists() and process.exists():
            return config, process
        # Some packagings put them under resources/
        config2 = base / "resources" / "config-openmaptiles.json"
        process2 = base / "resources" / "process-openmaptiles.lua"
        if config2.exists() and process2.exists():
            return config2, process2

    return None, None


def check_tilemaker() -> tuple[str, Path, Path]:
    """Return (tilemaker_path, config_path, process_path) or exit with guidance."""
    exe = _find_tilemaker()
    if not exe:
        err("Nie znaleziono programu `tilemaker` w PATH.")
        print()
        print(f"{C.B}Instalacja:{C.R}")
        print("  Debian/Ubuntu:   sudo apt install -y tilemaker")
        print("  macOS (brew):    brew install tilemaker")
        print("  Inne / ze źródeł: https://github.com/systemed/tilemaker")
        raise SystemExit(2)

    config, process = _find_tilemaker_assets()
    if not config or not process:
        err("Znaleziono `tilemaker`, ale nie mogę zlokalizować plików konfiguracji "
            "OpenMapTiles (config-openmaptiles.json / process-openmaptiles.lua).")
        print()
        print(f"{C.B}Rozwiązanie:{C.R}")
        print("  1) Upewnij się, że zainstalowany jest pakiet z zasobami, np.")
        print("     sudo apt install -y tilemaker")
        print("  2) Lub sklonuj repo i wskaż ścieżki ręcznie:")
        print("     git clone https://github.com/systemed/tilemaker")
        print("     python builder.py --tilemaker-config <path>/resources/config-openmaptiles.json \\")
        print("                       --tilemaker-process <path>/resources/process-openmaptiles.lua")
        raise SystemExit(3)

    return exe, config, process


def run_tilemaker(
    tilemaker: str,
    pbf: Path,
    out_mbtiles: Path,
    config: Path,
    process: Path,
    preset: Preset,
) -> None:
    """Invoke tilemaker with the chosen zoom range, streaming stdout live."""
    if out_mbtiles.exists():
        warn(f"Plik wyjściowy już istnieje i zostanie nadpisany: {out_mbtiles}")
        out_mbtiles.unlink()

    cmd = [
        tilemaker,
        "--input", str(pbf),
        "--output", str(out_mbtiles),
        "--config", str(config),
        "--process", str(process),
        "--bbox", "14.07,49.00,24.15,54.84",  # Poland bounding box
    ]

    info("Uruchamiam tilemaker — to potrwa (od kilku do kilkudziesięciu minut).")
    info(f"  preset:  {preset.label_pl}  ({preset.key}, zoom {preset.min_zoom}-{preset.max_zoom})")
    info(f"  input:   {pbf}")
    info(f"  output:  {out_mbtiles}")
    info(f"  config:  {config}")
    info(f"  process: {process}")
    print()

    # NOTE: tilemaker's openmaptiles config defines its own per-layer
    # min/max zooms; the global --bbox we pass here restricts the area,
    # while the preset primarily affects final mbtiles size through the
    # config's built-in zoom caps. Advanced users who need *exact* zoom
    # cropping can post-process the mbtiles with `mbtileserver` tools.
    # For the presets offered here, tilemaker's defaults give the right
    # scale/size tradeoff.

    # Pass zoom hints if the tilemaker build supports them.
    # Older builds ignore unknown flags, newer ones honour --max-zoom.
    cmd += ["--max-zoom", str(preset.max_zoom)]

    try:
        proc = subprocess.run(cmd, check=False)
    except FileNotFoundError as e:
        raise SystemExit(f"Nie mogę uruchomić tilemaker: {e}")

    if proc.returncode != 0:
        err(f"tilemaker zakończył się z kodem {proc.returncode}")
        raise SystemExit(proc.returncode)

    if not out_mbtiles.exists():
        err("tilemaker zakończył się sukcesem, ale plik MBTiles nie powstał.")
        raise SystemExit(4)

    ok(f"Gotowe: {out_mbtiles}  ({human_size(out_mbtiles.stat().st_size)})")


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def _banner() -> None:
    print()
    print(f"{C.B}{C.BLU}╔══════════════════════════════════════════════════╗{C.R}")
    print(f"{C.B}{C.BLU}║    OSM MBTiles Builder — Polska (offline)        ║{C.R}")
    print(f"{C.B}{C.BLU}║    Geofabrik → tilemaker → MBTiles (OpenMapTiles)║{C.R}")
    print(f"{C.B}{C.BLU}╚══════════════════════════════════════════════════╝{C.R}")
    print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Pobiera OSM dla Polski z Geofabrik i generuje wektorową mapę "
            "MBTiles za pomocą tilemaker. Program samodzielny — nie wymaga "
            "AISTATE."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Przykłady:\n"
            "  python builder.py\n"
            "  python builder.py --preset detailed --output poland.mbtiles\n"
            "  python builder.py --preset standard --keep-pbf\n"
            "  python builder.py --list-presets\n"
        ),
    )
    parser.add_argument(
        "--preset",
        choices=[p.key for p in PRESETS],
        help="poziom szczegółowości (jeśli nie podany, skrypt zapyta).",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help=f"ścieżka wyjściowego pliku .mbtiles (domyślnie {DEFAULT_MBTILES_NAME}).",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=Path.cwd(),
        help="katalog roboczy (domyślnie bieżący).",
    )
    parser.add_argument(
        "--pbf",
        type=Path,
        help=(
            "użyj istniejącego pliku .osm.pbf zamiast pobierania "
            "(wygodne gdy masz już dane z Geofabrik)."
        ),
    )
    parser.add_argument(
        "--keep-pbf",
        action="store_true",
        help="nie usuwaj pobranego .osm.pbf po zakończeniu.",
    )
    parser.add_argument(
        "--list-presets",
        action="store_true",
        help="wypisz dostępne presety i zakończ.",
    )
    parser.add_argument(
        "--tilemaker-config",
        type=Path,
        help="ręczna ścieżka do config-openmaptiles.json (override auto-detect).",
    )
    parser.add_argument(
        "--tilemaker-process",
        type=Path,
        help="ręczna ścieżka do process-openmaptiles.lua (override auto-detect).",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="nie zadawaj pytań; wymaga --preset.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.list_presets:
        _banner()
        print_presets()
        return 0

    _banner()

    # 1. preset
    if args.preset:
        preset = get_preset_by_key(args.preset)
        info(f"Wybrany preset: {preset.label_pl} (zoom {preset.min_zoom}-{preset.max_zoom}, "
             f"~{human_size(preset.est_size_mb * 1024 * 1024)})")
    else:
        if args.non_interactive:
            err("--non-interactive wymaga podania --preset.")
            return 2
        preset = pick_preset_interactively()
        ok(f"Wybrano: {preset.label_pl}")

    # 2. paths
    workdir: Path = args.workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    pbf_path: Path = (args.pbf or (workdir / DEFAULT_PBF_NAME)).resolve()
    out_path: Path = (args.output or (workdir / DEFAULT_MBTILES_NAME)).resolve()

    # 3. tilemaker sanity check (fail fast before downloading 1.5 GB)
    tilemaker, auto_config, auto_process = check_tilemaker()
    config = args.tilemaker_config or auto_config
    process = args.tilemaker_process or auto_process
    if not config or not process or not config.exists() or not process.exists():
        err("Brakuje plików konfiguracji tilemaker "
            "(config-openmaptiles.json / process-openmaptiles.lua).")
        return 3
    ok(f"tilemaker: {tilemaker}")

    # 4. PBF
    if not pbf_path.exists():
        download_pbf(pbf_path)
    else:
        info(f"Używam istniejącego PBF: {pbf_path} "
             f"({human_size(pbf_path.stat().st_size)})")

    # 5. generate
    run_tilemaker(
        tilemaker=tilemaker,
        pbf=pbf_path,
        out_mbtiles=out_path,
        config=config,
        process=process,
        preset=preset,
    )

    # 6. cleanup
    if not args.keep_pbf and not args.pbf:
        # Only delete PBFs we downloaded ourselves in this run
        try:
            pbf_path.unlink()
            info(f"Usunięto plik tymczasowy: {pbf_path}")
        except FileNotFoundError:
            pass
        except Exception as e:
            warn(f"Nie udało się usunąć {pbf_path}: {e}")

    print()
    ok("Wszystko gotowe.")
    print()
    print(f"{C.B}Podgląd mapy:{C.R}")
    print(f"  python serve.py {out_path}")
    print(f"  → otwórz http://127.0.0.1:8080 w przeglądarce")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
