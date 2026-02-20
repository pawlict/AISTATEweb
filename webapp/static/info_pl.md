# AISTATE Web — Informacje

**AISTATE Web** (*Artificial Intelligence Speech‑To‑Analysis‑Translation‑Engine*) to aplikacja WWW do transkrypcji, diarizacji, tłumaczeń.

---

## 🚀 Co potrafi

- **Transkrypcja**  Audio → tekst (Whisper). 
- **Diaryzacja** „kto mówi kiedy” + segmenty mówców. 
- **Tłumaczenia** Tekst → inne języki (NLLB) 
- **Analiza (LLM / Ollama)**  streszczenia, wnioski, raporty 
- **Logi i postęp** podgląd zadań, diagnostyka 

> **Tryb projektu**: AISTATE zapisuje wyniki i metadane tak, aby po ponownym otwarciu projektu widzieć co zostało zrobione (silnik, model, język, format raportu itp.).

---

## 🆕 Nowości w 3.5.1 beta

- **Korekta tekstu** — porównanie oryginału z poprawionym tekstem (diff), wybór modelu (Bielik, PLLuM, Qwen3), tryb rozwinięty.
- **Nowy widok projektów** — karty w siatce, info o zespole, zaproszenia z poziomu karty.
- Drobne poprawki UI i stabilności.

---

## 🆕 Nowości w 3.2 beta

- **Moduł tłumaczeń (NLLB)** – obsługa lokalnych tłumaczeń wielojęzycznych (w tym PL/EN/ZH i inne).
- **Ustawienia NLLB** – wybór modelu, tryb pracy oraz informacje o cache modeli.

---

## 📦 Skąd pobierane są modele

AISTATE web **nie** dołącza modeli do repozytorium. Modele są pobierane „na żądanie” i cache’owane lokalnie (zależnie od modułu):

- **Hugging Face Hub**: pyannote + NLLB (cache w standardowej lokalizacji HF).
- **NVIDIA NGC / NeMo**: modele ASR/diaryzacji NeMo (zależnie od konfiguracji, cache NeMo).
- **Ollama**: modele LLM pobierane przez usługę Ollama.

---

## 🔐 Prywatność i bezpieczeństwo

- Aplikacja jest projektowana pod pracę **lokalnie / self‑hosted**.
- Tokeny (np. Hugging Face) traktuj jak hasła — **nigdy** nie commituj do GitHuba.
- Pamiętaj o ograniczeniach prawnych i regulaminach dostawców modeli (HF/NGC/Meta/Google).

---

## ⚖️ Licencje

### Licencja aplikacji

- **AISTATE Web**: **MIT License** (AS IS).

### Licencje silników / bibliotek (kod)

- **OpenAI Whisper**: **MIT**.  
- **pyannote.audio**: **MIT**.  
- **WhisperX**: **MIT** (wrapper/aligner – licencja zależna od wersji pakietu).  
- **NVIDIA NeMo Toolkit**: **Apache 2.0**.  
- **Ollama (server/CLI, repo)**: **MIT**.

### Licencje modeli (wagi / checkpoints)

> Modele mają **oddzielne licencje** od kodu. Zawsze sprawdzaj kartę modelu / warunki na stronie dostawcy.

- **Meta NLLB‑200 (NLLB)**: **CC‑BY‑NC 4.0** (ograniczenia komercyjne).  
- **pyannote pipelines (HF)**: zależnie od modelu; część jest **gated** (wymaga akceptacji warunków na stronie modelu).  
- **NeMo modele (NGC/HF)**: licencja zależna od modelu; część checkpointów ma własną licencję (np. na HF spotyka się **CC‑BY‑4.0**), a część w NGC bywa „pokryta licencją NeMo Toolkit” — sprawdź stronę danego modelu.  
- **LLM przez Ollama**: licencja zależy od wybranego modelu, np.:
  - **Meta Llama 3**: **Meta Llama 3 Community License** (warunki dystrybucji/atrybucji i AUP).  
  - **Mistral 7B**: **Apache 2.0**.  
  - **Google Gemma**: **Gemma Terms of Use** (warunki umowne + polityka użycia).

### Ważne

- Ta informacja to tylko skrót. W repozytorium są plik typu **THIRD_PARTY_NOTICES.md** z pełniejszym zestawieniem zależności.
- Jeśli używasz AISTATE w organizacji/komercyjnie: sprawdź szczególnie **NLLB (CC‑BY‑NC)** i licencje wybranych modeli LLM.

---

## 💬 Wsparcie / kontakt

Masz bug, sugestię lub feature request? Napisz: **pawlict@proton.me**
