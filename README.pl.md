# AISTATEweb Community (3.7.2 beta)

[![English](https://flagcdn.com/24x18/gb.png) English](README.md) | [![Polski](https://flagcdn.com/24x18/pl.png) Polski](README.pl.md) | [![한국어](https://flagcdn.com/24x18/kr.png) 한국어](README.ko.md) | [![Español](https://flagcdn.com/24x18/es.png) Español](README.es.md) | [![Français](https://flagcdn.com/24x18/fr.png) Français](README.fr.md) | [![中文](https://flagcdn.com/24x18/cn.png) 中文](README.zh.md) | [![Українська](https://flagcdn.com/24x18/ua.png) Українська](README.uk.md) | [![Deutsch](https://flagcdn.com/24x18/de.png) Deutsch](README.de.md)

![Version](https://img.shields.io/badge/Wersja-3.7.2%20beta-orange)
![Edition](https://img.shields.io/badge/Edycja-Community-blue)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Platform](https://img.shields.io/badge/Platforma-Web-lightgrey)
![License](https://img.shields.io/badge/Licencja-MIT-green)

* * *

AISTATEweb Community to webowe narzędzie do transkrypcji audio, diaryzacji mówców, tłumaczenia, analizy wspieranej AI oraz raportowania — w pełni offline, działające na lokalnym sprzęcie.

#### Kontakt / Wsparcie

Pytania, sugestie lub zgłoszenia błędów: **pawlict@proton.me**

* * *

## 🚀 Główne funkcjonalności

### 🎙️ Przetwarzanie mowy
- Automatyczne rozpoznawanie mowy (ASR) za pomocą **Whisper**, **WhisperX** i **NVIDIA NeMo**
- Obsługa wielojęzycznego audio (PL / EN / UA / RU / BY i inne)
- Wykonanie offline na lokalnych modelach (bez chmury)
- Wysoka jakość transkrypcji zoptymalizowana dla długich nagrań

### 🧩 Diaryzacja mówców
- Zaawansowana diaryzacja za pomocą **pyannote** i **NeMo Diarization**
- Automatyczna detekcja i segmentacja mówców
- Obsługa rozmów wieloosobowych (spotkania, wywiady, rozmowy telefoniczne)
- Konfigurowalne silniki i modele diaryzacji

### 🌍 Tłumaczenie wielojęzyczne
- Neuronowe tłumaczenie maszynowe oparte na **NLLB-200**
- W pełni offline pipeline tłumaczeniowy
- Elastyczny wybór języka źródłowego i docelowego
- Zaprojektowane dla OSINT i wielojęzycznych analiz

### 🧠 Analiza i wywiad
- Analiza treści wspomagana AI z użyciem lokalnych **modeli LLM**
- Transformacja surowej mowy i tekstu w ustrukturyzowane wnioski
- Wsparcie dla raportów analitycznych i przepływów pracy wywiadowczych

### 📱 Analiza GSM / BTS
- Import i analiza **danych billingowych GSM** (CSV, XLSX, PDF)
- Interaktywna **wizualizacja mapowa** lokalizacji BTS (Leaflet + OpenStreetMap)
- Obsługa **map offline** przez MBTiles (raster PNG/JPG/WebP + wektor PBF via MapLibre GL)
- Wiele widoków mapy: wszystkie punkty, trasa, klastry, podróże, zasięg BTS, heatmapa, oś czasu
- **Zaznaczanie obszaru** (koło / prostokąt) dla zapytań przestrzennych
- **Warstwy nakładkowe**: bazy wojskowe, lotniska cywilne, placówki dyplomatyczne (wbudowane dane)
- **Import KML/KMZ** — własne warstwy z Google Earth i innych narzędzi GIS
- Zrzuty ekranu mapy ze znakiem wodnym (mapy online i offline + wszystkie nakładki)
- Graf kontaktów, heatmapa aktywności, analiza top kontaktów
- Odtwarzacz osi czasu z animacją miesięczną/dzienną

### 💰 AML — Analiza finansowa
- Pipeline **Anti-Money Laundering** dla wyciągów bankowych
- Automatyczne wykrywanie banku i parsowanie PDF dla polskich banków:
  PKO BP, ING, mBank, Pekao SA, Santander, Millennium, Revolut (+ generyczny fallback)
- Obsługa formatu MT940 (SWIFT)
- Normalizacja transakcji, klasyfikacja regułowa, scoring ryzyka
- **Wykrywanie anomalii**: baseline statystyczny + ML (Isolation Forest)
- **Analiza grafowa** — wizualizacja sieci kontrahentów
- Analiza wielokontowa dla śledztw wielorachunkowych
- Rozwiązywanie tożsamości i pamięć kontrahentów (etykiety/notatki)
- Analiza wydatków, wzorce behawioralne, kategoryzacja merchant
- Analiza wspomagana LLM (kreator promptów dla modeli Ollama)
- Generowanie raportów HTML z wykresami
- Profile anonimizacji danych do bezpiecznego udostępniania

### 🔗 Crypto — Analiza transakcji blockchain *(eksperymentalne)*
- Offline analiza transakcji **BTC** i **ETH**
- Import z **WalletExplorer.com** CSV i wielu formatów giełdowych (Binance, Etherscan, Kraken, Coinbase i inne)
- Automatyczne wykrywanie formatu na podstawie sygnatur kolumn CSV
- Scoring ryzyka z detekcją wzorców: peel chain, dust attack, round-trip, smurfing
- Baza adresów sankcjonowanych OFAC i znanych kontraktów DeFi
- Interaktywny **graf przepływu transakcji** (Cytoscape.js)
- Wykresy: oś czasu salda, wolumen miesięczny, aktywność dzienna, ranking kontrahentów (Chart.js)
- Analiza narracyjna wspomagana LLM przez Ollama
- *Ten moduł jest w fazie wczesnych testów — funkcje i formaty danych mogą się zmienić*

### ⚙️ Zarządzanie GPU i zasobami
- Wbudowany **GPU Resource Manager**
- Automatyczne planowanie i priorytetyzacja zadań (ASR, diaryzacja, analiza)
- Bezpieczne wykonywanie współbieżnych zadań bez przeciążania GPU
- Fallback na CPU gdy zasoby GPU są niedostępne

### 📂 Przepływ pracy oparty na projektach
- Organizacja danych w projektach
- Trwałe przechowywanie audio, transkrypcji, tłumaczeń i analiz
- Powtarzalne przepływy pracy analitycznej
- Separacja danych użytkownika od procesów systemowych

### 📄 Raportowanie i eksport
- Eksport wyników do **TXT**, **HTML**, **DOC** i **PDF**
- Strukturalne raporty łączące transkrypcję, diaryzację i analizę
- Raporty finansowe AML z wykresami i wskaźnikami ryzyka
- Gotowe do użycia w badaniach, dokumentacji i śledztwach

### 🌐 Interfejs webowy
- Nowoczesny interfejs webowy (**AISTATEweb**)
- Status zadań i logi w czasie rzeczywistym
- Wielojęzyczny interfejs (PL / EN)
- Zaprojektowany dla środowisk jednoosobowych i wieloużytkownikowych (wkrótce)

* * *

## Wymagania

### System (Linux)

Instalacja pakietów bazowych (przykład):
    sudo apt update -y
    sudo apt install -y python3 python3-venv python3-pip git

### Python

Zalecany: Python 3.11+.

* * *
## pyannote / Hugging Face (wymagane do diaryzacji)

Diaryzacja korzysta z pipeline'ów **pyannote.audio** hostowanych na **Hugging Face Hub**. Niektóre modele pyannote są **bramkowane**, co oznacza że musisz:
  * mieć konto Hugging Face,
  * zaakceptować warunki na stronach modeli,
  * wygenerować token dostępu **READ** i podać go w aplikacji.

### Krok po kroku (token + uprawnienia)

  1. Utwórz / zaloguj się na konto Hugging Face.
  2. Otwórz strony wymaganych modeli pyannote i kliknij **„Agree / Accept"** (warunki użytkowania).
     Typowe modele wymagające akceptacji (zależnie od wersji):
     * `pyannote/segmentation` (lub `pyannote/segmentation-3.0`)
     * `pyannote/speaker-diarization` (lub `pyannote/speaker-diarization-3.1`)
  3. Przejdź do **Settings → Access Tokens** i utwórz nowy token z rolą **READ**.
  4. Wklej token w ustawieniach AISTATE Web (lub podaj jako zmienną środowiskową).
* * *
## Instalacja (Linux)

```bash
sudo apt update
sudo apt install -y ffmpeg
curl -fsSL https://ollama.com/install.sh | sh
```
```
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/pawlict/AISTATEweb.git
cd AISTATEweb

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```
* * *

## Uruchomienie
```
python3 AISTATEweb.py
```
Przykład (uvicorn):
    python -m uvicorn webapp.server:app --host 0.0.0.0 --port 8000

Otwórz w przeglądarce:
    http://127.0.0.1:8000

* * *
# AISTATEweb — Windows (WSL2 + NVIDIA GPU)

> **Ważne:** W WSL2 sterownik NVIDIA jest zainstalowany **w Windows**, nie wewnątrz Linuxa. **Nie** instaluj pakietów `nvidia-driver-*` wewnątrz dystrybucji WSL.

---

### 1. Po stronie Windows

1. Włącz WSL2 (PowerShell: `wsl --install` lub Funkcje systemu Windows).
2. Zainstaluj najnowszy **sterownik NVIDIA Windows** (Game Ready / Studio) — to zapewnia obsługę GPU wewnątrz WSL2.
3. Zaktualizuj WSL i zrestartuj:
   ```powershell
   wsl --update
   wsl --shutdown
   ```

### 2. Wewnątrz WSL (zalecane Ubuntu)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3 python3-venv python3-pip ffmpeg
```

Sprawdź czy GPU jest widoczne:
```bash
nvidia-smi
```

### 3. Instalacja AISTATEweb

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/pawlict/AISTATEweb.git
cd AISTATEweb

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel

# PyTorch z CUDA (przykład: cu128)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

pip install -r requirements.txt
```

Weryfikacja dostępu do GPU:
```bash
python -c "import torch; print('CUDA:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
```

### 4. Uruchomienie

```bash
python3 AISTATEweb.py
```
Otwórz w przeglądarce: http://127.0.0.1:8000

### Rozwiązywanie problemów

Jeśli `nvidia-smi` nie działa wewnątrz WSL, upewnij się że **nie** zainstalowałeś pakietów NVIDIA w Linuxie. Usuń je jeśli są:
```bash
sudo apt purge -y 'nvidia-*' 'libnvidia-*' && sudo apt autoremove --purge -y
```

---

## Odnośniki

- [NVIDIA: CUDA on WSL User Guide](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
- [Microsoft: Instalacja WSL](https://learn.microsoft.com/windows/wsl/install)
- [PyTorch: Rozpocznij](https://pytorch.org/get-started/locally/)
- [pyannote.audio (Hugging Face)](https://huggingface.co/pyannote)
- [Whisper (OpenAI)](https://github.com/openai/whisper)
- [NLLB-200 (Meta)](https://huggingface.co/facebook/nllb-200-distilled-600M)
- [Ollama](https://ollama.com/)

---

„Ten projekt jest licencjonowany na MIT (AS IS). Komponenty zewnętrzne mają osobne licencje — zobacz THIRD_PARTY_NOTICES.md."

## beta 3.7.2
- **Panel analityka** — nowy panel boczny zastępujący pasek notatek w transkrypcji i diaryzacji
- **Notatki blokowe z tagami** — notatki mogą mieć kolorowe tagi, wyświetlane jako lewy border na segmentach
- **Revolut crypto PDF** — parser wyciągów kryptowalutowych Revolut, zintegrowany z pipeline AML
- **Baza tokenów (TOP 200)** — klasyfikacja znanych/nieznanych tokenów w analizie krypto
- **Ulepszone raporty** — raporty DOCX/HTML z wykresami, znakami wodnymi, dynamicznymi wnioskami, opisami sekcji
- **Wyzwalacz ARIA** — przeciągany pływający wyzwalacz z zapamiętywaniem pozycji i inteligentnym umieszczaniem HUD
- Naprawiono tłumaczenie zatrzymujące się na 5% (auto-detekcja cache modeli)
- Naprawiono utratę formatowania raportu tłumaczeniowego (newlines zwinięte w jeden blok)
- Naprawiono nieaktualne wyniki transkrypcji/diaryzacji przy nowym wgraniu audio
- Middleware no-cache dla statycznych plików JS/CSS

## beta 3.7.1
- **Analiza kryptowalut — Binance** — rozszerzona analiza danych giełdy Binance
- Profilowanie zachowań użytkownika (10 wzorców: HODLer, Scalper, Day Trader, Swing Trader, Staker, Whale, Institutional, Alpha Hunter, Meme Trader, Bagholder)
- 18 kart analizy forensycznej: kontrahenci wewnętrzni, Pay C2C, adresy on-chain, przepływy pass-through, privacy coins, logi dostępu, karty płatnicze + **NOWE:** analiza temporalna, łańcuchy konwersji tokenów, wykrywanie structuringu/smurfingu, wash trading, fiat on/off ramp, analiza P2P, velocity deposit-to-withdrawal, analiza opłat, analiza sieci blockchain, rozszerzone bezpieczeństwo (VPN/proxy)
- Usunięto limity rekordów — pełne dane z przewijalnymi tabelami
- Pobieranie raportów jako pliki (HTML, TXT, DOCX)

## beta 3.7
- **Analiza krypto** *(eksperymentalne)* — moduł offline analizy transakcji blockchain (BTC/ETH), import CSV (WalletExplorer + 16 formatów giełdowych), scoring ryzyka, detekcja wzorców, graf przepływów, wykresy Chart.js, narracja LLM — w fazie głębokich testów
- Auto-detekcja języka źródłowego przy wgrywaniu pliku i wklejaniu tekstu (moduł tłumaczenia)
- Eksport wielojęzyczny (wszystkie przetłumaczone języki naraz)
- Naprawiono nazwy plików eksportu DOCX (problem z podkreślnikami)
- Naprawiono błąd syntezy waveform MMS TTS
- Naprawiono brak koreańskiego w wynikach tłumaczenia

## beta 3.6
- **Analiza GSM / BTS** — pełny moduł analizy billingów GSM z interaktywnymi mapami, osią czasu, klastrami, podróżami, heatmapą, grafem kontaktów
- **Analiza finansowa AML** — pipeline anti-money laundering: parsowanie PDF (7 polskich banków + MT940), wykrywanie anomalii regułowe + ML, analiza grafowa, scoring ryzyka, raporty wspomagane LLM
- **Nakładki mapowe** — bazy wojskowe, lotniska, placówki dyplomatyczne + import KML/KMZ
- **Mapy offline** — obsługa MBTiles (raster + wektor PBF via MapLibre GL)
- **Zrzuty ekranu mapy** — pełne przechwytywanie mapy ze wszystkimi warstwami, nakładkami i markerami KML
- Naprawiono parser KML/KMZ (bug z falsy element w ElementTree)
- Naprawiono zrzut ekranu canvas MapLibre GL (preserveDrawingBuffer)
- Naprawiono przełączanie języka na stronie info

## beta 3.5.1/3
- Naprawiono zapisywanie/przypisywanie projektów
- Ulepszono parser dla banku ING

## beta 3.5.0 (SQLite)
- Migracja JSON -> SQLite

## beta 3.4.0
- Dodano obsługę wielu użytkowników

## beta 3.2.3 (aktualizacja tłumaczenia)
- Dodano moduł tłumaczenia
- Dodano stronę ustawień NLLB
- Dodano możliwość zmiany priorytetów zadań
- Dodano Chat LLM
- Analiza dźwięków w tle *(eksperymentalne)*

## beta 3.0 - 3.1
- Wprowadzono moduły LLM Ollama do analizy danych
- Planowanie / przydzielanie GPU (aktualizacja)

Ta aktualizacja wprowadza koncepcję **GPU Resource Manager** w interfejsie i wewnętrznym przepływie, aby zmniejszyć ryzyko **nakładających się obciążeń GPU** (np. jednoczesna diaryzacja + transkrypcja + analiza LLM).

### Jaki problem to rozwiązuje
Gdy wiele zadań GPU uruchamia się jednocześnie, może to prowadzić do:
- nagłego wyczerpania VRAM (OOM),
- resetów sterownika / błędów CUDA,
- ekstremalnie wolnego przetwarzania z powodu rywalizacji o zasoby,
- niestabilnego zachowania gdy wielu użytkowników uruchamia zadania jednocześnie.

### Kompatybilność wsteczna
- Brak zmian w funkcjonalnym układzie istniejących zakładek.
- Zaktualizowano tylko koordynację GPU i etykiety administratora.

## beta 2.1 - 2.2

- Zmiana metodologii edycji bloków
- Poprawa obserwowalności i użyteczności logów aplikacji
- Fix: Przebudowa logowania (Whisper + pyannote) + eksport do pliku
