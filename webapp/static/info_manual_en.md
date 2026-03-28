# AISTATE Web Community — User Manual

> **Edition:** Community (open-source) · **Version:** 3.7.2 beta
>
> The Community edition is a free, fully-featured version of AISTATE Web for individual, educational, and research use. It includes all modules: transcription, diarization, translation, analysis (LLM, AML, GSM, Crypto), Chat LLM, and reporting.

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

### Sound detection *(experimental)*
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

### 6.4 Crypto Analysis *(experimental)*

Offline cryptocurrency transaction analysis module (BTC / ETH) and exchange data.

#### Data import
1. Go to the **Crypto** tab in the Analysis module.
2. Click **Load data** and select a CSV or JSON file.
3. The system automatically detects the format:
   - **Blockchain**: WalletExplorer.com, Etherscan
   - **Exchanges**: Binance, Kraken, Coinbase, Revolut and more (16+ formats)
4. After loading, data information appears: transaction count, period, token portfolio.

#### Data view
- **Exchange mode** — exchange transaction table with types (deposit, withdraw, swap, staking, etc.).
- **Blockchain mode** — on-chain transaction table with addresses and amounts.
- **Token portfolio** — token list with descriptions, classification (known / unknown) and values.
- **Transaction type dictionary** — hover over a type to see its description (tooltip).

#### Classification and review
- Classify transactions: neutral / legitimate / suspicious / monitoring.
- The system automatically classifies some transactions based on patterns.

#### Anomalies
- **ML anomaly detection** — algorithm detects unusual transactions (large amounts, unusual hours, suspicious patterns).
- Anomaly types: peel chain, dust attack, round-trip, smurfing, structuring.
- **OFAC** sanctioned address database and known DeFi contract lookup.

#### Charts
- **Balance timeline** — balance changes over time (with logarithmic normalization).
- **Monthly volume** — transaction totals by month.
- **Daily activity** — transaction distribution by day of week.
- **Counterparty ranking** — most frequent transaction partners.

#### Flow graph
- Interactive **transaction graph** (Cytoscape.js) — flow visualization between addresses/counterparties.
- Click a node to see details.

#### User profiling (Binance)
- 10 behavioral patterns: HODLer, Scalper, Day Trader, Swing Trader, Staker, Whale, Institutional, Alpha Hunter, Meme Trader, Bagholder.
- 18 forensic analysis cards (internal counterparties, on-chain addresses, wash trading, P2P, fee analysis and more).

#### Narrative analysis (LLM)
- Click **Generate analysis** → an Ollama model will generate a descriptive report with conclusions and recommendations.

#### Reports
- Export results to **HTML / DOCX / TXT** from the toolbar.

#### Analyst panel (Crypto)
- Left panel with global note and transaction notes.
- **Ctrl+M** — quickly add a note to the current transaction.
- Tags: neutral, legitimate, suspicious, monitoring + 4 custom tags.

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
- Install sound detection models (YAMNet, PANNs, BEATs) *(experimental)*.

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

When creating a project, an **Encrypt project** checkbox appears with information about the current method (e.g., "AES-256-GCM"). The checkbox is checked by default if the administrator has enabled encryption, and locked if encryption is enforced.

### Export and import

- **Export** of an encrypted project — the `.aistate` file is always encrypted. The system asks for an **export password** (separate from the account password).
- **Import** — the system automatically detects whether the `.aistate` file is encrypted. If so — it asks for the password. After import, the project is re-encrypted according to the administrator's current policy.
- An unencrypted project can be exported without a password OR with the "encrypt export" option.

### <span style="color:red">⚠ Access Recovery — step-by-step procedures</span>

<span style="color:red">Each encrypted project has a random encryption key (Project Key), which is protected by the user's key (derived from their password). Additionally, the project key is secured by the administrator's **Master Key**. The administrator **cannot decrypt a project alone** — user interaction is required.</span>

#### <span style="color:red">Scenario 1: User forgot password (self-recovery)</span>

<span style="color:red">The user has their recovery phrase (12 words received when the account was created).</span>

<span style="color:red">**User steps:**</span>
<span style="color:red">1. On the login screen, click **"Forgot password"**.</span>
<span style="color:red">2. Enter your **recovery phrase** (12 words, separated by spaces).</span>
<span style="color:red">3. The system verifies the phrase — if correct, a new password form appears.</span>
<span style="color:red">4. Set a **new password** and confirm.</span>
<span style="color:red">5. The system automatically re-encrypts the keys of all your encrypted projects with the new password.</span>
<span style="color:red">6. Log in normally with the new password.</span>

<span style="color:red">**No administrator involvement needed** — the process is fully automatic.</span>

#### <span style="color:red">Scenario 2: User forgot password but has recovery phrase (admin-assisted recovery)</span>

<span style="color:red">If self-service reset did not work or is disabled by policy:</span>

<span style="color:red">**Administrator steps:**</span>
<span style="color:red">1. Open **User Management** → find the user's account.</span>
<span style="color:red">2. Click **"Generate recovery token"** — the system generates a one-time token (valid for 24 hours).</span>
<span style="color:red">3. Deliver the token to the user (in person, by phone, or via another secure channel).</span>

<span style="color:red">**User steps:**</span>
<span style="color:red">1. Go to the **access recovery** page (link on the login screen).</span>
<span style="color:red">2. Enter the **recovery token** received from the administrator.</span>
<span style="color:red">3. Enter your **recovery phrase** (12 words).</span>
<span style="color:red">4. Set a **new password**.</span>
<span style="color:red">5. The system re-encrypts the project keys with the new password.</span>
<span style="color:red">6. The token is invalidated after use.</span>

#### <span style="color:red">Scenario 3: User lost password AND recovery phrase (Master Key recovery)</span>

<span style="color:red">This is the only scenario where the **Master Key** is used.</span>

<span style="color:red">**Administrator steps:**</span>
<span style="color:red">1. Open **User Management → Security → Encryption**.</span>
<span style="color:red">2. Enter your **administrator password** to unlock the Master Key.</span>
<span style="color:red">3. Select the user account that lost access.</span>
<span style="color:red">4. Click **"Emergency recovery"** — the system uses the Master Key to decrypt the user's project keys.</span>
<span style="color:red">5. The system generates a **new recovery phrase** for the user.</span>
<span style="color:red">6. The system generates a **one-time recovery token**.</span>
<span style="color:red">7. Deliver to the user: the token + the new recovery phrase.</span>

<span style="color:red">**User steps:**</span>
<span style="color:red">1. Go to the **access recovery** page.</span>
<span style="color:red">2. Enter the **token** from the administrator.</span>
<span style="color:red">3. Enter the **new recovery phrase** from the administrator.</span>
<span style="color:red">4. Set a **new password**.</span>
<span style="color:red">5. The system re-encrypts the project keys with the new password.</span>

<span style="color:red">**IMPORTANT:** The new recovery phrase must be immediately saved and stored in a secure location!</span>

### <span style="color:red">⚠ Master Key Backup</span>

<span style="color:red">**WARNING:** If a user loses their password and recovery phrase, and the administrator loses the Master Key — **data in encrypted projects will be irrecoverable**. There is no "backdoor".</span>

<span style="color:red">**Administrator responsibilities:**</span>
<span style="color:red">1. After initializing the Master Key, click **"Backup Master Key"** in the encryption panel.</span>
<span style="color:red">2. Enter the administrator password — the system displays the key in base64 format.</span>
<span style="color:red">3. **Save the key on an offline medium** (USB drive, printout in a safe) — do NOT store it in the system or in email.</span>
<span style="color:red">4. Periodically verify the backup using the **"Verify Master Key"** button.</span>

<span style="color:red">**Loss of Master Key + user password + recovery phrase = permanent data loss.**</span>

### <span style="color:red">⚠ Searching in encrypted projects</span>

<span style="color:red">The project list (name, creation date) is always visible. However, **content search** (transcriptions, notes, analysis results) requires data decryption and works **only in the active (open) project**. It is not possible to search across multiple encrypted projects simultaneously.</span>

---

## 12. A.R.I.A. — AI Assistant

The floating A.R.I.A. button (bottom-right corner) opens the AI assistant panel.

### Features
- **AI Chat** — ask questions about the current context (transcription, analysis, data).
- **Automatic context** — the assistant automatically includes data from the currently open page.
- **Response reading** (TTS) — listen to the assistant's response.
- **Hint chips** — ready-made questions tailored to the current module.
- **Draggable** — the A.R.I.A. button can be dragged anywhere on screen (position is remembered).

---

## 13. Audio Player

The audio player bar appears in Transcription and Diarization when the project has an audio file.

- **Play / Pause** — play or stop the recording.
- **Skip** ±5 seconds (buttons or click on the progress bar).
- **Playback speed** — 0.5×, 0.75×, 1×, 1.25×, 1.5×, 2× (saved in browser).
- **Click a text segment** to play the corresponding audio fragment.
- **Waveform map** — amplitude visualization with segment markers.

---

## 14. Search and Segment Editing

### Text search
- In Transcription and Diarization, use **Ctrl+F** or the magnifying glass icon in the toolbar.
- Search highlights matches and shows the count.
- Navigate between matches with ↑ ↓ arrows.

### Merging and splitting segments
- **Merge segments** — select two adjacent blocks and click "Merge" (toolbar icon).
- **Split segment** — place the cursor in a block and click "Split" → the block is split at the cursor position.

---

## 15. Dark / Light Mode

- Click the theme icon in the sidebar (sun / moon icon).
- The choice is remembered in the browser.

---

## Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| **Esc** | Close block editor / close search |
| **Ctrl+F** | Open text search (transcription / diarization) |
| **Ctrl+Enter** | Save note |
| **Ctrl+M** | Add analyst note (AML / GSM / Crypto) |
| **Right-click** | Open block editor (transcription / diarization) |
| **Click segment** | Play audio fragment |
