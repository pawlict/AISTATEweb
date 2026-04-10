#!/usr/bin/env python3
"""Minimal HTTP server that serves an .mbtiles file as vector tiles
for the MapLibre GL JS viewer (viewer.html).

Standalone — uses only the Python standard library.

Endpoints
---------
    GET /                       -> viewer.html
    GET /style.json             -> style.json (with URLs rewritten to this host)
    GET /tiles/metadata         -> TileJSON derived from mbtiles metadata
    GET /tiles/{z}/{x}/{y}.pbf  -> vector tile (Content-Encoding: gzip)

Usage
-----
    python serve.py poland.mbtiles
    python serve.py poland.mbtiles --port 8080 --host 127.0.0.1

Then open http://127.0.0.1:8080 in a browser.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional


HERE = Path(__file__).resolve().parent
VIEWER_HTML = HERE / "viewer.html"
STYLE_JSON = HERE / "style.json"


# --------------------------------------------------------------------------- #
# MBTiles reader                                                              #
# --------------------------------------------------------------------------- #

class MBTilesReader:
    """Thin read-only wrapper around an .mbtiles SQLite file.

    MBTiles uses the TMS tile scheme (y axis flipped), while MapLibre and
    most XYZ consumers use the standard XYZ scheme. We flip on read.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        # check_same_thread=False because ThreadingHTTPServer shares this
        # connection across request threads; SQLite read-only is safe here.
        self._conn = sqlite3.connect(
            f"file:{path}?mode=ro",
            uri=True,
            check_same_thread=False,
        )
        self._metadata: dict[str, str] = {}
        for k, v in self._conn.execute("SELECT name, value FROM metadata"):
            self._metadata[k] = v

    def metadata(self) -> dict[str, Any]:
        return dict(self._metadata)

    def get_tile(self, z: int, x: int, y: int) -> Optional[bytes]:
        # Flip Y: TMS <-> XYZ
        y_tms = (1 << z) - 1 - y
        row = self._conn.execute(
            "SELECT tile_data FROM tiles "
            "WHERE zoom_level=? AND tile_column=? AND tile_row=?",
            (z, x, y_tms),
        ).fetchone()
        return bytes(row[0]) if row else None

    def tilejson(self, base_url: str) -> dict[str, Any]:
        """Build a TileJSON object from the mbtiles metadata."""
        m = self._metadata
        tj: dict[str, Any] = {
            "tilejson": "3.0.0",
            "name": m.get("name", self.path.stem),
            "description": m.get("description", ""),
            "version": m.get("version", "1.0.0"),
            "attribution": m.get(
                "attribution",
                '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
            ),
            "scheme": "xyz",
            "tiles": [f"{base_url}/tiles/{{z}}/{{x}}/{{y}}.pbf"],
        }
        # bounds, center, minzoom, maxzoom if present
        if "bounds" in m:
            try:
                tj["bounds"] = [float(x) for x in m["bounds"].split(",")]
            except ValueError:
                pass
        if "center" in m:
            try:
                tj["center"] = [float(x) for x in m["center"].split(",")]
            except ValueError:
                pass
        for key in ("minzoom", "maxzoom"):
            if key in m:
                try:
                    tj[key] = int(m[key])
                except ValueError:
                    pass
        # vector_layers come from openmaptiles-generated mbtiles as a json string
        if "json" in m:
            try:
                extra = json.loads(m["json"])
                if "vector_layers" in extra:
                    tj["vector_layers"] = extra["vector_layers"]
            except (json.JSONDecodeError, TypeError):
                pass
        # openmaptiles mbtiles are vector
        if m.get("format", "pbf") == "pbf":
            tj["format"] = "pbf"
        return tj


# --------------------------------------------------------------------------- #
# HTTP handler                                                                 #
# --------------------------------------------------------------------------- #

def make_handler(reader: MBTilesReader):
    class Handler(BaseHTTPRequestHandler):
        server_version = "OSMMBTilesBuilder/1.0"

        # reduce log noise: only print errors + tile counts on demand
        def log_message(self, fmt: str, *args: Any) -> None:
            # Comment out to silence access logs entirely.
            sys.stderr.write(
                f"[{self.log_date_time_string()}] {self.address_string()} - "
                f"{fmt % args}\n"
            )

        # ---- helpers ----
        def _send(self, status: int, body: bytes, content_type: str,
                  extra_headers: Optional[dict[str, str]] = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "public, max-age=3600")
            if extra_headers:
                for k, v in extra_headers.items():
                    self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _send_file(self, path: Path, content_type: str) -> None:
            try:
                body = path.read_bytes()
            except FileNotFoundError:
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
                return
            self._send(HTTPStatus.OK, body, content_type)

        def _base_url(self) -> str:
            host = self.headers.get("Host") or f"127.0.0.1:{self.server.server_port}"
            return f"http://{host}"

        # ---- routing ----
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]

            if path in ("/", "/index.html", "/viewer.html"):
                self._send_file(VIEWER_HTML, "text/html; charset=utf-8")
                return

            if path == "/style.json":
                self._serve_style()
                return

            if path in ("/tiles/metadata", "/tiles/metadata.json", "/tiles.json"):
                self._serve_metadata()
                return

            if path.startswith("/tiles/"):
                self._serve_tile(path)
                return

            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")

        def do_HEAD(self) -> None:
            # same routing, _send already checks self.command
            self.do_GET()

        # ---- endpoints ----
        def _serve_style(self) -> None:
            try:
                style = json.loads(STYLE_JSON.read_text(encoding="utf-8"))
            except FileNotFoundError:
                self._send(HTTPStatus.NOT_FOUND, b"style.json missing",
                           "text/plain")
                return
            except json.JSONDecodeError as e:
                body = f"style.json invalid: {e}".encode("utf-8")
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, body, "text/plain")
                return

            # Rewrite the source URL(s) to point at this server's /tiles endpoint.
            base = self._base_url()
            sources = style.get("sources", {})
            for src in sources.values():
                if isinstance(src, dict) and src.get("type") == "vector":
                    src["tiles"] = [f"{base}/tiles/{{z}}/{{x}}/{{y}}.pbf"]
                    # MBTiles from tilemaker go up to z14 by default
                    meta = reader.metadata()
                    if "maxzoom" in meta:
                        try:
                            src["maxzoom"] = int(meta["maxzoom"])
                        except ValueError:
                            pass
                    if "minzoom" in meta:
                        try:
                            src["minzoom"] = int(meta["minzoom"])
                        except ValueError:
                            pass

            body = json.dumps(style).encode("utf-8")
            self._send(HTTPStatus.OK, body, "application/json; charset=utf-8")

        def _serve_metadata(self) -> None:
            tj = reader.tilejson(self._base_url())
            body = json.dumps(tj).encode("utf-8")
            self._send(HTTPStatus.OK, body, "application/json; charset=utf-8")

        def _serve_tile(self, path: str) -> None:
            # /tiles/{z}/{x}/{y}.pbf  or  /tiles/{z}/{x}/{y}
            rest = path[len("/tiles/"):]
            if rest.endswith(".pbf"):
                rest = rest[:-4]
            elif rest.endswith(".mvt"):
                rest = rest[:-4]
            parts = rest.split("/")
            if len(parts) != 3:
                self._send(HTTPStatus.BAD_REQUEST, b"bad tile path", "text/plain")
                return
            try:
                z, x, y = (int(p) for p in parts)
            except ValueError:
                self._send(HTTPStatus.BAD_REQUEST, b"bad tile coords", "text/plain")
                return

            data = reader.get_tile(z, x, y)
            if data is None:
                # Returning 204 keeps MapLibre quiet when a tile is missing
                # (e.g. over the sea or outside the mbtiles bbox).
                self.send_response(HTTPStatus.NO_CONTENT)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                return

            # openmaptiles tiles are gzip-compressed pbf. Advertise that so
            # the browser decompresses them transparently.
            headers = {"Content-Encoding": "gzip"}
            self._send(
                HTTPStatus.OK,
                data,
                "application/x-protobuf",
                extra_headers=headers,
            )

    return Handler


# --------------------------------------------------------------------------- #
# main                                                                         #
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Serwuje plik .mbtiles (vector) przez HTTP dla wbudowanej "
            "przeglądarki mapy (viewer.html)."
        )
    )
    parser.add_argument("mbtiles", type=Path, help="ścieżka do pliku .mbtiles")
    parser.add_argument("--host", default="127.0.0.1", help="adres nasłuchu")
    parser.add_argument("--port", type=int, default=8080, help="port nasłuchu")
    args = parser.parse_args()

    path: Path = args.mbtiles.resolve()
    if not path.exists():
        print(f"[x] Nie znaleziono pliku: {path}", file=sys.stderr)
        return 2
    if path.suffix.lower() != ".mbtiles":
        print(f"[!] Ostrzeżenie: plik nie ma rozszerzenia .mbtiles ({path.name})",
              file=sys.stderr)

    reader = MBTilesReader(path)
    meta = reader.metadata()
    handler_cls = make_handler(reader)
    server = ThreadingHTTPServer((args.host, args.port), handler_cls)

    print()
    print(f"  OSM MBTiles Viewer — {path.name}")
    print(f"  format:   {meta.get('format', 'pbf')}")
    print(f"  minzoom:  {meta.get('minzoom', '?')}")
    print(f"  maxzoom:  {meta.get('maxzoom', '?')}")
    print(f"  bounds:   {meta.get('bounds', '?')}")
    print()
    print(f"  ▶ Otwórz: http://{args.host}:{args.port}")
    print(f"  (Ctrl+C aby zatrzymać)")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[i] zatrzymuję serwer…")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
