## Third-party notices / Licencje komponentów zewnętrznych

This project (AISTATE Web) is licensed under the MIT License (see LICENSE).
It uses third-party libraries and models which are licensed separately.

* * *

### OpenAI Whisper
- Project: openai/whisper
- License: MIT (code and model weights)
- Source: https://github.com/openai/whisper

* * *

### pyannote.audio (speaker diarization)
- Project: pyannote/pyannote-audio
- License: MIT
- Source: https://github.com/pyannote/pyannote-audio

#### pyannote models on Hugging Face
Some diarization models are hosted on the Hugging Face Hub and may be gated.
Access may require:
- Hugging Face account
- accepting model terms/conditions on the model page
- using a Hugging Face access token (READ)

### NLLB (No Language Left Behind) - Translation Models
- Project: Meta AI NLLB-200
- License: CC-BY-NC 4.0 (Creative Commons Attribution-NonCommercial 4.0)
- Source: https://github.com/facebookresearch/fairseq/tree/nllb
- Models on Hugging Face: https://huggingface.co/facebook/nllb-200-distilled-600M (and other variants)

**Important license restrictions:**
- **Non-commercial use only** — Commercial use requires separate licensing from Meta
- Attribution required — Must credit Meta AI and the NLLB project
- Model licenses may vary by specific variant (check each model card on Hugging Face)

**Models commonly used:**
- `facebook/nllb-200-distilled-600M` (600M parameters)
- `facebook/nllb-200-distilled-1.3B` (1.3B parameters)
- `facebook/nllb-200-3.3B` (3.3B parameters)

Model licenses may differ per model repository (e.g., MIT, CC BY 4.0, etc.).
Always check the model card and LICENSE file on the model page before use.

* * *
#### Ollama (local LLM inference)
Project: ollama/ollama

License: MIT
Source: 
https://github.com/ollama/ollama

Ollama models
Models are downloaded from the Ollama library (https://ollama.com/library). Each model has its own license (e.g., Llama 3: Meta License with restrictions on redistribution and use; Codestral: Mistral AI Non-Production License).
​
Licenses are embedded in model files and viewable via ollama show <model> --license or on model pages under Tags > latest > License layer.
​
Always inspect the specific model's license before use, as they vary (e.g., commercial restrictions, attribution requirements).
​
* * *

### Hugging Face Hub (tokens)
- Tokens are managed in: Settings → Access Tokens
- Recommended role for downloads: READ
Never commit tokens to GitHub.

* * *

### FFmpeg (if installed/used for audio decoding)
FFmpeg is licensed under LGPL 2.1+ with optional GPL components.  
If you bundle FFmpeg binaries, you must comply with the license terms of the specific build you ship.
Source: https://www.ffmpeg.org/legal.html

* * *

### Leaflet (interactive maps)
- Project: Leaflet
- License: BSD-2-Clause
- Version used: 1.9.4 (loaded from CDN)
- Source: https://github.com/Leaflet/Leaflet
- Website: https://leafletjs.com

* * *

### MapLibre GL JS (vector map rendering)
- Project: MapLibre GL JS
- License: BSD-3-Clause
- Version used: 4.7.1 (loaded from CDN)
- Source: https://github.com/maplibre/maplibre-gl-js
- Website: https://maplibre.org

* * *

### Leaflet-MapLibre GL (Leaflet ↔ MapLibre bridge)
- Project: @maplibre/maplibre-gl-leaflet
- License: ISC
- Version used: 0.0.22 (loaded from CDN)
- Source: https://github.com/maplibre/maplibre-gl-leaflet

* * *

### OpenStreetMap (map tiles)
- Online map tiles sourced from OpenStreetMap tile servers
- License: Map data © OpenStreetMap contributors, **ODbL 1.0** (Open Database License)
- Tile usage policy: https://operations.osmfoundation.org/policies/tiles/
- Website: https://www.openstreetmap.org
- **Attribution required** — "© OpenStreetMap contributors" must be displayed

* * *

### OpenMapTiles (offline PBF vector tile schema)
- Project: OpenMapTiles
- License: BSD-3-Clause (schema); map data under ODbL
- Source: https://github.com/openmaptiles/openmaptiles
- Website: https://openmaptiles.org

* * *

### html2canvas (DOM screenshots)
- Project: html2canvas
- License: MIT
- Version used: 1.4.1 (loaded from CDN)
- Source: https://github.com/niklasvh/html2canvas

* * *

### Chart.js (charts and data visualization)
- Project: Chart.js
- License: MIT
- Version used: 4.4.1 / 4.4.4 (loaded from CDN — jsdelivr)
- Source: https://github.com/chartjs/Chart.js
- Website: https://www.chartjs.org

* * *

### Cytoscape.js (graph visualization)
- Project: Cytoscape.js
- License: MIT
- Version used: 3.28.1 (loaded from CDN — unpkg)
- Source: https://github.com/cytoscape/cytoscape.js
- Website: https://js.cytoscape.org

* * *

### OSRM (Open Source Routing Machine)
- Project: OSRM
- License: BSD-2-Clause
- Usage: routing API calls to `router.project-osrm.org` (GSM/BTS trip routing)
- Source: https://github.com/Project-OSRM/osrm-backend
- Website: https://project-osrm.org
- API usage policy: https://github.com/Project-OSRM/osrm-backend/wiki/Api-usage-policy

* * *

### Python libraries

| Library | License | Purpose |
|---------|---------|---------|
| FastAPI | MIT | Web framework |
| Uvicorn | BSD-3-Clause | ASGI server |
| PyTorch | BSD-3-Clause | ML inference |
| Transformers (Hugging Face) | Apache-2.0 | Model loading (NLLB, etc.) |
| sentencepiece | Apache-2.0 | Tokenization (NLLB) |
| pandas | BSD-3-Clause | Data analysis (AML, GSM, Crypto) |
| pdfplumber | MIT | PDF text extraction |
| PyMuPDF (fitz) | AGPL-3.0 | PDF rendering and extraction |
| PyPDF2 | BSD-3-Clause | PDF reading |
| reportlab | BSD | PDF report generation |
| Pillow | HPND | Image processing |
| python-docx | MIT | DOCX report generation |
| openpyxl | MIT | XLSX file processing |
| matplotlib | PSF (BSD-compatible) | Chart generation for reports |
| langdetect | Apache-2.0 | Language detection |
| cryptography | Apache-2.0 / BSD-3-Clause | Encryption |
| argon2-cffi | MIT | Password hashing |
| httpx | BSD-3-Clause | Async HTTP client (Ollama) |
| markdown | BSD-3-Clause | Markdown rendering |
| Jinja2 | BSD-3-Clause | HTML templates |

**Note:** PyMuPDF is licensed under **AGPL-3.0**. If you distribute modified binaries, AGPL terms apply.

(Exact dependencies and versions are defined in requirements.txt.)
