# Instrukcja obsługi AISTATE Web

---

## 1. Projekty

Projekty to centralny element pracy w AISTATE. Każdy projekt przechowuje plik audio, wyniki transkrypcji, diaryzacji, tłumaczeń, analiz i notatki.

### Tworzenie projektu
1. Przejdź do zakładki **Projekty** w menu bocznym.
2. Kliknij **Utwórz projekt** i wpisz nazwę (np. „Wywiad_2026_01").
3. Opcjonalnie dodaj plik audio (WAV, MP3, M4A, FLAC, OGG, OPUS, MP4, AAC).
4. Po utworzeniu projekt staje się aktywny — jest widoczny w pasku u góry strony.

### Otwieranie i zarządzanie
- Kliknij kartę projektu, aby go otworzyć i ustawić jako aktywny.
- Eksportuj projekt do pliku `.aistate` (menu kontekstowe na karcie) — przeniesiesz go na inną maszynę.
- Importuj plik `.aistate`, aby dodać projekt z innej instancji.

### Usuwanie
- Usuń projekt z menu kontekstowego karty. Możesz wybrać metodę nadpisywania plików (szybkie / pseudolosowe / HMG IS5 / Gutmann).

---

## 2. Transkrypcja

Moduł zamiany mowy na tekst (Speech-to-Text).

### Jak korzystać
1. Upewnij się, że masz aktywny projekt z plikiem audio (lub dodaj plik przyciskiem w toolbarze).
2. Wybierz **silnik ASR** (Whisper lub NeMo) i **model** (np. `large-v3`).
3. Wybierz **język** nagrania (lub `auto` dla automatycznej detekcji).
4. Kliknij przycisk **Transkrybuj** (ikona AI).

### Wynik
- Tekst pojawia się w blokach z timestampami (`[00:00:05.120 - 00:00:08.340]`).
- **Kliknij** na blok, aby odsłuchać fragment.
- **Prawy przycisk myszy** (PPM) na bloku otwiera edytor inline — możesz zmienić tekst i mówcę.
- Wszystkie zmiany zapisują się automatycznie.

### Detekcja dźwięków
- Jeśli masz zainstalowany model detekcji dźwięków (YAMNet, PANNs, BEATs), włącz opcję **Detekcja dźwięków** w toolbarze.
- Wykryte dźwięki (kaszel, śmiech, muzyka, syrena itp.) pojawią się jako znaczniki w tekście.

### Notatki
- Panel **Notatki** (po prawej) pozwala dodać notatkę globalną i notatki do poszczególnych bloków.
- Ikona notatki obok każdego bloku wskazuje, czy blok ma przypisaną notatkę.

### Raporty
- W toolbarze zaznacz formaty (HTML, DOC, TXT) i kliknij **Zapisz** — raporty trafią do folderu projektu.

---

## 3. Diaryzacja

Moduł identyfikacji mówców — „kto mówi kiedy".

### Jak korzystać
1. Potrzebujesz aktywnego projektu z plikiem audio.
2. Wybierz **silnik diaryzacji**: pyannote (audio) lub NeMo diarization.
3. Opcjonalnie podaj liczbę mówców (lub zostaw auto).
4. Kliknij **Diaryzuj**.

### Wynik
- Każdy blok ma etykietę mówcy (np. `SPEAKER_00`, `SPEAKER_01`).
- **Mapowanie mówców**: podmień etykiety na imiona (np. `SPEAKER_00` → „Jan Kowalski").
- Wpisz imiona w pola → kliknij **Zastosuj mapowanie** → etykiety zostaną zamienione.
- Mapowanie zapisuje się w `project.json` — przy ponownym otwarciu projektu zostanie załadowane automatycznie.

### Edycja
- PPM (prawy przycisk myszy) na bloku otwiera edytor: zmiana tekstu, mówcy, odtwarzanie fragmentu.
- Notatki działają identycznie jak w transkrypcji.

### Raporty
- Eksportuj wynik do HTML / DOC / TXT z toolbara.

---

## 4. Tłumaczenie

Moduł wielojęzycznych tłumaczeń opartych na modelach NLLB (Meta).

### Jak korzystać
1. Przejdź do zakładki **Tłumaczenie**.
2. Wybierz **model NLLB** (musi być zainstalowany w Ustawieniach NLLB).
3. Wklej tekst lub zaimportuj dokument (TXT, DOCX, PDF, SRT).
4. Wybierz **język źródłowy** i **języki docelowe** (możesz zaznaczyć kilka naraz).
5. Kliknij **Generuj**.

### Tryby pracy
- **Szybki (NLLB)** — mniejsze modele, szybsze tłumaczenie.
- **Dokładny (NLLB)** — większe modele, lepsza jakość.

### Funkcje dodatkowe
- **Zachowaj formatowanie** — zachowuje akapity i podział linii.
- **Słownik terminów** — użyj słownika specjalistycznych terminów.
- **TTS (Lektor)** — odsłuchaj tekst źródłowy i tłumaczenie (wymaga zainstalowanego silnika TTS).
- **Presety** — gotowe konfiguracje (dokumenty biznesowe, artykuły naukowe, transkrypcje audio).

### Raporty
- Eksportuj wynik do HTML / DOC / TXT.

---

## 5. Chat LLM

Interfejs czatu z lokalnymi modelami LLM (przez Ollama).

### Jak korzystać
1. Przejdź do **Chat LLM**.
2. Wybierz **model** z listy (musi być zainstalowany w Ollama).
3. Wpisz wiadomość i kliknij **Wyślij**.

### Opcje
- **Prompt systemowy** — określ rolę asystenta (np. „Jesteś prawnikiem specjalizującym się w prawie polskim").
- **Temperatura** — kontroluj kreatywność odpowiedzi (0 = deterministyczna, 1.5 = bardzo kreatywna).
- **Historia** — rozmowy zapisują się automatycznie. Wróć do poprzedniej rozmowy z panelu bocznego.

---

## 6. Analiza (LLM)

Moduł analizy treści za pomocą modeli LLM.

### Analiza LLM
1. Zaznacz **źródła danych** w panelu bocznym (transkrypcja, diaryzacja, notatki, dokumenty).
2. Wybierz **prompty** — gotowe szablony lub utwórz własne.
3. Kliknij **Generuj** (ikona AI w toolbarze).

#### Szybka analiza (Quick)
- Automatyczna, lekka analiza uruchamiana po transkrypcji.
- Używa mniejszego modelu (konfiguracja w Ustawieniach LLM).

#### Głęboka analiza (Deep)
- Pełna analiza z wybranych źródeł i promptów.
- Obsługuje własne prompty: wpisz polecenie w polu „Własny prompt" (np. „Zrób protokół spotkania z decyzjami").

### Analiza AML
- Prześlij wyciąg bankowy (PDF) — system automatycznie rozpozna bank, sparsuje transakcje, oceni ryzyko.
- Przeglądaj i klasyfikuj transakcje (neutralne / poprawne / podejrzane / obserwacja).
- Wykresy: saldo w czasie, kategorie, kanały, trend miesięczny, top kontrahenci.
- Graf przepływów: wizualizacja powiązań między kontrahentami.

---

## 7. Logi

Podgląd zadań i diagnostyka systemowa.

- Przejdź do zakładki **Logi**, aby zobaczyć status wszystkich zadań (transkrypcja, diaryzacja, analiza, tłumaczenie).
- Kopiuj logi do schowka lub zapisz do pliku.
- Wyczyść listę zadań przyciskiem (nie usuwa projektów).

---

## 8. Panel administracyjny

### Ustawienia GPU
- Monitor kart GPU, VRAM, aktywnych zadań.
- Ustaw limity współbieżności (sloty na GPU, ułamek pamięci).
- Przeglądaj i zarządzaj kolejką zadań.
- Ustaw priorytety typów zadań (przeciągnij aby zmienić kolejność).

### Ustawienia ASR
- Instaluj modele Whisper (tiny → large-v3).
- Instaluj modele NeMo ASR i diaryzacji.
- Instaluj modele detekcji dźwięków (YAMNet, PANNs, BEATs).

### Ustawienia LLM
- Przeglądaj i instaluj modele Ollama (szybka analiza, głęboka analiza, finanse, korekta, tłumaczenia, vision/OCR).
- Dodaj własny model Ollama.
- Konfiguruj tokeny (Hugging Face).

### Ustawienia NLLB
- Instaluj modele tłumaczeń NLLB (distilled-600M, distilled-1.3B, base-3.3B).
- Przeglądaj informacje o modelach (rozmiar, jakość, wymagania).

### Ustawienia TTS
- Instaluj silniki lektora: Piper (szybki, CPU), MMS (1100+ języków), Kokoro (najwyższa jakość).
- Testuj głos przed użyciem.

---

## 9. Ustawienia

- **Język interfejsu** — przełączanie PL / EN.
- **Token Hugging Face** — wymagany dla modeli pyannote (gated models).
- **Domyślny model Whisper** — preferencja dla nowych transkrypcji.

---

## 10. Zarządzanie użytkownikami (tryb wieloużytkownikowy)

Jeśli tryb multiuser jest włączony:
- Administrator tworzy, edytuje, banuje i usuwa konta użytkowników.
- Nowi użytkownicy po rejestracji czekają na zatwierdzenie przez administratora.
- Każdy użytkownik ma przypisaną rolę, która określa dostępne moduły.

---

## Skróty klawiszowe

| Skrót | Akcja |
|-------|-------|
| **Esc** | Zamknij edytor bloku |
| **Ctrl+Enter** | Zapisz notatkę |
| **PPM** (prawy przycisk myszy) | Otwórz edytor bloku (transkrypcja / diaryzacja) |
