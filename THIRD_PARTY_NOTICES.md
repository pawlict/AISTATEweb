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

### Framework/server (if used in this repository)
- FastAPI — MIT
- Uvicorn — BSD-3-Clause
- PyTorch — BSD-3-Clause

(Exact dependencies and versions are defined in requirements.txt / lock files.)
