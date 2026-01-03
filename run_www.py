#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

def main() -> None:
    host = os.environ.get("AISTATEWEB_HOST") or os.environ.get("AISTATEWWW_HOST") or "0.0.0.0"
    port = int(os.environ.get("AISTATEWEB_PORT") or os.environ.get("AISTATEWWW_PORT") or "8000")
    try:
        import uvicorn
    except Exception:
        print("Brak uvicorn. Zainstaluj: pip install -r requirements.txt", file=sys.stderr)
        raise
    uvicorn.run("webapp.server:app", host=host, port=port, reload=True)

if __name__ == "__main__":
    main()
