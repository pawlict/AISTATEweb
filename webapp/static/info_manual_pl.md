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

### Korekta tekstu
- Użyj funkcji **Korekta** do automatycznego poprawienia transkrypcji za pomocą modelu LLM (np. Bielik, PLLuM, Qwen3).
- Porównaj oryginał z poprawionym tekstem w widoku diff (side-by-side).

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

## 6. Analiza

Zakładka Analiza zawiera cztery moduły: LLM, AML, GSM i Crypto. Przełączaj się między nimi za pomocą kart u góry.

### 6.1 Analiza LLM

Moduł analizy treści za pomocą modeli LLM.

1. Zaznacz **źródła danych** w panelu bocznym (transkrypcja, diaryzacja, notatki, dokumenty).
2. Wybierz **prompty** — gotowe szablony lub utwórz własne.
3. Kliknij **Generuj** (ikona AI w toolbarze).

#### Szybka analiza (Quick)
- Automatyczna, lekka analiza uruchamiana po transkrypcji.
- Używa mniejszego modelu (konfiguracja w Ustawieniach LLM).

#### Głęboka analiza (Deep)
- Pełna analiza z wybranych źródeł i promptów.
- Obsługuje własne prompty: wpisz polecenie w polu „Własny prompt" (np. „Zrób protokół spotkania z decyzjami").

### 6.2 Analiza AML (Anti-Money Laundering)

Moduł analizy finansowej wyciągów bankowych.

1. Prześlij wyciąg bankowy (PDF lub MT940) — system automatycznie rozpozna bank i sparsuje transakcje.
2. Przeglądaj **informacje o wyciągu**, zidentyfikowane rachunki i karty.
3. Klasyfikuj transakcje: neutralne / poprawne / podejrzane / obserwacja.
4. Przeglądaj **wykresy**: saldo w czasie, kategorie, kanały, trend miesięczny, aktywność dzienna, top kontrahenci.
5. **Anomalie ML** — algorytm Isolation Forest wykrywa nietypowe transakcje.
6. **Graf przepływów** — wizualizacja powiązań między kontrahentami (układy: przepływowy, kwotowy, czasowy).
7. Zadaj pytanie modelowi LLM o dane finansowe (sekcja „Pytanie / instrukcja dla analizy").
8. Pobierz **raport HTML** z wynikami analizy.

#### Panel analityczny (AML)
- Lewy panel z wyszukiwaniem, notatką globalną i notatkami do elementów.
- **Ctrl+M** — szybkie dodanie notatki do bieżącego elementu.
- Tagi: neutralny, poprawny, podejrzany, obserwacja + 4 tagi własne (kliknij 2× aby zmienić nazwę).

### 6.3 Analiza GSM / BTS

Moduł analizy danych billingowych GSM.

1. Wczytaj dane billingowe (CSV, XLSX, PDF, ZIP z wieloma plikami).
2. Przeglądaj **podsumowanie**: liczba rekordów, okres, urządzenia (IMEI/IMSI).
3. **Anomalie** — wykrywanie nietypowych wzorców (aktywność nocna, roaming, dual-SIM itp.).
4. **Numery specjalne** — identyfikacja numerów alarmowych, serwisowych itp.
5. **Graf kontaktów** — wizualizacja najczęstszych kontaktów (Top 5/10/15/20).
6. **Rekordy** — tabela wszystkich rekordów z filtrowaniem, wyszukiwaniem i zarządzaniem kolumnami.
7. **Wykresy aktywności** — heatmapa rozkładu godzinowego, aktywność nocna i weekendowa.
8. **Mapa BTS** — interaktywna mapa z wieloma widokami:
   - Wszystkie punkty, ścieżka, klastry, podróże, granica, zasięg BTS, mapa cieplna, oś czasu.
   - **Nakładki**: jednostki wojskowe, lotniska cywilne, placówki dyplomatyczne.
   - **Import KML/KMZ** — własne warstwy z Google Earth.
   - **Mapy offline** — obsługa MBTiles (raster + wektor PBF).
   - **Selekcja obszarowa** — koło / prostokąt do zapytań przestrzennych.
9. **Wykryte lokalizacje** — klastry najczęstszych lokalizacji.
10. **Przekroczenia granic** — wykrywanie wyjazdów zagranicznych.
11. **Nocowanie poza domem** — analiza miejsc noclegowych.
12. **Analiza narracyjna (LLM)** — generuj raport z analizy GSM za pomocą modelu Ollama.
13. **Raporty** — eksport do HTML / DOCX / TXT. Notatki analityczne DOCX z wykresami.

#### Układ sekcji
- Przycisk **Dostosuj układ** w panelu analitycznym pozwala zmienić kolejność i widoczność sekcji (przeciągnij / zaznacz-odznacz).

#### Panel analityczny (GSM)
- Lewy panel z wyszukiwaniem, notatką globalną i notatkami do elementów.
- **Ctrl+M** — szybkie dodanie notatki do bieżącego rekordu.

#### Mapa samodzielna
- Otwórz mapę bez danych billingowych (przycisk mapy w toolbarze).
- Tryb edycji — dodawaj punkty, poligony, warstwy użytkownika.

### 6.4 Analiza Crypto

Moduł analizy transakcji kryptowalutowych.

1. Wczytaj dane transakcji (CSV, JSON).
2. Przeglądaj wyniki analizy.
3. Generuj analizę narracyjną za pomocą modelu LLM.

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

- **Język interfejsu** — przełączanie PL / EN / KO.
- **Token Hugging Face** — wymagany dla modeli pyannote (gated models).
- **Domyślny model Whisper** — preferencja dla nowych transkrypcji.

---

## 10. Zarządzanie użytkownikami (tryb wieloużytkownikowy)

Jeśli tryb multiuser jest włączony:
- Administrator tworzy, edytuje, banuje i usuwa konta użytkowników.
- Nowi użytkownicy po rejestracji czekają na zatwierdzenie przez administratora.
- Każdy użytkownik ma przypisaną rolę, która określa dostępne moduły.

---

## 11. Szyfrowanie projektów

AISTATE umożliwia szyfrowanie projektów w celu ochrony danych przed nieuprawnionym dostępem.

### Konfiguracja (administrator)

W panelu **Zarządzanie użytkownikami → Bezpieczeństwo → Polityka bezpieczeństwa** administrator ustawia:

- **Szyfrowanie projektów** — włącz / wyłącz możliwość szyfrowania.
- **Metoda szyfrowania** — wybierz jedną z trzech metod:

| Poziom | Algorytm | Opis |
|--------|----------|------|
| **Lekki** | AES-128-GCM | Szybkie szyfrowanie, ochrona przed przypadkowym dostępem |
| **Standardowy** | AES-256-GCM | Domyślny poziom — równowaga szybkości i bezpieczeństwa |
| **Maksymalny** | AES-256-GCM + ChaCha20-Poly1305 | Podwójna warstwa szyfrowania dla danych wrażliwych |

- **Wymuszaj szyfrowanie** — jeśli włączone, użytkownicy nie mogą tworzyć niezaszyfrowanych projektów.

Wybrany poziom szyfrowania obowiązuje dla wszystkich kolejnych projektów tworzonych przez użytkowników.

### Tworzenie zaszyfrowanego projektu

Podczas tworzenia projektu pojawia się checkbox **Szyfruj projekt** z informacją o aktualnej metodzie (np. „AES-256-GCM"). Checkbox jest domyślnie zaznaczony, jeśli administrator włączył szyfrowanie, i zablokowany, jeśli szyfrowanie jest wymuszone.

### Eksport i import

- **Eksport** zaszyfrowanego projektu — plik `.aistate` jest zawsze szyfrowany. System prosi o podanie **hasła eksportowego** (odrębnego od hasła konta).
- **Import** — system automatycznie wykrywa, czy plik `.aistate` jest zaszyfrowany. Jeśli tak — prosi o hasło. Po imporcie projekt jest re-szyfrowany zgodnie z aktualną polityką administratora.
- Niezaszyfrowany projekt można wyeksportować bez hasła LUB z opcją „szyfruj eksport".

### <span style="color:red">⚠ Odzyskiwanie dostępu — klucz główny (Master Key)</span>

<span style="color:red">Każdy projekt szyfrowany posiada losowy klucz szyfrowania, który jest chroniony kluczem użytkownika (derywowanym z hasła). Dodatkowo administrator posiada **klucz główny (Master Key)**, który umożliwia odszyfrowanie każdego projektu.</span>

<span style="color:red">**UWAGA:** Jeśli użytkownik zapomni hasło, a administrator utraci klucz główny — **dane w zaszyfrowanych projektach będą niemożliwe do odzyskania**. Nie istnieje żadna „tylna furtka" ani metoda obejścia szyfrowania. Dlatego:</span>

<span style="color:red">- Administrator **musi** wykonać kopię zapasową klucza głównego i przechowywać ją w bezpiecznym miejscu (np. sejf, nośnik offline).</span>
<span style="color:red">- Użytkownicy powinni korzystać z **frazy odzyskiwania** (recovery phrase) przypisanej do konta — umożliwia ona reset hasła bez utraty dostępu do projektów.</span>
<span style="color:red">- Utrata klucza głównego + hasła użytkownika = **trwała utrata danych**.</span>

### <span style="color:red">⚠ Wyszukiwanie w zaszyfrowanych projektach</span>

<span style="color:red">Lista projektów (nazwa, data utworzenia) jest zawsze widoczna. Jednak **wyszukiwanie w treści** (transkrypcje, notatki, wyniki analiz) wymaga odszyfrowania danych i działa **wyłącznie w aktywnym (otwartym) projekcie**. Nie jest możliwe przeszukiwanie zawartości wielu zaszyfrowanych projektów jednocześnie.</span>

---

## Skróty klawiszowe

| Skrót | Akcja |
|-------|-------|
| **Esc** | Zamknij edytor bloku |
| **Ctrl+Enter** | Zapisz notatkę |
| **Ctrl+M** | Dodaj notatkę analityczną (AML / GSM) |
| **PPM** (prawy przycisk myszy) | Otwórz edytor bloku (transkrypcja / diaryzacja) |
