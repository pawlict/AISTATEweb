"""Offline map tile server — serves tiles from MBTiles (SQLite) files.

MBTiles is a SQLite database with tables:
    metadata: name, format, bounds, etc.
    tiles: zoom_level, tile_column, tile_row, tile_data (BLOB)

Tile coordinates follow TMS convention (Y-axis flipped vs. XYZ/slippy map).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


class TileServer:
    """Serves map tiles from an MBTiles file."""

    def __init__(self, mbtiles_path: Path):
        self.path = mbtiles_path
        self._conn: Optional[sqlite3.Connection] = None
        self._metadata: Optional[Dict[str, str]] = None

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            if not self.path.exists():
                raise FileNotFoundError(f"MBTiles file not found: {self.path}")
            self._conn = sqlite3.connect(str(self.path), timeout=10)
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def get_metadata(self) -> Dict[str, str]:
        """Read MBTiles metadata table."""
        if self._metadata is not None:
            return self._metadata
        conn = self._get_conn()
        rows = conn.execute("SELECT name, value FROM metadata").fetchall()
        self._metadata = {row[0]: row[1] for row in rows}
        return self._metadata

    def get_tile(self, z: int, x: int, y: int) -> Optional[bytes]:
        """Get a single tile by z/x/y coordinates.

        Handles TMS ↔ XYZ y-axis flip.

        Args:
            z: Zoom level.
            x: Tile column (X).
            y: Tile row (Y) in XYZ/slippy convention.

        Returns:
            Tile data bytes (PBF for vector, PNG/JPEG for raster) or None.
        """
        conn = self._get_conn()
        # MBTiles uses TMS convention: y is flipped
        tms_y = (1 << z) - 1 - y

        row = conn.execute(
            "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
            (z, x, tms_y),
        ).fetchone()

        if row:
            return row[0]
        return None

    def get_format(self) -> str:
        """Return tile format: 'pbf', 'png', 'jpg', or 'unknown'."""
        meta = self.get_metadata()
        fmt = meta.get("format", "").lower()
        if fmt in ("pbf", "png", "jpg", "jpeg", "webp"):
            return fmt

        # Try to detect from a sample tile
        conn = self._get_conn()
        row = conn.execute(
            "SELECT tile_data FROM tiles LIMIT 1"
        ).fetchone()
        if row and row[0]:
            data = row[0]
            if data[:2] == b"\x1f\x8b":  # gzip (PBF)
                return "pbf"
            if data[:4] == b"\x89PNG":
                return "png"
            if data[:2] == b"\xff\xd8":
                return "jpg"
        return "unknown"

    def get_info(self) -> Dict[str, Any]:
        """Get tile server info."""
        if not self.exists:
            return {"available": False}

        try:
            meta = self.get_metadata()
            fmt = self.get_format()
            conn = self._get_conn()
            tile_count = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]

            return {
                "available": True,
                "path": str(self.path),
                "size_mb": round(self.path.stat().st_size / 1048576, 1),
                "format": fmt,
                "name": meta.get("name", ""),
                "description": meta.get("description", ""),
                "bounds": meta.get("bounds", ""),
                "center": meta.get("center", ""),
                "minzoom": meta.get("minzoom", ""),
                "maxzoom": meta.get("maxzoom", ""),
                "tile_count": tile_count,
            }
        except Exception as e:
            log.warning("Error reading MBTiles info: %s", e)
            return {"available": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_server: Optional[TileServer] = None


def get_tile_server(data_dir: Optional[Path] = None) -> TileServer:
    """Get or create the default tile server instance."""
    global _default_server
    if _default_server is not None:
        return _default_server

    if data_dir is None:
        import os
        data_dir = Path(os.environ.get("AISTATEWEB_DATA_DIR", "data_www"))

    mbtiles_path = data_dir / "gsm" / "map.mbtiles"
    _default_server = TileServer(mbtiles_path)
    return _default_server
