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

### 6.4 Analiza Crypto *(eksperymentalne)*

Moduł offline analizy transakcji kryptowalutowych (BTC / ETH) oraz danych giełdowych.

#### Import danych
1. Przejdź do zakładki **Crypto** w module Analiza.
2. Kliknij **Wczytaj dane** i wybierz plik CSV lub JSON.
3. System automatycznie rozpozna format:
   - **Blockchain**: WalletExplorer.com, Etherscan
   - **Giełdy**: Binance, Kraken, Coinbase, Revolut i inne (16+ formatów)
4. Po wczytaniu pojawią się informacje o danych: liczba transakcji, okres, portfel tokenów.

#### Widok danych
- **Tryb giełdowy** — tabela transakcji giełdowych z typami (deposit, withdraw, swap, staking itp.).
- **Tryb blockchain** — tabela transakcji on-chain z adresami i kwotami.
- **Portfel tokenów** — lista tokenów z opisami, klasyfikacją (znany / nieznany) i wartościami.
- **Słownik typów transakcji** — najedź kursorem na typ, aby zobaczyć opis (tooltip).

#### Klasyfikacja i przegląd
- Klasyfikuj transakcje: neutralna / poprawna / podejrzana / obserwacja.
- System automatycznie klasyfikuje niektóre transakcje na podstawie wzorców.

#### Anomalie
- **Detekcja anomalii ML** — algorytm wykrywa nietypowe transakcje (duże kwoty, nietypowe godziny, podejrzane wzorce).
- Typy anomalii: peel chain, dust attack, round-trip, smurfing, structuring.
- Baza adresów sankcjonowanych **OFAC** i znanych kontraktów DeFi.

#### Wykresy
- **Oś czasu salda** — zmiana salda w czasie (z normalizacją logarytmiczną).
- **Wolumen miesięczny** — suma transakcji w poszczególnych miesiącach.
- **Aktywność dzienna** — rozkład transakcji w dniach tygodnia.
- **Ranking kontrahentów** — najczęstsi partnerzy transakcji.

#### Graf przepływów
- Interaktywny **graf transakcji** (Cytoscape.js) — wizualizacja przepływów między adresami/kontrahentami.
- Kliknij węzeł, aby zobaczyć szczegóły.

#### Profilowanie użytkownika (Binance)
- 10 wzorców behawioralnych: HODLer, Scalper, Day Trader, Swing Trader, Staker, Whale, Institutional, Alpha Hunter, Meme Trader, Bagholder.
- 18 kart analizy forensycznej (kontrahenci wewnętrzni, adresy on-chain, wash trading, P2P, analiza opłat i inne).

#### Analiza narracyjna (LLM)
- Kliknij **Generuj analizę** → model Ollama wygeneruje raport opisowy z wnioskami i rekomendacjami.

#### Raporty
- Eksportuj wyniki do **HTML / DOCX / TXT** z toolbara.

#### Panel analityczny (Crypto)
- Lewy panel z notatką globalną i notatkami do transakcji.
- **Ctrl+M** — szybkie dodanie notatki do bieżącej transakcji.
- Tagi: neutralny, poprawny, podejrzany, obserwacja + 4 tagi własne.

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

### <span style="color:red">⚠ Odzyskiwanie dostępu — procedury krok po kroku</span>

<span style="color:red">Każdy zaszyfrowany projekt posiada losowy klucz szyfrowania (Project Key), który jest chroniony kluczem użytkownika (derywowanym z hasła). Dodatkowo klucz projektu jest zabezpieczony **kluczem głównym (Master Key)** administratora. Administrator **nie może samodzielnie odszyfrować projektu** — wymagana jest interakcja z użytkownikiem.</span>

#### <span style="color:red">Scenariusz 1: Użytkownik zapomniał hasło (samodzielne odzyskanie)</span>

<span style="color:red">Użytkownik posiada frazę odzyskiwania (12 słów otrzymanych przy tworzeniu konta).</span>

<span style="color:red">**Kroki użytkownika:**</span>
<span style="color:red">1. Na ekranie logowania kliknij **„Nie pamiętam hasła"**.</span>
<span style="color:red">2. Wpisz swoją **frazę odzyskiwania** (12 słów, oddzielonych spacjami).</span>
<span style="color:red">3. System weryfikuje frazę — jeśli poprawna, pojawia się formularz nowego hasła.</span>
<span style="color:red">4. Ustaw **nowe hasło** i potwierdź.</span>
<span style="color:red">5. System automatycznie re-szyfruje klucze wszystkich Twoich zaszyfrowanych projektów nowym hasłem.</span>
<span style="color:red">6. Logowanie odbywa się normalnie z nowym hasłem.</span>

<span style="color:red">**Administrator nie jest potrzebny** — cały proces jest automatyczny.</span>

#### <span style="color:red">Scenariusz 2: Użytkownik zapomniał hasło, ale ma frazę odzyskiwania (odzyskanie z pomocą admina)</span>

<span style="color:red">Jeśli samodzielny reset nie zadziałał lub jest wyłączony przez politykę:</span>

<span style="color:red">**Kroki administratora:**</span>
<span style="color:red">1. Otwórz **Zarządzanie użytkownikami** → znajdź konto użytkownika.</span>
<span style="color:red">2. Kliknij **„Generuj token odzyskiwania"** — system wygeneruje jednorazowy token (ważny 24h).</span>
<span style="color:red">3. Przekaż token użytkownikowi (osobiście, telefonicznie lub innym bezpiecznym kanałem).</span>

<span style="color:red">**Kroki użytkownika:**</span>
<span style="color:red">1. Przejdź do strony **odzyskiwania dostępu** (link na ekranie logowania).</span>
<span style="color:red">2. Wpisz **token odzyskiwania** otrzymany od administratora.</span>
<span style="color:red">3. Wpisz swoją **frazę odzyskiwania** (12 słów).</span>
<span style="color:red">4. Ustaw **nowe hasło**.</span>
<span style="color:red">5. System re-szyfruje klucze projektów nowym hasłem.</span>
<span style="color:red">6. Token zostaje unieważniony po użyciu.</span>

#### <span style="color:red">Scenariusz 3: Użytkownik stracił hasło ORAZ frazę odzyskiwania (odzyskanie kluczem głównym)</span>

<span style="color:red">To jedyny scenariusz, w którym wykorzystywany jest **klucz główny (Master Key)**.</span>

<span style="color:red">**Kroki administratora:**</span>
<span style="color:red">1. Otwórz **Zarządzanie użytkownikami → Bezpieczeństwo → Szyfrowanie**.</span>
<span style="color:red">2. Podaj swoje **hasło administratora** w celu odblokowania klucza głównego.</span>
<span style="color:red">3. Wybierz konto użytkownika, który utracił dostęp.</span>
<span style="color:red">4. Kliknij **„Odzyskiwanie awaryjne"** — system użyje klucza głównego do odszyfrowania kluczy projektów użytkownika.</span>
<span style="color:red">5. System wygeneruje **nową frazę odzyskiwania** dla użytkownika.</span>
<span style="color:red">6. System wygeneruje **jednorazowy token odzyskiwania**.</span>
<span style="color:red">7. Przekaż użytkownikowi: token + nową frazę odzyskiwania.</span>

<span style="color:red">**Kroki użytkownika:**</span>
<span style="color:red">1. Przejdź do strony **odzyskiwania dostępu**.</span>
<span style="color:red">2. Wpisz **token** od administratora.</span>
<span style="color:red">3. Wpisz **nową frazę odzyskiwania** od administratora.</span>
<span style="color:red">4. Ustaw **nowe hasło**.</span>
<span style="color:red">5. System re-szyfruje klucze projektów nowym hasłem.</span>

<span style="color:red">**WAŻNE:** Nową frazę odzyskiwania należy natychmiast zapisać i przechowywać w bezpiecznym miejscu!</span>

### <span style="color:red">⚠ Kopia zapasowa klucza głównego (Master Key)</span>

<span style="color:red">**UWAGA:** Jeśli użytkownik utraci hasło i frazę odzyskiwania, a administrator utraci klucz główny — **dane w zaszyfrowanych projektach będą niemożliwe do odzyskania**. Nie istnieje żadna „tylna furtka".</span>

<span style="color:red">**Obowiązki administratora:**</span>
<span style="color:red">1. Po inicjalizacji klucza głównego kliknij **„Kopia zapasowa klucza głównego"** w panelu szyfrowania.</span>
<span style="color:red">2. Podaj hasło administratora — system wyświetli klucz w formacie base64.</span>
<span style="color:red">3. **Zapisz klucz na nośniku offline** (pendrive, wydruk w sejfie) — NIE przechowuj go w systemie ani w e-mailu.</span>
<span style="color:red">4. Okresowo weryfikuj kopię zapasową przyciskiem **„Weryfikuj klucz główny"**.</span>

<span style="color:red">**Utrata klucza głównego + hasła użytkownika + frazy odzyskiwania = trwała utrata danych.**</span>

### <span style="color:red">⚠ Wyszukiwanie w zaszyfrowanych projektach</span>

<span style="color:red">Lista projektów (nazwa, data utworzenia) jest zawsze widoczna. Jednak **wyszukiwanie w treści** (transkrypcje, notatki, wyniki analiz) wymaga odszyfrowania danych i działa **wyłącznie w aktywnym (otwartym) projekcie**. Nie jest możliwe przeszukiwanie zawartości wielu zaszyfrowanych projektów jednocześnie.</span>

---

## 12. A.R.I.A. — asystent AI

Pływający przycisk A.R.I.A. (w prawym dolnym rogu ekranu) otwiera panel asystenta AI.

### Funkcje
- **Czat z AI** — zadawaj pytania dotyczące bieżącego kontekstu (transkrypcji, analizy, danych).
- **Kontekst automatyczny** — asystent automatycznie uwzględnia dane z aktualnie otwartej strony.
- **Czytanie odpowiedzi** (TTS) — odsłuchaj odpowiedź asystenta.
- **Podpowiedzi** (hint chips) — gotowe pytania dostosowane do aktualnego modułu.
- **Przeciąganie** — przycisk A.R.I.A. można przeciągnąć w dowolne miejsce na ekranie (pozycja jest zapamiętywana).

---

## 13. Odtwarzacz audio

Pasek odtwarzacza audio pojawia się w transkrypcji i diaryzacji, gdy projekt ma plik audio.

- **Play / Pauza** — odtwórz lub zatrzymaj nagranie.
- **Przewijanie** ±5 sekund (przyciski lub kliknięcie na pasku postępu).
- **Prędkość odtwarzania** — 0.5×, 0.75×, 1×, 1.25×, 1.5×, 2× (zapisywana w przeglądarce).
- **Kliknij na segment** tekstu, aby odsłuchać odpowiadający fragment audio.
- **Mapa fali dźwiękowej** (waveform) — wizualizacja amplitudy z markerami segmentów.

---

## 14. Wyszukiwanie i edycja segmentów

### Wyszukiwanie w tekście
- W transkrypcji i diaryzacji użyj **Ctrl+F** lub ikony lupy w toolbarze.
- Wyszukiwanie podświetla trafienia i pokazuje ich liczbę.
- Nawiguj między trafieniami strzałkami ↑ ↓.

### Scalanie i dzielenie segmentów
- **Scal segmenty** — zaznacz dwa sąsiednie bloki i kliknij „Scal" (ikona w toolbarze).
- **Podziel segment** — ustaw kursor w bloku i kliknij „Podziel" → blok zostanie podzielony w miejscu kursora.

---

## 15. Tryb ciemny / jasny

- Kliknij ikonę motywu w pasku bocznym (ikona słońca / księżyca).
- Wybór jest zapamiętywany w przeglądarce.

---

## Skróty klawiszowe

| Skrót | Akcja |
|-------|-------|
| **Esc** | Zamknij edytor bloku / zamknij wyszukiwanie |
| **Ctrl+F** | Otwórz wyszukiwanie w tekście (transkrypcja / diaryzacja) |
| **Ctrl+Enter** | Zapisz notatkę |
| **Ctrl+M** | Dodaj notatkę analityczną (AML / GSM / Crypto) |
| **PPM** (prawy przycisk myszy) | Otwórz edytor bloku (transkrypcja / diaryzacja) |
| **Kliknij segment** | Odtwórz fragment audio |
