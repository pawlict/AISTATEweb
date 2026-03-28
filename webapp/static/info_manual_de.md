# AISTATE Web Community — Benutzerhandbuch

> **Ausgabe:** Community (Open-Source) · **Version:** 3.7.2 Beta
>
> Die Community-Ausgabe ist eine kostenlose, voll ausgestattete Version von AISTATE Web für den individuellen, bildungsbezogenen und wissenschaftlichen Einsatz. Sie umfasst alle Module: Transkription, Diarisierung, Übersetzung, Analyse (LLM, AML, GSM, Crypto), Chat LLM und Berichterstellung.

---

## 1. Projekte

Projekte sind das zentrale Element der Arbeit mit AISTATE. Jedes Projekt speichert eine Audiodatei, Transkriptionsergebnisse, Diarisierung, Übersetzungen, Analysen und Notizen.

### Projekt erstellen
1. Wechseln Sie zum Reiter **Projects** in der Seitenleiste.
2. Klicken Sie auf **Create project** und geben Sie einen Namen ein (z. B. „Interview_2026_01").
3. Fügen Sie optional eine Audiodatei hinzu (WAV, MP3, M4A, FLAC, OGG, OPUS, MP4, AAC).
4. Nach der Erstellung wird das Projekt aktiv — es ist in der oberen Leiste sichtbar.

### Öffnen und verwalten
- Klicken Sie auf eine Projektkarte, um das Projekt zu öffnen und als aktiv festzulegen.
- Exportieren Sie ein Projekt als `.aistate`-Datei (Kontextmenü auf der Karte) — übertragen Sie es auf einen anderen Rechner.
- Importieren Sie eine `.aistate`-Datei, um ein Projekt aus einer anderen Instanz hinzuzufügen.

### Löschen
- Löschen Sie ein Projekt über das Kontextmenü der Karte. Sie können eine Methode zur Dateiüberschreibung wählen (schnell / pseudozufällig / HMG IS5 / Gutmann).

---

## 2. Transkription

Speech-to-Text-Modul.

### Verwendung
1. Stellen Sie sicher, dass Sie ein aktives Projekt mit einer Audiodatei haben (oder fügen Sie eine über die Symbolleistenschaltfläche hinzu).
2. Wählen Sie die **ASR engine** (Whisper oder NeMo) und das **Modell** (z. B. `large-v3`).
3. Wählen Sie die **Sprache** der Aufnahme (oder `auto` für automatische Erkennung).
4. Klicken Sie auf die Schaltfläche **Transcribe** (AI-Symbol).

### Ergebnis
- Der Text erscheint in Blöcken mit Zeitstempeln (`[00:00:05.120 - 00:00:08.340]`).
- **Klicken** Sie auf einen Block, um das Audiosegment abzuspielen.
- **Rechtsklick** auf einen Block öffnet den Inline-Editor — ändern Sie Text und Sprechernamen.
- Alle Änderungen werden automatisch gespeichert.

### Geräuscherkennung
- Wenn Sie ein Geräuscherkennungsmodell installiert haben (YAMNet, PANNs, BEATs), aktivieren Sie die Option **Sound detection** in der Symbolleiste.
- Erkannte Geräusche (Husten, Lachen, Musik, Sirene usw.) erscheinen als Markierungen im Text.

### Textkorrektur
- Verwenden Sie die Funktion **Proofread**, um die Transkription automatisch mithilfe eines LLM-Modells zu korrigieren (z. B. Bielik, PLLuM, Qwen3).
- Vergleichen Sie das Original mit dem korrigierten Text in einer nebeneinander angeordneten Diff-Ansicht.

### Notizen
- Das Panel **Notes** (auf der rechten Seite) ermöglicht es Ihnen, eine globale Notiz und Notizen für einzelne Blöcke hinzuzufügen.
- Das Notizsymbol neben jedem Block zeigt an, ob eine Notiz zugewiesen ist.

### Berichte
- Wählen Sie in der Symbolleiste die Formate (HTML, DOC, TXT) und klicken Sie auf **Save** — Berichte werden im Projektordner gespeichert.

---

## 3. Diarisierung

Modul zur Sprecheridentifikation — „wer spricht wann".

### Verwendung
1. Sie benötigen ein aktives Projekt mit einer Audiodatei.
2. Wählen Sie die **Diarisierungs-Engine**: pyannote (audio) oder NeMo diarization.
3. Legen Sie optional die Anzahl der Sprecher fest (oder belassen Sie es auf automatisch).
4. Klicken Sie auf **Diarize**.

### Ergebnis
- Jeder Block hat eine Sprecherbezeichnung (z. B. `SPEAKER_00`, `SPEAKER_01`).
- **Speaker mapping**: Ersetzen Sie Bezeichnungen durch Namen (z. B. `SPEAKER_00` → „Max Mustermann").
- Geben Sie Namen in die Felder ein → klicken Sie auf **Apply mapping** → die Bezeichnungen werden ersetzt.
- Die Zuordnung wird in `project.json` gespeichert — sie wird beim erneuten Öffnen des Projekts automatisch geladen.

### Bearbeitung
- Rechtsklick auf einen Block öffnet den Editor: Text und Sprecher ändern, Segment abspielen.
- Notizen funktionieren wie in der Transkription.

### Berichte
- Exportieren Sie Ergebnisse über die Symbolleiste nach HTML / DOC / TXT.

---

## 4. Übersetzung

Mehrsprachiges Übersetzungsmodul basierend auf NLLB-Modellen (Meta).

### Verwendung
1. Wechseln Sie zum Reiter **Translation**.
2. Wählen Sie ein **NLLB-Modell** (muss in den NLLB Settings installiert sein).
3. Fügen Sie Text ein oder importieren Sie ein Dokument (TXT, DOCX, PDF, SRT).
4. Wählen Sie die **Ausgangssprache** und die **Zielsprachen** (Mehrfachauswahl möglich).
5. Klicken Sie auf **Generate**.

### Modi
- **Fast (NLLB)** — kleinere Modelle, schnellere Übersetzung.
- **Accurate (NLLB)** — größere Modelle, bessere Qualität.

### Zusätzliche Funktionen
- **Preserve formatting** — behält Absätze und Zeilenumbrüche bei.
- **Terminology glossary** — verwenden Sie ein Glossar mit Fachbegriffen.
- **TTS (Reader)** — hören Sie sich Ausgangstext und Übersetzung an (erfordert eine installierte TTS-Engine).
- **Presets** — vorgefertigte Konfigurationen (Geschäftsdokumente, wissenschaftliche Arbeiten, Audio-Transkripte).

### Berichte
- Exportieren Sie Ergebnisse nach HTML / DOC / TXT.

---

## 5. Chat LLM

Chat-Schnittstelle mit lokalen LLM-Modellen (über Ollama).

### Verwendung
1. Wechseln Sie zu **Chat LLM**.
2. Wählen Sie ein **Modell** aus der Liste (muss in Ollama installiert sein).
3. Geben Sie eine Nachricht ein und klicken Sie auf **Send**.

### Optionen
- **System prompt** — definieren Sie die Rolle des Assistenten (z. B. „Sie sind ein Anwalt, der auf deutsches Recht spezialisiert ist").
- **Temperature** — steuern Sie die Kreativität der Antworten (0 = deterministisch, 1.5 = sehr kreativ).
- **History** — Gespräche werden automatisch gespeichert. Kehren Sie über die Seitenleiste zu einem früheren Gespräch zurück.

---

## 6. Analyse

Der Reiter „Analyse" enthält vier Module: LLM, AML, GSM und Crypto. Wechseln Sie zwischen ihnen über die Registerkarten oben.

### 6.1 LLM-Analyse

Modul zur Inhaltsanalyse mithilfe von LLM-Modellen.

1. Wählen Sie **Datenquellen** im Seitenleisten-Panel (Transkription, Diarisierung, Notizen, Dokumente).
2. Wählen Sie **Prompts** — Vorlagen oder erstellen Sie eigene.
3. Klicken Sie auf **Generate** (AI-Symbol in der Symbolleiste).

#### Schnellanalyse
- Automatische, schlanke Analyse, die nach der Transkription ausgelöst wird.
- Verwendet ein kleineres Modell (konfiguriert in den LLM Settings).

#### Tiefenanalyse
- Vollständige Analyse aus ausgewählten Quellen und Prompts.
- Unterstützt benutzerdefinierte Prompts: Geben Sie eine Anweisung im Feld „Custom prompt" ein (z. B. „Erstellen Sie ein Besprechungsprotokoll mit Beschlüssen").

### 6.2 AML-Analyse (Anti-Money Laundering)

Modul zur Finanzanalyse von Kontoauszügen.

1. Laden Sie einen Kontoauszug hoch (PDF oder MT940) — das System erkennt automatisch die Bank und analysiert die Transaktionen.
2. Überprüfen Sie die **Auszugsinformationen**, identifizierte Konten und Karten.
3. Klassifizieren Sie Transaktionen: neutral / legitim / verdächtig / Überwachung.
4. Sehen Sie sich **Diagramme** an: Saldoverlauf, Kategorien, Kanäle, Monatstrend, Tagesaktivität, Top-Gegenparteien.
5. **ML Anomalies** — Der Isolation-Forest-Algorithmus erkennt ungewöhnliche Transaktionen.
6. **Flow graph** — Visualisierung der Gegenpartei-Beziehungen (Layouts: Flow, Betrag, Zeitverlauf).
7. Stellen Sie dem LLM-Modell Fragen zu den Finanzdaten (Abschnitt „Question / instruction for analysis").
8. Laden Sie einen **HTML-Bericht** mit Analyseergebnissen herunter.

#### Analysten-Panel (AML)
- Linkes Panel mit Suche, globaler Notiz und Elementnotizen.
- **Ctrl+M** — schnelles Hinzufügen einer Notiz zum aktuellen Element.
- Tags: neutral, legitim, verdächtig, Überwachung + 4 benutzerdefinierte Tags (Doppelklick zum Umbenennen).

### 6.3 GSM / BTS-Analyse

Modul zur Analyse von GSM-Abrechnungsdaten.

1. Laden Sie Abrechnungsdaten (CSV, XLSX, PDF, ZIP mit mehreren Dateien).
2. Sehen Sie sich die **Zusammenfassung** an: Anzahl der Datensätze, Zeitraum, Geräte (IMEI/IMSI).
3. **Anomalies** — Erkennung ungewöhnlicher Muster (Nachtaktivität, Roaming, Dual-SIM usw.).
4. **Special numbers** — Identifikation von Notruf-, Servicenummern usw.
5. **Contact graph** — Visualisierung der häufigsten Kontakte (Top 5/10/15/20).
6. **Records** — Tabelle aller Datensätze mit Filterung, Suche und Spaltenverwaltung.
7. **Activity charts** — Heatmap der stündlichen Verteilung, Nacht- und Wochenendaktivität.
8. **BTS Map** — interaktive Karte mit mehreren Ansichten:
   - Alle Punkte, Pfad, Cluster, Fahrten, Grenze, BTS-Abdeckung, Heatmap, Zeitverlauf.
   - **Overlays**: Militärbasen, zivile Flughäfen, diplomatische Vertretungen.
   - **KML/KMZ import** — benutzerdefinierte Ebenen aus Google Earth.
   - **Offline maps** — MBTiles-Unterstützung (Raster + Vektor PBF).
   - **Area selection** — Kreis / Rechteck für räumliche Abfragen.
9. **Detected locations** — Cluster der häufigsten Standorte.
10. **Border crossings** — Erkennung von Auslandsreisen.
11. **Overnight stays** — Analyse der Übernachtungsstandorte.
12. **Narrative analysis (LLM)** — Erstellen Sie einen GSM-Analysebericht mithilfe eines Ollama-Modells.
13. **Reports** — Export nach HTML / DOCX / TXT. Analytische Notizen als DOCX mit Diagrammen.

#### Abschnittslayout
- Die Schaltfläche **Customize layout** im Analysten-Panel ermöglicht es Ihnen, die Reihenfolge und Sichtbarkeit von Abschnitten zu ändern (Ziehen / An-/Abwählen).

#### Analysten-Panel (GSM)
- Linkes Panel mit Suche, globaler Notiz und Elementnotizen.
- **Ctrl+M** — schnelles Hinzufügen einer Notiz zum aktuellen Datensatz.

#### Eigenständige Karte
- Öffnen Sie eine Karte ohne Abrechnungsdaten (Karten-Schaltfläche in der Symbolleiste).
- Bearbeitungsmodus — Punkte, Polygone, Benutzerebenen hinzufügen.

### 6.4 Crypto-Analyse *(experimentell)*

Offline-Modul zur Analyse von Kryptowährungstransaktionen (BTC / ETH) und Börsendaten.

#### Datenimport
1. Wechseln Sie zum Reiter **Crypto** im Analyse-Modul.
2. Klicken Sie auf **Load data** und wählen Sie eine CSV- oder JSON-Datei.
3. Das System erkennt automatisch das Format:
   - **Blockchain**: WalletExplorer.com, Etherscan
   - **Exchanges**: Binance, Kraken, Coinbase, Revolut und weitere (16+ Formate)
4. Nach dem Laden erscheinen Dateninformationen: Transaktionsanzahl, Zeitraum, Token-Portfolio.

#### Datenansicht
- **Exchange mode** — Tabelle der Börsentransaktionen mit Typen (deposit, withdraw, swap, staking usw.).
- **Blockchain mode** — Tabelle der On-Chain-Transaktionen mit Adressen und Beträgen.
- **Token portfolio** — Token-Liste mit Beschreibungen, Klassifikation (bekannt / unbekannt) und Werten.
- **Transaction type dictionary** — Bewegen Sie den Mauszeiger über einen Typ, um dessen Beschreibung anzuzeigen (Tooltip).

#### Klassifikation und Überprüfung
- Klassifizieren Sie Transaktionen: neutral / legitim / verdächtig / Überwachung.
- Das System klassifiziert einige Transaktionen automatisch anhand von Mustern.

#### Anomalien
- **ML anomaly detection** — Der Algorithmus erkennt ungewöhnliche Transaktionen (hohe Beträge, ungewöhnliche Uhrzeiten, verdächtige Muster).
- Anomalie-Typen: peel chain, dust attack, round-trip, smurfing, structuring.
- **OFAC**-Datenbank sanktionierter Adressen und Suche nach bekannten DeFi-Verträgen.

#### Diagramme
- **Balance timeline** — Saldoveränderungen über die Zeit (mit logarithmischer Normalisierung).
- **Monthly volume** — Transaktionssummen nach Monat.
- **Daily activity** — Transaktionsverteilung nach Wochentag.
- **Counterparty ranking** — häufigste Transaktionspartner.

#### Flow graph
- Interaktiver **Transaktionsgraph** (Cytoscape.js) — Flussvisualisierung zwischen Adressen/Gegenparteien.
- Klicken Sie auf einen Knoten, um Details anzuzeigen.

#### Benutzerprofilerstellung (Binance)
- 10 Verhaltensmuster: HODLer, Scalper, Day Trader, Swing Trader, Staker, Whale, Institutional, Alpha Hunter, Meme Trader, Bagholder.
- 18 forensische Analysekarten (interne Gegenparteien, On-Chain-Adressen, Wash Trading, P2P, Gebührenanalyse und mehr).

#### Narrative Analyse (LLM)
- Klicken Sie auf **Generate analysis** → ein Ollama-Modell erstellt einen beschreibenden Bericht mit Schlussfolgerungen und Empfehlungen.

#### Berichte
- Exportieren Sie Ergebnisse über die Symbolleiste nach **HTML / DOCX / TXT**.

#### Analysten-Panel (Crypto)
- Linkes Panel mit globaler Notiz und Transaktionsnotizen.
- **Ctrl+M** — schnelles Hinzufügen einer Notiz zur aktuellen Transaktion.
- Tags: neutral, legitim, verdächtig, Überwachung + 4 benutzerdefinierte Tags.

---

## 7. Logs

Aufgabenüberwachung und Systemdiagnose.

- Gehen Sie zur Registerkarte **Logs**, um den Status aller Aufgaben (Transkription, Diarisierung, Analyse, Übersetzung) einzusehen.
- Kopieren Sie Logs in die Zwischenablage oder speichern Sie sie in einer Datei.
- Löschen Sie die Aufgabenliste (Projekte werden nicht gelöscht).

---

## 8. Admin-Panel

### GPU-Einstellungen
- Überwachen Sie GPU-Karten, VRAM und aktive Aufgaben.
- Legen Sie Parallelitätslimits fest (Slots pro GPU, Speicheranteil).
- Zeigen Sie die Auftragswarteschlange an und verwalten Sie diese.
- Legen Sie Aufgabentyp-Prioritäten fest (per Drag-and-Drop neu anordnen).

### ASR-Einstellungen
- Installieren Sie Whisper-Modelle (tiny → large-v3).
- Installieren Sie NeMo ASR- und Diarisierungsmodelle.
- Installieren Sie Geräuscherkennungsmodelle (YAMNet, PANNs, BEATs).

### LLM-Einstellungen
- Durchsuchen und installieren Sie Ollama-Modelle (Schnellanalyse, Tiefenanalyse, Finanzen, Korrekturlesen, Übersetzung, Vision/OCR).
- Fügen Sie ein benutzerdefiniertes Ollama-Modell hinzu.
- Konfigurieren Sie Tokens (Hugging Face).

### NLLB-Einstellungen
- Installieren Sie NLLB-Übersetzungsmodelle (distilled-600M, distilled-1.3B, base-3.3B).
- Zeigen Sie Modellinformationen an (Größe, Qualität, Anforderungen).

### TTS-Einstellungen
- Installieren Sie Vorlesemodule: Piper (schnell, CPU), MMS (1100+ Sprachen), Kokoro (höchste Qualität).
- Testen Sie Stimmen vor der Verwendung.

---

## 9. Einstellungen

- **UI-Sprache** — wechseln Sie zwischen PL / EN / KO.
- **Hugging Face Token** — erforderlich für pyannote-Modelle (zugangsgeschützte Modelle).
- **Standard-Whisper-Modell** — Voreinstellung für neue Transkriptionen.

---

## 10. Benutzerverwaltung (Mehrbenutzermodus)

Wenn der Mehrbenutzermodus aktiviert ist:
- Administratoren erstellen, bearbeiten, sperren und löschen Benutzerkonten.
- Neue Benutzer warten nach der Registrierung auf die Genehmigung durch den Administrator.
- Jedem Benutzer wird eine Rolle zugewiesen, die die verfügbaren Module bestimmt.

---

## 11. Projektverschlüsselung

AISTATE ermöglicht die Verschlüsselung von Projekten zum Schutz der Daten vor unbefugtem Zugriff.

### Konfiguration (Administrator)

Im Panel **Benutzerverwaltung → Sicherheit → Sicherheitsrichtlinie** konfiguriert der Administrator:

- **Projektverschlüsselung** — Verschlüsselungsfunktion aktivieren / deaktivieren.
- **Verschlüsselungsmethode** — wählen Sie eine der drei Methoden:

| Stufe | Algorithmus | Beschreibung |
|-------|-----------|-------------|
| **Light** | AES-128-GCM | Schnelle Verschlüsselung, Schutz vor unbefugtem Zugriff |
| **Standard** | AES-256-GCM | Standardstufe — Gleichgewicht zwischen Geschwindigkeit und Sicherheit |
| **Maximum** | AES-256-GCM + ChaCha20-Poly1305 | Doppelschichtverschlüsselung für sensible Daten |

- **Verschlüsselung erzwingen** — wenn aktiviert, können Benutzer keine unverschlüsselten Projekte erstellen.

Die gewählte Verschlüsselungsstufe gilt für alle nachfolgend von Benutzern erstellten Projekte.

### Ein verschlüsseltes Projekt erstellen

Beim Erstellen eines Projekts erscheint ein Kontrollkästchen **Projekt verschlüsseln** mit Informationen zur aktuellen Methode (z. B. „AES-256-GCM"). Das Kontrollkästchen ist standardmäßig aktiviert, wenn der Administrator die Verschlüsselung aktiviert hat, und gesperrt, wenn die Verschlüsselung erzwungen wird.

### Export und Import

- **Export** eines verschlüsselten Projekts — die `.aistate`-Datei ist immer verschlüsselt. Das System fragt nach einem **Export-Passwort** (getrennt vom Kontopasswort).
- **Import** — das System erkennt automatisch, ob die `.aistate`-Datei verschlüsselt ist. Falls ja — wird nach dem Passwort gefragt. Nach dem Import wird das Projekt gemäß der aktuellen Richtlinie des Administrators neu verschlüsselt.
- Ein unverschlüsseltes Projekt kann ohne Passwort ODER mit der Option „Export verschlüsseln" exportiert werden.

### <span style="color:red">⚠ Zugriffswiederherstellung — Schritt-für-Schritt-Verfahren</span>

<span style="color:red">Jedes verschlüsselte Projekt hat einen zufälligen Verschlüsselungsschlüssel (Project Key), der durch den Schlüssel des Benutzers geschützt ist (abgeleitet aus dessen Passwort). Zusätzlich wird der Projektschlüssel durch den **Master Key** des Administrators gesichert. Der Administrator **kann ein Projekt nicht allein entschlüsseln** — eine Mitwirkung des Benutzers ist erforderlich.</span>

#### <span style="color:red">Szenario 1: Benutzer hat das Passwort vergessen (Selbstwiederherstellung)</span>

<span style="color:red">Der Benutzer hat seine Wiederherstellungsphrase (12 Wörter, die bei der Kontoerstellung erhalten wurden).</span>

<span style="color:red">**Schritte für den Benutzer:**</span>
<span style="color:red">1. Klicken Sie auf dem Anmeldebildschirm auf **„Passwort vergessen"**.</span>
<span style="color:red">2. Geben Sie Ihre **Wiederherstellungsphrase** ein (12 Wörter, durch Leerzeichen getrennt).</span>
<span style="color:red">3. Das System überprüft die Phrase — bei Korrektheit erscheint ein Formular für ein neues Passwort.</span>
<span style="color:red">4. Legen Sie ein **neues Passwort** fest und bestätigen Sie es.</span>
<span style="color:red">5. Das System verschlüsselt automatisch die Schlüssel aller Ihrer verschlüsselten Projekte mit dem neuen Passwort neu.</span>
<span style="color:red">6. Melden Sie sich normal mit dem neuen Passwort an.</span>

<span style="color:red">**Keine Beteiligung des Administrators erforderlich** — der Vorgang ist vollautomatisch.</span>

#### <span style="color:red">Szenario 2: Benutzer hat das Passwort vergessen, besitzt aber die Wiederherstellungsphrase (administratorgestützte Wiederherstellung)</span>

<span style="color:red">Wenn die Selbstbedienungszurücksetzung nicht funktioniert hat oder durch eine Richtlinie deaktiviert ist:</span>

<span style="color:red">**Schritte für den Administrator:**</span>
<span style="color:red">1. Öffnen Sie **Benutzerverwaltung** → suchen Sie das Benutzerkonto.</span>
<span style="color:red">2. Klicken Sie auf **„Wiederherstellungstoken generieren"** — das System generiert ein Einmal-Token (gültig für 24 Stunden).</span>
<span style="color:red">3. Übermitteln Sie das Token an den Benutzer (persönlich, telefonisch oder über einen anderen sicheren Kanal).</span>

<span style="color:red">**Schritte für den Benutzer:**</span>
<span style="color:red">1. Gehen Sie zur Seite **Zugriffswiederherstellung** (Link auf dem Anmeldebildschirm).</span>
<span style="color:red">2. Geben Sie das vom Administrator erhaltene **Wiederherstellungstoken** ein.</span>
<span style="color:red">3. Geben Sie Ihre **Wiederherstellungsphrase** ein (12 Wörter).</span>
<span style="color:red">4. Legen Sie ein **neues Passwort** fest.</span>
<span style="color:red">5. Das System verschlüsselt die Projektschlüssel mit dem neuen Passwort neu.</span>
<span style="color:red">6. Das Token wird nach Verwendung ungültig.</span>

#### <span style="color:red">Szenario 3: Benutzer hat Passwort UND Wiederherstellungsphrase verloren (Master-Key-Wiederherstellung)</span>

<span style="color:red">Dies ist das einzige Szenario, in dem der **Master Key** verwendet wird.</span>

<span style="color:red">**Schritte für den Administrator:**</span>
<span style="color:red">1. Öffnen Sie **Benutzerverwaltung → Sicherheit → Verschlüsselung**.</span>
<span style="color:red">2. Geben Sie Ihr **Administratorpasswort** ein, um den Master Key freizuschalten.</span>
<span style="color:red">3. Wählen Sie das Benutzerkonto aus, das den Zugriff verloren hat.</span>
<span style="color:red">4. Klicken Sie auf **„Notfallwiederherstellung"** — das System verwendet den Master Key, um die Projektschlüssel des Benutzers zu entschlüsseln.</span>
<span style="color:red">5. Das System generiert eine **neue Wiederherstellungsphrase** für den Benutzer.</span>
<span style="color:red">6. Das System generiert ein **Einmal-Wiederherstellungstoken**.</span>
<span style="color:red">7. Übermitteln Sie dem Benutzer: das Token + die neue Wiederherstellungsphrase.</span>

<span style="color:red">**Schritte für den Benutzer:**</span>
<span style="color:red">1. Gehen Sie zur Seite **Zugriffswiederherstellung**.</span>
<span style="color:red">2. Geben Sie das **Token** vom Administrator ein.</span>
<span style="color:red">3. Geben Sie die **neue Wiederherstellungsphrase** vom Administrator ein.</span>
<span style="color:red">4. Legen Sie ein **neues Passwort** fest.</span>
<span style="color:red">5. Das System verschlüsselt die Projektschlüssel mit dem neuen Passwort neu.</span>

<span style="color:red">**WICHTIG:** Die neue Wiederherstellungsphrase muss sofort gespeichert und an einem sicheren Ort aufbewahrt werden!</span>

### <span style="color:red">⚠ Master-Key-Sicherung</span>

<span style="color:red">**WARNUNG:** Wenn ein Benutzer sein Passwort und seine Wiederherstellungsphrase verliert und der Administrator den Master Key verliert — **sind die Daten in verschlüsselten Projekten unwiederbringlich verloren**. Es gibt keine „Hintertür".</span>

<span style="color:red">**Pflichten des Administrators:**</span>
<span style="color:red">1. Klicken Sie nach der Initialisierung des Master Key im Verschlüsselungspanel auf **„Master Key sichern"**.</span>
<span style="color:red">2. Geben Sie das Administratorpasswort ein — das System zeigt den Schlüssel im Base64-Format an.</span>
<span style="color:red">3. **Speichern Sie den Schlüssel auf einem Offline-Medium** (USB-Stick, Ausdruck in einem Tresor) — speichern Sie ihn NICHT im System oder in E-Mails.</span>
<span style="color:red">4. Überprüfen Sie die Sicherung regelmäßig mit der Schaltfläche **„Master Key überprüfen"**.</span>

<span style="color:red">**Verlust des Master Key + Benutzerpasswort + Wiederherstellungsphrase = dauerhafter Datenverlust.**</span>

### <span style="color:red">⚠ Suche in verschlüsselten Projekten</span>

<span style="color:red">Die Projektliste (Name, Erstellungsdatum) ist immer sichtbar. Die **Inhaltssuche** (Transkriptionen, Notizen, Analyseergebnisse) erfordert jedoch eine Datenentschlüsselung und funktioniert **nur im aktiven (geöffneten) Projekt**. Es ist nicht möglich, mehrere verschlüsselte Projekte gleichzeitig zu durchsuchen.</span>

---

## 12. A.R.I.A. — KI-Assistent

Die schwebende A.R.I.A.-Schaltfläche (untere rechte Ecke) öffnet das KI-Assistentenpanel.

### Funktionen
- **KI-Chat** — stellen Sie Fragen zum aktuellen Kontext (Transkription, Analyse, Daten).
- **Automatischer Kontext** — der Assistent bezieht automatisch Daten von der aktuell geöffneten Seite ein.
- **Antwortvorlesen** (TTS) — hören Sie sich die Antwort des Assistenten an.
- **Hinweis-Chips** — vorgefertigte Fragen, die auf das aktuelle Modul zugeschnitten sind.
- **Verschiebbar** — die A.R.I.A.-Schaltfläche kann an eine beliebige Stelle auf dem Bildschirm gezogen werden (die Position wird gespeichert).

---

## 13. Audio-Player

Die Audio-Player-Leiste erscheint in Transkription und Diarisierung, wenn das Projekt eine Audiodatei enthält.

- **Abspielen / Pause** — Aufnahme abspielen oder stoppen.
- **Überspringen** ±5 Sekunden (Schaltflächen oder Klick auf den Fortschrittsbalken).
- **Wiedergabegeschwindigkeit** — 0.5×, 0.75×, 1×, 1.25×, 1.5×, 2× (wird im Browser gespeichert).
- **Klicken Sie auf ein Textsegment**, um das entsprechende Audiofragment abzuspielen.
- **Wellenformkarte** — Amplitudenvisualisierung mit Segmentmarkierungen.

---

## 14. Suche und Segmentbearbeitung

### Textsuche
- Verwenden Sie in Transkription und Diarisierung **Ctrl+F** oder das Lupensymbol in der Symbolleiste.
- Die Suche hebt Treffer hervor und zeigt die Anzahl an.
- Navigieren Sie zwischen den Treffern mit den Pfeilen ↑ ↓.

### Zusammenführen und Teilen von Segmenten
- **Segmente zusammenführen** — wählen Sie zwei benachbarte Blöcke aus und klicken Sie auf „Zusammenführen" (Symbolleistensymbol).
- **Segment teilen** — setzen Sie den Cursor in einen Block und klicken Sie auf „Teilen" → der Block wird an der Cursorposition geteilt.

---

## 15. Dunkel- / Hellmodus

- Klicken Sie auf das Themensymbol in der Seitenleiste (Sonnen- / Mondsymbol).
- Die Auswahl wird im Browser gespeichert.

---

## Tastaturkürzel

| Tastenkürzel | Aktion |
|----------|--------|
| **Esc** | Blockeditor schließen / Suche schließen |
| **Ctrl+F** | Textsuche öffnen (Transkription / Diarisierung) |
| **Ctrl+Enter** | Notiz speichern |
| **Ctrl+M** | Analystennotiz hinzufügen (AML / GSM / Crypto) |
| **Rechtsklick** | Blockeditor öffnen (Transkription / Diarisierung) |
| **Click segment** | Audiofragment abspielen |
