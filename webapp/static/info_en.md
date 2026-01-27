# AISTATE Web — Information

**AISTATE Web** (*Artificial Intelligence Speech‑To‑Analysis‑Translation Engine*) is a web app for **transcription**, **speaker diarization**, **translation**.

---

## 🚀 What it does


- **Transcription** Audio → text (Whisper)
- **Diarization** “who spoke when” + speaker segments
- **Translation** Text → other languages (NLLB)
- **Analysis (LLM / Ollama)** summaries, insights, reports
- **Logs & progress** task monitoring + diagnostics

---

## 🆕 What’s new in 3.2 beta

- **Translation module (NLLB)** – local multilingual translation (incl. PL/EN/ZH and more).
- **NLLB settings** – model selection, runtime options, model cache visibility.

---

## 📦 Where models are downloaded from

AISTATE web does **not** ship model weights in the repository. Models are downloaded on-demand and cached locally (depending on the module):

- **Hugging Face Hub**: pyannote + NLLB (standard HF cache).
- **NVIDIA NGC / NeMo**: NeMo ASR/diarization models (NeMo/NGC caching behavior).
- **Ollama**: LLM models pulled by the Ollama service.
---

## 🔐 Privacy & security

- Designed primarily for **local / self-hosted** workflows.
- Treat tokens (e.g., Hugging Face) like passwords — **never** commit them to GitHub.
- Respect legal requirements and model/provider terms (HF/NGC/Meta/Google).

---

## ⚖️ Licensing

### App license

- **AISTATE Web**: **MIT License** (AS IS).

### Engines / libraries (code licenses)

- **OpenAI Whisper**: **MIT**.  
- **pyannote.audio**: **MIT**.  
- **WhisperX**: **MIT** (wrapper/aligner – package-version dependent).  
- **NVIDIA NeMo Toolkit**: **Apache 2.0**.  
- **Ollama (server/CLI repository)**: **MIT**.

### Model licenses (weights / checkpoints)

> Model weights are licensed **separately** from the code. Always verify the model card / provider terms.

- **Meta NLLB‑200 (NLLB)**: **CC‑BY‑NC 4.0** (non-commercial restrictions).  
- **pyannote pipelines (HF)**: model-dependent; some are **gated** and require accepting terms on the model page.  
- **NeMo models (NGC/HF)**: model-dependent; some checkpoints are published under licenses such as **CC‑BY‑4.0**, while some NGC models state coverage under the NeMo Toolkit license — check each model page.  
- **LLMs via Ollama**: model-dependent, for example:
  - **Meta Llama 3**: **Meta Llama 3 Community License** (redistribution/attribution + AUP).  
  - **Mistral 7B**: **Apache 2.0**.  
  - **Google Gemma**: **Gemma Terms of Use** (contractual terms + policy).

### Important

- This page is a summary. Keep a dedicated **THIRD_PARTY_NOTICES.md** in the repository for a complete list.
- For commercial / organizational use, pay special attention to **NLLB (CC‑BY‑NC)** and your chosen LLM model licenses.

---

## 💬 Feedback / support

Issues, suggestions, feature requests: **pawlict@proton.me**
