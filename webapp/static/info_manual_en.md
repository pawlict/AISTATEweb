# AISTATE Web — User Manual

---

## 1. Projects

Projects are the central element of working with AISTATE. Each project stores an audio file, transcription results, diarization, translations, analyses, and notes.

### Creating a project
1. Go to the **Projects** tab in the sidebar.
2. Click **Create project** and enter a name (e.g., "Interview_2026_01").
3. Optionally add an audio file (WAV, MP3, M4A, FLAC, OGG, OPUS, MP4, AAC).
4. After creation, the project becomes active — it's visible in the top bar.

### Opening and managing
- Click a project card to open it and set it as active.
- Export a project to an `.aistate` file (context menu on the card) — transfer it to another machine.
- Import an `.aistate` file to add a project from another instance.

### Deleting
- Delete a project from the card's context menu. You can choose a file overwrite method (fast / pseudorandom / HMG IS5 / Gutmann).

---

## 2. Transcription

Speech-to-Text module.

### How to use
1. Make sure you have an active project with an audio file (or add one using the toolbar button).
2. Select the **ASR engine** (Whisper or NeMo) and **model** (e.g., `large-v3`).
3. Select the recording **language** (or `auto` for automatic detection).
4. Click the **Transcribe** button (AI icon).

### Result
- Text appears in blocks with timestamps (`[00:00:05.120 - 00:00:08.340]`).
- **Click** a block to play the audio segment.
- **Right-click** a block to open the inline editor — change text and speaker name.
- All changes are saved automatically.

### Sound detection
- If you have a sound detection model installed (YAMNet, PANNs, BEATs), enable the **Sound detection** option in the toolbar.
- Detected sounds (cough, laughter, music, siren, etc.) will appear as markers in the text.

### Text proofreading
- Use the **Proofread** feature to automatically correct the transcription using an LLM model (e.g., Bielik, PLLuM, Qwen3).
- Compare the original with the corrected text in a side-by-side diff view.

### Notes
- The **Notes** panel (on the right) lets you add a global note and notes for individual blocks.
- The note icon next to each block indicates whether it has an assigned note.

### Reports
- In the toolbar, select formats (HTML, DOC, TXT) and click **Save** — reports are saved to the project folder.

---

## 3. Diarization

Speaker identification module — "who speaks when".

### How to use
1. You need an active project with an audio file.
2. Select the **diarization engine**: pyannote (audio) or NeMo diarization.
3. Optionally set the number of speakers (or leave auto).
4. Click **Diarize**.

### Result
- Each block has a speaker label (e.g., `SPEAKER_00`, `SPEAKER_01`).
- **Speaker mapping**: replace labels with names (e.g., `SPEAKER_00` → "John Smith").
- Enter names in the fields → click **Apply mapping** → labels will be replaced.
- Mapping is saved in `project.json` — it will be loaded automatically when re-opening the project.

### Editing
- Right-click a block to open the editor: change text, speaker, play segment.
- Notes work the same as in Transcription.

### Reports
- Export results to HTML / DOC / TXT from the toolbar.

---

## 4. Translation

Multilingual translation module based on NLLB models (Meta).

### How to use
1. Go to the **Translation** tab.
2. Select an **NLLB model** (must be installed in NLLB Settings).
3. Paste text or import a document (TXT, DOCX, PDF, SRT).
4. Select the **source language** and **target languages** (you can select multiple).
5. Click **Generate**.

### Modes
- **Fast (NLLB)** — smaller models, faster translation.
- **Accurate (NLLB)** — larger models, better quality.

### Additional features
- **Preserve formatting** — keeps paragraphs and line breaks.
- **Terminology glossary** — use a glossary of specialized terms.
- **TTS (Reader)** — listen to source text and translation (requires an installed TTS engine).
- **Presets** — ready-made configurations (business documents, scientific papers, audio transcripts).

### Reports
- Export results to HTML / DOC / TXT.

---

## 5. Chat LLM

Chat interface with local LLM models (via Ollama).

### How to use
1. Go to **Chat LLM**.
2. Select a **model** from the list (must be installed in Ollama).
3. Type a message and click **Send**.

### Options
- **System prompt** — define the assistant's role (e.g., "You are a lawyer specializing in Polish law").
- **Temperature** — control response creativity (0 = deterministic, 1.5 = very creative).
- **History** — conversations are saved automatically. Return to a previous conversation from the sidebar.

---

## 6. Analysis

The Analysis tab contains four modules: LLM, AML, GSM, and Crypto. Switch between them using the tabs at the top.

### 6.1 LLM Analysis

Content analysis module using LLM models.

1. Select **data sources** in the sidebar panel (transcription, diarization, notes, documents).
2. Choose **prompts** — templates or create your own.
3. Click **Generate** (AI icon in the toolbar).

#### Quick analysis
- Automatic, lightweight analysis triggered after transcription.
- Uses a smaller model (configured in LLM Settings).

#### Deep analysis
- Full analysis from selected sources and prompts.
- Supports custom prompts: type an instruction in the "Custom prompt" field (e.g., "Create meeting minutes with decisions").

### 6.2 AML Analysis (Anti-Money Laundering)

Financial analysis module for bank statements.

1. Upload a bank statement (PDF or MT940) — the system automatically detects the bank and parses transactions.
2. Review **statement information**, identified accounts and cards.
3. Classify transactions: neutral / legitimate / suspicious / monitoring.
4. View **charts**: balance over time, categories, channels, monthly trend, daily activity, top counterparties.
5. **ML Anomalies** — Isolation Forest algorithm detects unusual transactions.
6. **Flow graph** — counterparty relationship visualization (layouts: flow, amount, timeline).
7. Ask the LLM model questions about the financial data ("Question / instruction for analysis" section).
8. Download an **HTML report** with analysis results.

#### Analyst panel (AML)
- Left panel with search, global note, and item notes.
- **Ctrl+M** — quickly add a note to the current element.
- Tags: neutral, legitimate, suspicious, monitoring + 4 custom tags (double-click to rename).

### 6.3 GSM / BTS Analysis

GSM billing data analysis module.

1. Load billing data (CSV, XLSX, PDF, ZIP with multiple files).
2. View **summary**: record count, period, devices (IMEI/IMSI).
3. **Anomalies** — detection of unusual patterns (night activity, roaming, dual-SIM, etc.).
4. **Special numbers** — identification of emergency, service numbers, etc.
5. **Contact graph** — visualization of most frequent contacts (Top 5/10/15/20).
6. **Records** — table of all records with filtering, search, and column management.
7. **Activity charts** — hourly distribution heatmap, night and weekend activity.
8. **BTS Map** — interactive map with multiple views:
   - All points, path, clusters, trips, border, BTS coverage, heatmap, timeline.
   - **Overlays**: military bases, civilian airports, diplomatic posts.
   - **KML/KMZ import** — custom layers from Google Earth.
   - **Offline maps** — MBTiles support (raster + vector PBF).
   - **Area selection** — circle / rectangle for spatial queries.
9. **Detected locations** — clusters of most frequent locations.
10. **Border crossings** — detection of trips abroad.
11. **Overnight stays** — analysis of overnight locations.
12. **Narrative analysis (LLM)** — generate a GSM analysis report using an Ollama model.
13. **Reports** — export to HTML / DOCX / TXT. Analytical notes DOCX with charts.

#### Section layout
- The **Customize layout** button in the analyst panel lets you change the order and visibility of sections (drag / check-uncheck).

#### Analyst panel (GSM)
- Left panel with search, global note, and item notes.
- **Ctrl+M** — quickly add a note to the current record.

#### Standalone map
- Open a map without billing data (map button in the toolbar).
- Edit mode — add points, polygons, user layers.

### 6.4 Crypto Analysis

Cryptocurrency transaction analysis module.

1. Load transaction data (CSV, JSON).
2. Review analysis results.
3. Generate narrative analysis using an LLM model.

---

## 7. Logs

Task monitoring and system diagnostics.

- Go to the **Logs** tab to see the status of all tasks (transcription, diarization, analysis, translation).
- Copy logs to clipboard or save to file.
- Clear the task list (does not delete projects).

---

## 8. Admin Panel

### GPU Settings
- Monitor GPU cards, VRAM, active tasks.
- Set concurrency limits (slots per GPU, memory fraction).
- View and manage the job queue.
- Set task type priorities (drag to reorder).

### ASR Settings
- Install Whisper models (tiny → large-v3).
- Install NeMo ASR and diarization models.
- Install sound detection models (YAMNet, PANNs, BEATs).

### LLM Settings
- Browse and install Ollama models (quick analysis, deep analysis, financial, proofreading, translation, vision/OCR).
- Add a custom Ollama model.
- Configure tokens (Hugging Face).

### NLLB Settings
- Install NLLB translation models (distilled-600M, distilled-1.3B, base-3.3B).
- View model information (size, quality, requirements).

### TTS Settings
- Install reader engines: Piper (fast, CPU), MMS (1100+ languages), Kokoro (highest quality).
- Test voices before use.

---

## 9. Settings

- **UI language** — switch between PL / EN / KO.
- **Hugging Face token** — required for pyannote models (gated models).
- **Default Whisper model** — preference for new transcriptions.

---

## 10. User Management (multi-user mode)

If multi-user mode is enabled:
- Administrators create, edit, ban, and delete user accounts.
- New users wait for administrator approval after registration.
- Each user has an assigned role that determines available modules.

---

## 11. Project Encryption

AISTATE allows encrypting projects to protect data from unauthorized access.

### Configuration (administrator)

In the **User Management → Security → Security Policy** panel, the administrator configures:

- **Project encryption** — enable / disable encryption capability.
- **Encryption method** — choose one of three methods:

| Level | Algorithm | Description |
|-------|-----------|-------------|
| **Light** | AES-128-GCM | Fast encryption, protection against casual access |
| **Standard** | AES-256-GCM | Default level — balance of speed and security |
| **Maximum** | AES-256-GCM + ChaCha20-Poly1305 | Double-layer encryption for sensitive data |

- **Enforce encryption** — when enabled, users cannot create unencrypted projects.

The selected encryption level applies to all subsequent projects created by users.

### Creating an encrypted project

When creating a project, a **Encrypt project** checkbox appears with information about the current method (e.g., "AES-256-GCM"). The checkbox is checked by default if the administrator has enabled encryption, and locked if encryption is enforced.

### Export and import

- **Export** of an encrypted project — the `.aistate` file is always encrypted. The system asks for an **export password** (separate from the account password).
- **Import** — the system automatically detects whether the `.aistate` file is encrypted. If so — it asks for the password. After import, the project is re-encrypted according to the administrator's current policy.
- An unencrypted project can be exported without a password OR with the "encrypt export" option.

### <span style="color:red">⚠ Access Recovery — Master Key</span>

<span style="color:red">Each encrypted project has a random encryption key that is protected by the user's key (derived from their password). Additionally, the administrator holds a **Master Key** that can decrypt any project.</span>

<span style="color:red">**WARNING:** If a user forgets their password and the administrator loses the Master Key — **the data in encrypted projects will be irrecoverable**. There is no "backdoor" or method to bypass the encryption. Therefore:</span>

<span style="color:red">- The administrator **must** back up the Master Key and store it in a secure location (e.g., safe, offline storage medium).</span>
<span style="color:red">- Users should use the **recovery phrase** assigned to their account — it allows password reset without losing access to projects.</span>
<span style="color:red">- Loss of Master Key + user password = **permanent data loss**.</span>

### <span style="color:red">⚠ Searching in encrypted projects</span>

<span style="color:red">The project list (name, creation date) is always visible. However, **content search** (transcriptions, notes, analysis results) requires data decryption and works **only in the active (open) project**. It is not possible to search across multiple encrypted projects simultaneously.</span>

---

## Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| **Esc** | Close block editor |
| **Ctrl+Enter** | Save note |
| **Ctrl+M** | Add analyst note (AML / GSM) |
| **Right-click** | Open block editor (transcription / diarization) |
