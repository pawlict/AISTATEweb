# Plan: Dialog tworzenia projektu — finalna architektura

## Decyzje użytkownika
- **Flow**: Dialog modalny na stronie modułu (Opcja A), bez reload
- **Fallback**: requireProjectId() pokazuje ten sam dialog zamiast redirect
- **Typ projektu**: `general` (jeden projekt = wszystkie moduły)
- **Banner**: żaden gdy projekt aktywny

## Implementacja

### 1. `_showCreateProjectDialog()` — modal BEZ reload
**Plik:** `webapp/static/app.js`

Zmiany:
- Dialog tworzy projekt z typem `general`
- Tekst: "Ten projekt będzie używany we wszystkich modułach"
- Po utworzeniu: ustawia `AISTATE.projectId` i **zamyka dialog bez reload**
- Zwraca Promise<string> (project_id) — do użycia przez requireProjectId

### 2. `requireProjectId()` — dialog zamiast redirect
**Plik:** `webapp/static/app.js`

Zmiany:
- Zamiast redirect na /projects → wywołuje `_showCreateProjectDialog()`
- Czeka (await) na wynik dialogu
- Zwraca project_id do callera (startTask, file upload)
- Caller kontynuuje działanie bez utraty kontekstu

### 3. `_injectProjectBanner()` — uproszczenie
**Plik:** `webapp/static/app.js`

Zmiany:
- Gdy projekt aktywny: RETURN (żadnego bannera)
- Gdy brak: wywołaj `_showCreateProjectDialog()` (fire-and-forget)

### 4. i18n — nowe/zmienione klucze
**Pliki:** `webapp/static/lang/pl.json`, `webapp/static/lang/en.json`

- `banner.dialog_title` → "Utwórz nowy projekt"
- `banner.dialog_subtitle` → "Projekt będzie używany we wszystkich modułach..."
- Bez zmian w reszcie kluczy

### 5. NIE zmieniamy
- Strona /projects — bez zmian
- Backend endpoints — bez zmian
- startTask() — bez zmian (już woła requireProjectId)
- Transcription file upload handler — bez zmian (już woła requireProjectId)
