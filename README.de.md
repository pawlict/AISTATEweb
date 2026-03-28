# AISTATEweb Community (3.7.2 Beta)

[![English](https://flagcdn.com/24x18/gb.png) English](README.md) | [![Polski](https://flagcdn.com/24x18/pl.png) Polski](README.pl.md) | [![한국어](https://flagcdn.com/24x18/kr.png) 한국어](README.ko.md) | [![Español](https://flagcdn.com/24x18/es.png) Español](README.es.md) | [![Français](https://flagcdn.com/24x18/fr.png) Français](README.fr.md) | [![中文](https://flagcdn.com/24x18/cn.png) 中文](README.zh.md) | [![Українська](https://flagcdn.com/24x18/ua.png) Українська](README.uk.md) | [![Deutsch](https://flagcdn.com/24x18/de.png) Deutsch](README.de.md)

![Version](https://img.shields.io/badge/Version-3.7.2%20beta-orange)
![Edition](https://img.shields.io/badge/Edition-Community-blue)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Web-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

* * *

AISTATEweb Community ist ein webbasiertes Werkzeug für Audiotranskription, Sprecherdiarisierung, Übersetzung, KI-gestützte Analyse und strukturierte Berichterstellung — vollständig offline, auf lokaler Hardware ausführbar.

#### Feedback / Support

Bei Problemen, Vorschlägen oder Funktionswünschen kontaktieren Sie mich bitte unter: **pawlict@proton.me**

* * *

## 🚀 Hauptfunktionen

### 🎙️ Sprachverarbeitung
- Automatische Spracherkennung (ASR) mit **Whisper**, **WhisperX** und **NVIDIA NeMo**
- Unterstützung für mehrsprachige Audiodateien (PL / EN / UA / RU / BY und weitere)
- Offline- und lokale Modellausführung (keine Cloud-Abhängigkeit)
- Hochwertige Transkription, optimiert für lange Aufnahmen

### 🧩 Sprecherdiarisierung
- Fortgeschrittene Sprecherdiarisierung mit **pyannote** und **NeMo Diarization**
- Automatische Sprechererkennung und Segmentierung
- Unterstützung für Gespräche mit mehreren Sprechern (Besprechungen, Interviews, Anrufe)
- Konfigurierbare Diarisierungs-Engines und Modelle

### 🌍 Mehrsprachige Übersetzung
- Neuronale maschinelle Übersetzung basierend auf **NLLB-200**
- Vollständig offline arbeitende Übersetzungspipeline
- Flexible Auswahl von Quell- und Zielsprache
- Konzipiert für OSINT- und mehrsprachige Analyse-Workflows

### 🧠 Intelligence & Analyse
- KI-gestützte Inhaltsanalyse mit lokalen **LLM-Modellen**
- Transformation von Rohsprache und Text in strukturierte Erkenntnisse
- Unterstützung für analytische Berichte und nachrichtendienstlich orientierte Workflows

### 📱 GSM- / BTS-Analyse
- Import und Analyse von **GSM-Abrechnungsdaten** (CSV, XLSX, PDF)
- Interaktive **Kartenvisualisierung** von BTS-Standorten (Leaflet + OpenStreetMap)
- Unterstützung für **Offline-Karten** über MBTiles (Raster PNG/JPG/WebP + Vektor PBF via MapLibre GL)
- Mehrere Kartenansichten: alle Punkte, Pfad, Cluster, Fahrten, BTS-Abdeckung, Heatmap, Zeitstrahl
- **Gebietsauswahl** (Kreis / Rechteck) für räumliche Abfragen
- **Overlay-Ebenen**: Militärbasen, Zivilflughäfen, diplomatische Vertretungen (integrierte Daten)
- **KML/KMZ-Import** — benutzerdefinierte Overlay-Ebenen aus Google Earth und anderen GIS-Werkzeugen
- Karten-Screenshots mit Wasserzeichen (Online- und Offline-Karten + alle Overlay-Ebenen)
- Kontaktgraph, Aktivitäts-Heatmap, Top-Kontakte-Analyse
- Zeitstrahl-Player mit Monats-/Tagesanimation

### 💰 AML — Finanzanalyse
- **Anti-Geldwäsche**-Analysepipeline für Kontoauszüge
- Automatische Bankerkennung und PDF-Parsing für polnische Banken:
  PKO BP, ING, mBank, Pekao SA, Santander, Millennium, Revolut (+ generischer Fallback)
- Unterstützung des MT940 (SWIFT) Auszugsformats
- Transaktionsnormalisierung, regelbasierte Klassifizierung und Risikobewertung
- **Anomalieerkennung**: statistische Basislinie + ML-basiert (Isolation Forest)
- **Graphanalyse** — Visualisierung des Gegenparteinetzwerks
- Kontenübergreifende Analyse für Ermittlungen mit mehreren Konten
- Entity Resolution und Gegenpartei-Speicher (persistente Labels/Notizen)
- Ausgabenanalyse, Verhaltensmuster, Händlerkategorisierung
- LLM-gestützte Analyse (Prompt-Builder für Ollama-Modelle)
- HTML-Berichtserstellung mit Diagrammen
- Datenanonymisierungsprofile für sicheres Teilen

### 🔗 Krypto — Blockchain-Transaktionsanalyse *(experimentell)*
- Offline-Analyse von **BTC**- und **ETH**-Kryptowährungstransaktionen
- Import von **WalletExplorer.com** CSV und verschiedenen Börsenformaten (Binance, Etherscan, Kraken, Coinbase und weitere)
- Automatische Formaterkennung anhand von CSV-Spaltensignaturen
- Risikobewertung mit Mustererkennung: Peel Chain, Dust Attack, Round-Trip, Smurfing
- OFAC-Sanktionsadressdatenbank und bekannte DeFi-Vertragssuche
- Interaktiver **Transaktionsflussgraph** (Cytoscape.js)
- Diagramme: Saldoverlauf, monatliches Volumen, tägliche Aktivität, Gegenpartei-Ranking (Chart.js)
- LLM-gestützte narrative Analyse über Ollama
- *Dieses Modul befindet sich derzeit in einer frühen Testphase — Funktionen und Datenformate können sich ändern*

### ⚙️ GPU- & Ressourcenverwaltung
- Integrierter **GPU Resource Manager**
- Automatische Aufgabenplanung und Priorisierung (ASR, Diarisierung, Analyse)
- Sichere Ausführung gleichzeitiger Aufgaben ohne GPU-Überlastung
- CPU-Fallback bei nicht verfügbaren GPU-Ressourcen

### 📂 Projektbasierter Workflow
- Projektorientierte Datenorganisation
- Persistente Speicherung von Audio, Transkripten, Übersetzungen und Analysen
- Reproduzierbare analytische Workflows
- Trennung von Benutzerdaten und Systemprozessen

### 📄 Berichterstellung & Export
- Export der Ergebnisse in **TXT**, **HTML**, **DOC** und **PDF**
- Strukturierte Berichte, die Transkription, Diarisierung und Analyse kombinieren
- AML-Finanzberichte mit Diagrammen und Risikoindikatoren
- Sofort verwendbare Ergebnisse für Forschung, Dokumentation und Ermittlungen

### 🌐 Webbasierte Oberfläche
- Moderne Web-Oberfläche (**AISTATEweb**)
- Echtzeit-Aufgabenstatus und Protokolle
- Mehrsprachige Benutzeroberfläche (PL / EN)
- Konzipiert sowohl für Einzelplatz- als auch für Mehrbenutzerumgebungen (demnächst)


* * *

## Voraussetzungen

### System (Linux)

Installieren Sie die Basispakete (Beispiel):
    sudo apt update -y
    sudo apt install -y python3 python3-venv python3-pip git

### Python

Empfohlen: Python 3.11+.

* * *
## pyannote / Hugging Face (erforderlich für Diarisierung)

Die Diarisierung verwendet **pyannote.audio**-Pipelines, die auf dem **Hugging Face Hub** gehostet werden. Einige pyannote-Modelle sind **zugriffsbeschränkt** (gated), was bedeutet, dass Sie:
  * ein Hugging Face-Konto besitzen müssen,
  * die Nutzungsbedingungen auf den Modellseiten akzeptieren müssen,
  * einen **READ**-Zugriffstoken generieren und der Anwendung bereitstellen müssen.

### Schritt-für-Schritt-Anleitung (Token + Berechtigungen)

  1. Erstellen Sie ein Hugging Face-Konto oder melden Sie sich an.
  2. Öffnen Sie die erforderlichen pyannote-Modellseiten und klicken Sie auf **„Agree / Accept"** (Nutzungsbedingungen).
     Typische Modelle, die Sie möglicherweise akzeptieren müssen (je nach Version):
     * `pyannote/segmentation` (oder `pyannote/segmentation-3.0`)
     * `pyannote/speaker-diarization` (oder `pyannote/speaker-diarization-3.1`)
  3. Gehen Sie zu Ihren Hugging Face **Einstellungen → Zugriffstoken** und erstellen Sie einen neuen Token mit der Rolle **READ**.
  4. Fügen Sie den Token in die AISTATE Web-Einstellungen ein (oder stellen Sie ihn als Umgebungsvariable bereit — je nach Konfiguration).
* * *
## Installation (Linux)

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

## Ausführung
```
python3 AISTATEweb.py
```
Beispiel (uvicorn):
    python -m uvicorn webapp.server:app --host 0.0.0.0 --port 8000

Im Browser öffnen:
    http://127.0.0.1:8000

* * *
# AISTATEweb — Windows (WSL2 + NVIDIA GPU) Einrichtung

> **Wichtig:** In WSL2 wird der NVIDIA-Treiber **unter Windows** installiert, nicht innerhalb von Linux. Installieren Sie **keine** `nvidia-driver-*`-Pakete innerhalb der WSL-Distribution.

---

### 1. Windows-Seite

1. Aktivieren Sie WSL2 (PowerShell: `wsl --install` oder Windows-Features).
2. Installieren Sie den neuesten **NVIDIA Windows-Treiber** (Game Ready / Studio) — dieser stellt die GPU-Unterstützung innerhalb von WSL2 bereit.
3. Aktualisieren Sie WSL und starten Sie neu:
   ```powershell
   wsl --update
   wsl --shutdown
   ```

### 2. Innerhalb von WSL (Ubuntu empfohlen)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3 python3-venv python3-pip ffmpeg
```

Überprüfen Sie, ob die GPU sichtbar ist:
```bash
nvidia-smi
```

### 3. AISTATEweb installieren

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/pawlict/AISTATEweb.git
cd AISTATEweb

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel

# PyTorch mit CUDA (Beispiel: cu128)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

pip install -r requirements.txt
```

GPU-Zugriff überprüfen:
```bash
python -c "import torch; print('CUDA:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
```

### 4. Ausführung

```bash
python3 AISTATEweb.py
```
Im Browser öffnen: http://127.0.0.1:8000

### Fehlerbehebung

Falls `nvidia-smi` innerhalb von WSL nicht funktioniert, stellen Sie sicher, dass Sie **keine** Linux-NVIDIA-Pakete installiert haben. Entfernen Sie diese gegebenenfalls:
```bash
sudo apt purge -y 'nvidia-*' 'libnvidia-*' && sudo apt autoremove --purge -y
```

---

## Referenzen

- [NVIDIA: CUDA on WSL User Guide](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
- [Microsoft: Install WSL](https://learn.microsoft.com/windows/wsl/install)
- [PyTorch: Get Started](https://pytorch.org/get-started/locally/)
- [pyannote.audio (Hugging Face)](https://huggingface.co/pyannote)
- [Whisper (OpenAI)](https://github.com/openai/whisper)
- [NLLB-200 (Meta)](https://huggingface.co/facebook/nllb-200-distilled-600M)
- [Ollama](https://ollama.com/)

---

"Dieses Projekt steht unter der MIT-Lizenz (AS IS). Drittanbieterkomponenten sind separat lizenziert — siehe THIRD_PARTY_NOTICES.md."

## Beta 3.7.2
- **Analystenpanel** — neues Seitenleistenpanel, das die Notizen-Seitenleiste auf Transkriptions- und Diarisierungsseiten ersetzt
- **Blocknotizen mit Tags** — Notizen können nun farbige Tags haben, die als linker Rand auf Segmenten angezeigt werden
- **Revolut Krypto-PDF** — Parser für Revolut-Kryptowährungsauszüge, integriert in die AML-Pipeline
- **Token-Datenbank (TOP 200)** — Klassifizierung bekannter/unbekannter Token für die Kryptoanalyse
- **Verbesserte Berichte** — DOCX/HTML-Berichte mit Diagrammen, Wasserzeichen, dynamischen Schlussfolgerungen, Abschnittsbeschreibungen
- **ARIA-Trigger** — verschiebbarer schwebender Trigger mit Positionsspeicherung und intelligenter HUD-Platzierung
- Übersetzung bei 5 % hängengeblieben behoben (Auto-Detect-Modellcache)
- Formatierungsverlust bei Übersetzungsberichten behoben (Zeilenumbrüche zusammengefallen)
- Veraltete Transkriptions-/Diarisierungsergebnisse bei neuem Audio-Upload behoben
- No-Cache-Middleware für statische JS/CSS-Dateien

## Beta 3.7.1
- **Kryptowährungsanalyse — Binance** — erweiterte Analyse von Binance-Börsendaten
- Benutzerverhaltensprofilerstellung (10 Muster: HODLer, Scalper, Day Trader, Swing Trader, Staker, Whale, Institutional, Alpha Hunter, Meme Trader, Bagholder)
- 18 forensische Analysekarten: interne Gegenparteien, Pay C2C, On-Chain-Adressen, Durchleitungsströme, Privacy Coins, Zugriffsprotokolle, Zahlungskarten + **NEU:** Zeitanalyse, Token-Konvertierungsketten, Strukturierungs-/Smurfing-Erkennung, Wash Trading, Fiat On/Off Ramp, P2P-Analyse, Einzahlungs-Auszahlungs-Geschwindigkeit, Gebührenanalyse, Blockchain-Netzwerkanalyse, erweiterte Sicherheit (VPN/Proxy)
- Alle Datensatzlimits entfernt — vollständige Daten mit scrollbaren Tabellen
- Berichte als Dateien herunterladen (HTML, TXT, DOCX)

## Beta 3.7
- **Kryptoanalyse** *(experimentell)* — Offline-Blockchain-Transaktionsanalysemodul (BTC/ETH), CSV-Import (WalletExplorer + 16 Börsenformate), Risikobewertung, Mustererkennung, Flussgraph, Chart.js-Diagramme, LLM-Narrativ — derzeit in intensiver Testphase
- Automatische Quellsprachenerkennung beim Datei-Upload und Texteinfügen (Übersetzungsmodul)
- Mehrsprachiger Export (alle übersetzten Sprachen gleichzeitig)
- DOCX-Export-Dateinamen behoben (Problem mit Unterstrichen)
- MMS-TTS-Wellenformsynthesefehler behoben
- Fehlende koreanische Sprache in Übersetzungsergebnissen behoben

## Beta 3.6
- **GSM-/BTS-Analyse** — vollständiges GSM-Abrechnungsanalysemodul mit interaktiven Karten, Zeitstrahl, Clustern, Fahrten, Heatmap, Kontaktgraph
- **AML-Finanzanalyse** — Anti-Geldwäsche-Pipeline: PDF-Parsing (7 polnische Banken + MT940), regelbasierte + ML-Anomalieerkennung, Graphanalyse, Risikobewertung, LLM-gestützte Berichte
- **Karten-Overlays** — Militärbasen, Flughäfen, diplomatische Vertretungen + benutzerdefinierter KML/KMZ-Import
- **Offline-Karten** — MBTiles-Unterstützung (Raster + PBF-Vektor via MapLibre GL)
- **Karten-Screenshots** — vollständige Kartenerfassung einschließlich aller Kachelebenen, Overlays und KML-Markierungen
- KML/KMZ-Parser behoben (ElementTree Falsy-Element-Bug)
- MapLibre GL Canvas-Screenshot behoben (preserveDrawingBuffer)
- Sprachumschaltung auf der Infoseite behoben

## Beta 3.5.1/3
- Projektspeicherung/-zuweisung behoben.
- Verbesserter Parser für ING-Banking

## Beta 3.5.0 (SQLite)
- JSON -> SQLite-Migration

## Beta 3.4.0
- Mehrbenutzerbetrieb hinzugefügt

## Beta 3.2.3 (Übersetzungs-Update)
- Übersetzungsmodul hinzugefügt
- NLLB-Einstellungsseite hinzugefügt
- Möglichkeit zur Änderung von Aufgabenprioritäten hinzugefügt
- Chat-LLM hinzugefügt
- Hintergrund-Geräuschanalyse *(experimentell)*

## Beta 3.0 - 3.1
- LLM-Ollama-Module für Datenanalyse eingeführt
- GPU-Zuweisung / Planung (Update)

Dieses Update führt ein **GPU Resource Manager**-Konzept in der Benutzeroberfläche und im internen Ablauf ein, um das Risiko **überlappender GPU-intensiver Arbeitslasten** zu reduzieren (z. B. gleichzeitige Ausführung von Diarisierung + Transkription + LLM-Analyse).

### Welches Problem dies löst
Wenn mehrere GPU-Aufgaben gleichzeitig gestartet werden, kann dies zu Folgendem führen:
- plötzliche VRAM-Erschöpfung (OOM),
- Treiber-Resets / CUDA-Fehler,
- extrem langsame Verarbeitung durch Ressourcenkonflikte,
- instabiles Verhalten, wenn mehrere Benutzer gleichzeitig Aufgaben auslösen.

### Abwärtskompatibilität
- Keine Änderungen am funktionalen Layout bestehender Tabs.
- Nur GPU-Zugangskoordination und Admin-Beschriftung wurden aktualisiert.

## Beta 2.1 - 2.2

- Änderung der Blockbearbeitungsmethodik
- Dieses Update konzentriert sich auf die Verbesserung der Beobachtbarkeit und Benutzerfreundlichkeit von Anwendungsprotokollen.
- Behoben: Überarbeitung der Protokollierung (Whisper + pyannote) + Export in Datei
