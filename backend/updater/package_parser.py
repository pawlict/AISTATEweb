from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from backend.updater.models import UpdateInfo

# Directories that belong to user data — must NEVER be in an update package
_FORBIDDEN_DIRS = {"data_www", ".aistate", ".env", ".git"}

# Directories expected in a valid update package
_EXPECTED_CONTENT = {"webapp", "backend"}

ROOT = Path(__file__).resolve().parents[2]
UPDATES_DIR = ROOT / "_updates"
STAGING_DIR = UPDATES_DIR / "staging"


def parse_update_package(zip_path: Path) -> UpdateInfo:
    """Validate and extract an update .zip package.

    Returns UpdateInfo on success, raises ValueError on failure.
    """
    if not zip_path.exists():
        raise ValueError("Plik aktualizacji nie istnieje")
    if not zipfile.is_zipfile(str(zip_path)):
        raise ValueError("Plik nie jest prawidłowym archiwum ZIP")

    # Clean previous staging
    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(str(zip_path), "r") as zf:
        # Security: check for forbidden content
        names = zf.namelist()
        for name in names:
            top = name.split("/")[0] if "/" in name else name
            if top in _FORBIDDEN_DIRS:
                raise ValueError(
                    f"Paczka zawiera niedozwolony katalog/plik: {top}. "
                    "Aktualizacja nie może zawierać danych użytkownika."
                )

        zf.extractall(STAGING_DIR)

    # Handle case where zip contains a single top-level directory
    staging_contents = list(STAGING_DIR.iterdir())
    actual_staging = STAGING_DIR
    if len(staging_contents) == 1 and staging_contents[0].is_dir():
        actual_staging = staging_contents[0]

    # Validate UPDATE_INFO.json
    info_path = actual_staging / "UPDATE_INFO.json"
    if not info_path.exists():
        shutil.rmtree(STAGING_DIR)
        raise ValueError(
            "Paczka nie zawiera pliku UPDATE_INFO.json. "
            "Nieprawidłowy format paczki aktualizacji."
        )

    try:
        raw = json.loads(info_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        shutil.rmtree(STAGING_DIR)
        raise ValueError(f"Błąd parsowania UPDATE_INFO.json: {e}")

    if not raw.get("version"):
        shutil.rmtree(STAGING_DIR)
        raise ValueError("UPDATE_INFO.json nie zawiera pola 'version'")

    # Validate that package has expected code directories
    has_code = False
    for d in _EXPECTED_CONTENT:
        if (actual_staging / d).is_dir():
            has_code = True
            break
    if not has_code:
        shutil.rmtree(STAGING_DIR)
        raise ValueError(
            "Paczka nie zawiera katalogów z kodem (webapp/, backend/). "
            "Nieprawidłowa paczka aktualizacji."
        )

    # If staging was inside a subdirectory, move contents up
    if actual_staging != STAGING_DIR:
        temp = STAGING_DIR.parent / "_staging_tmp"
        actual_staging.rename(temp)
        shutil.rmtree(STAGING_DIR)
        temp.rename(STAGING_DIR)

    info = UpdateInfo(
        version=raw.get("version", ""),
        min_version=raw.get("min_version", ""),
        changelog=raw.get("changelog", ""),
        migrations=raw.get("migrations", []),
        new_dependencies=raw.get("new_dependencies", []),
        min_python=raw.get("min_python", ""),
        release_date=raw.get("release_date", ""),
    )

    return info


def get_staging_dir() -> Path:
    """Return the staging directory path."""
    return STAGING_DIR


def cleanup_staging() -> None:
    """Remove staging directory."""
    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
    uploaded = UPDATES_DIR / "uploaded.zip"
    if uploaded.exists():
        uploaded.unlink()
