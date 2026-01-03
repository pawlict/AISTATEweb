# AISTATEweb (1.0 beta)

**AISTATEweb** (Artificial Intelligence Speech‑To‑Analysis‑Translation Engine) to webowa wersja narzędzia do:
- transkrypcji audio (OpenAI Whisper),
- diaryzacji mówców (pyannote.audio),
- pracy „projektowej” (źródłowy plik audio + wyniki + raporty),
- generowania raportów (HTML/TXT/PDF).

Repozytorium zawiera **wyłącznie** wersję WWW (bez starego GUI/Qt).

---

## Funkcje

- ✅ **Nowy projekt**: nazwa projektu + wybór pliku audio (trzymany w projekcie)
- ✅ **Transkrypcja**: Whisper (modele od szybkich po dokładniejsze)
- ✅ **Diaryzacja**: pyannote.audio (wymaga tokena Hugging Face)
- ✅ **Logi**: podgląd i kopiowanie treści
- ✅ **Raporty**: HTML / TXT / PDF (z metadanymi projektu)

---

## Wymagania

- Python 3.10+ (zalecane 3.11/3.12)
- `ffmpeg` w systemie (`ffmpeg -version`)
- (Opcjonalnie) GPU CUDA dla szybszej pracy modeli

---

## Instalacja (Linux / Kali)

```bash
git clone https://github.com/pawlict/AISTATEweb.git
cd AISTATEweb

python3 -m venv .venv
source .venv/bin/activate

pip install -U pip
pip install -r requirements.txt
```

**FFmpeg (Debian/Kali/Ubuntu):**
```bash
sudo apt update
sudo apt install -y ffmpeg
```

---

## Uruchomienie

```bash
python3 run_www.py
```

Domyślnie aplikacja startuje pod: `http://127.0.0.1:8000`

### Zmienne środowiskowe

- `AISTATEWEB_HOST` (domyślnie `0.0.0.0`)
- `AISTATEWEB_PORT` (domyślnie `8000`)
- `AISTATEWEB_DATA_DIR` (domyślnie `./data_www`) – gdzie trzymane są projekty i pliki

Przykład:
```bash
AISTATEWEB_HOST=127.0.0.1 AISTATEWEB_PORT=8080 python3 run_www.py
```

---

## Struktura projektu

```
AISTATEweb/
  backend/          logika: projekty, taski, adaptery (Whisper/pyannote)
  webapp/           FastAPI + templates + static
  generators/       generatory raportów HTML/TXT/PDF
  assets/           fonty do PDF
  docs/             treści zakładki Info (Markdown)
  run_www.py        uruchomienie serwera
  requirements.txt  zależności
```

---

## Rozwiązywanie problemów

### 1) `FileNotFoundError: ffmpeg`
Zainstaluj `ffmpeg` i upewnij się, że jest w PATH:
```bash
ffmpeg -version
```

### 2) Diaryzacja „nic nie robi”
Najczęściej brak tokena HF lub model nie ma uprawnień. Ustaw token w zakładce **Ustawienia** (Hugging Face).

### 3) CPU: „FP16 is not supported”
To normalne na CPU – Whisper przełącza się na FP32.

---

## Licencja

MIT License (AS IS) – zob. plik `LICENSE`.

---

## English (short)

AISTATEweb is a web-first tool for audio transcription (Whisper) and speaker diarization (pyannote.audio),
with project-based workflow and report export (HTML/TXT/PDF). Licensed under MIT (AS IS).
