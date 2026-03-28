# AISTATE Web — Informationen

**AISTATE Web** (*Artificial Intelligence Speech‑To‑Analysis‑Translation‑Engine*) ist eine Webanwendung für **Transkription**, **Sprecherdiarisierung**, **Übersetzung**, **GSM/BTS-Analyse** und **AML-Finanzanalyse**.

---

## 🚀 Funktionsumfang

- **Transkription** — Audio → Text (Whisper, WhisperX, NeMo)
- **Diarisierung** — „Wer hat wann gesprochen" + Sprechersegmente (pyannote, NeMo)
- **Übersetzung** — Text → andere Sprachen (NLLB‑200, vollständig offline)
- **Analyse (LLM / Ollama)** — Zusammenfassungen, Erkenntnisse, Berichte
- **GSM / BTS-Analyse** — Abrechnungsimport, BTS-Karte, Routen, Cluster, Zeitachse
- **Finanzanalyse (AML)** — Kontoauszugs-Parsing, Risikobewertung, Anomalieerkennung
- **Protokolle & Fortschritt** — Aufgabenüberwachung + Diagnose

---

## 🆕 Neuigkeiten in 3.7.1 beta

### 🔐 Kryptowährungsanalyse — Binance XLSX
- Erweiterte Analyse von Binance-Börsendaten
- Nutzerverhaltensprofilierung (10 Muster: HODLer, Scalper, Day Trader, Swing Trader, Staker, Whale, Institutional, Alpha Hunter, Meme Trader, Bagholder)
- 18 forensische Analysekarten:
  - Interne Gegenparteien, Pay C2C, On-Chain-Adressen, Durchleitungsflüsse, Privacy Coins, Zugriffsprotokolle, Zahlungskarten
  - **NEU:** Temporalanalyse (stündliche Verteilung, Bursts, Ruheperioden), Token-Konvertierungsketten, Structuring-/Smurfing-Erkennung, Wash Trading, Fiat On-/Off-Ramp-Analyse, P2P-Analyse, Einzahlungs-zu-Auszahlungs-Geschwindigkeit, Gebührenanalyse, Blockchain-Netzwerkanalyse, erweiterte Sicherheitsanalyse (VPN-/Proxy-Erkennung)

---

## 🆕 Neuigkeiten in 3.6 beta

### 📱 GSM / BTS-Analyse
- Import von Abrechnungsdaten (CSV, XLSX, PDF)
- Interaktive **BTS-Karte** mit mehreren Ansichten: Punkte, Pfad, Cluster, Fahrten, BTS-Abdeckung, Heatmap, Zeitachse
- **Offline-Karten** — MBTiles-Unterstützung (Raster PNG/JPG/WebP + Vektor PBF via MapLibre GL)
- **Overlay-Ebenen**: Militärbasen, Zivilflughäfen, diplomatische Vertretungen (integrierte Daten)
- **KML/KMZ-Import** — benutzerdefinierte Ebenen aus Google Earth und anderen GIS-Werkzeugen
- Flächenauswahl (Kreis / Rechteck) für räumliche Abfragen
- Kontaktgraph, Aktivitäts-Heatmap, Top-Kontakte-Analyse
- Kartenscreenshots mit Wasserzeichen (Online- & Offline-Karten + alle Overlay-Ebenen)

### 💰 Finanzanalyse (AML)
- **Anti‑Money Laundering**-Pipeline für Kontoauszüge
- Automatische Bankerkennung und PDF-Parsing: PKO BP, ING, mBank, Pekao SA, Santander, Millennium, Revolut (+ generischer Fallback)
- MT940 (SWIFT) Kontoauszugsformat-Unterstützung
- Transaktionsnormalisierung, regelbasierte Klassifizierung und Risikobewertung
- **Anomalieerkennung**: statistische Basislinie + ML (Isolation Forest)
- **Graph-Analyse** — Visualisierung des Gegenpartei-Netzwerks
- Kontenübergreifende Analyse für Multi-Konto-Ermittlungen
- Ausgabenanalyse, Verhaltensmuster, Händlerkategorisierung
- LLM-gestützte Analyse (Prompt-Builder für Ollama-Modelle)
- HTML-Berichte mit Diagrammen
- Datenanonymisierungsprofile für sicheres Teilen

---

## 🆕 Neuigkeiten in 3.5.1 beta

- **Textkorrektur** — Seite-an-Seite-Vergleich von Original- und korrigiertem Text, Modellauswahl (Bielik, PLLuM, Qwen3), erweiterter Modus.
- **Neugestaltete Projektansicht** — Kartengitter-Layout, Teaminformationen, Einladungen pro Karte.
- Kleinere UI- und Stabilitätskorrekturen.

---

## 🆕 Neuigkeiten in 3.2 beta

- **Übersetzungsmodul (NLLB)** – lokale mehrsprachige Übersetzung (inkl. PL/EN/ZH und weitere).
- **NLLB-Einstellungen** – Modellauswahl, Laufzeitoptionen, Sichtbarkeit des Modell-Caches.

---

## 📦 Woher die Modelle heruntergeladen werden

AISTATE Web liefert **keine** Modellgewichte im Repository mit. Modelle werden bei Bedarf heruntergeladen und lokal zwischengespeichert (je nach Modul):

- **Hugging Face Hub**: pyannote + NLLB (Standard-HF-Cache).
- **NVIDIA NGC / NeMo**: NeMo ASR-/Diarisierungsmodelle (NeMo/NGC-Caching-Verhalten).
- **Ollama**: LLM-Modelle, die vom Ollama-Dienst heruntergeladen werden.
---

## 🔐 Sicherheit & Benutzerverwaltung

AISTATE Web unterstützt zwei Bereitstellungsmodi:

- **Einzelbenutzer-Modus** — vereinfacht, keine Anmeldung erforderlich (lokal / selbst gehostet).
- **Mehrbenutzer-Modus** — vollständige Authentifizierung, Autorisierung und Kontoverwaltung (ausgelegt für 50–100 gleichzeitige Benutzer).

### 👥 Rollen & Berechtigungen

**Benutzerrollen** (Modulzugang):
- Transkryptor, Lingwista, Analityk, Dialogista, Strateg, Mistrz Sesji

**Administrative Rollen:**
- **Architekt Funkcji** — Verwaltung der Anwendungseinstellungen
- **Strażnik Dostępu** — Benutzerkontoverwaltung (Erstellen, Genehmigen, Sperren, Passwörter zurücksetzen)
- **Główny Opiekun (Superadmin)** — Vollzugriff auf alle Module und Administratorfunktionen

### 🔑 Sicherheitsmechanismen

- **Passwort-Hashing**: PBKDF2-HMAC-SHA256 (260.000 Iterationen)
- **Passwortrichtlinie**: konfigurierbar (keine / einfach / mittel / stark); Administratoren erfordern immer starke Passwörter (12+ Zeichen, Groß-/Kleinbuchstaben, Ziffer, Sonderzeichen)
- **Passwort-Sperrliste**: integriert + vom Administrator verwaltete benutzerdefinierte Liste
- **Passwortablauf**: konfigurierbar (Änderung nach X Tagen erzwingen)
- **Kontosperrung**: nach konfigurierbarer Anzahl fehlgeschlagener Versuche (Standard 5), automatische Entsperrung nach 15 Min.
- **Ratenbegrenzung**: Anmeldung und Registrierung gedrosselt (5 pro Minute pro IP)
- **Sitzungen**: sichere Tokens (secrets-Modul), HTTPOnly + SameSite=Lax Cookies, konfigurierbares Timeout (Standard 8h)
- **Wiederherstellungsphrase**: 12-Wörter BIP-39 Mnemonic (~132 Bit Entropie) für Self-Service-Passwortwiederherstellung
- **Benutzersperrung**: dauerhaft oder temporär, mit Begründung
- **Sicherheits-Header**: X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy

### 📝 Audit & Protokollierung

- Vollständiges Ereignisprotokoll: Anmeldungen, fehlgeschlagene Versuche, Passwortänderungen, Kontoerstellung/-löschung, Sperrungen, Entsperrungen
- Aufzeichnung von IP-Adresse und Browser-Fingerprint
- Dateibasierte Protokolle mit stündlicher Rotation + SQLite-Datenbank
- Benutzer-Anmeldehistorie + vollständiger Audit-Trail für Administratoren

### 📋 Registrierung & Genehmigung

- Selbstregistrierung mit obligatorischer Administratorgenehmigung (Rolle Strażnik Dostępu)
- Obligatorische Passwortänderung bei der ersten Anmeldung
- Wiederherstellungsphrase wird einmalig generiert und angezeigt

---

## ⚖️ Lizenzierung

### App-Lizenz

- **AISTATE Web**: **MIT License** (AS IS).

### Engines / Bibliotheken (Code-Lizenzen)

- **OpenAI Whisper**: **MIT**.
- **pyannote.audio**: **MIT**.
- **WhisperX**: **MIT** (Wrapper/Aligner – abhängig von der Paketversion).
- **NVIDIA NeMo Toolkit**: **Apache 2.0**.
- **Ollama (Server/CLI Repository)**: **MIT**.

### Modell-Lizenzen (Gewichte / Checkpoints)

> Modellgewichte werden **separat** vom Code lizenziert. Bitte überprüfen Sie stets die Modellkarte / Anbieterbedingungen.

- **Meta NLLB‑200 (NLLB)**: **CC‑BY‑NC 4.0** (nicht-kommerzielle Einschränkungen).
- **pyannote Pipelines (HF)**: modellabhängig; einige sind **zugangsbeschränkt** und erfordern die Annahme der Bedingungen auf der Modellseite.
- **NeMo-Modelle (NGC/HF)**: modellabhängig; einige Checkpoints werden unter Lizenzen wie **CC‑BY‑4.0** veröffentlicht, während einige NGC-Modelle die Abdeckung unter der NeMo Toolkit-Lizenz angeben — prüfen Sie die jeweilige Modellseite.
- **LLMs über Ollama**: modellabhängig, zum Beispiel:
  - **Meta Llama 3**: **Meta Llama 3 Community License** (Weiterverbreitung/Attribution + AUP).
  - **Mistral 7B**: **Apache 2.0**.
  - **Google Gemma**: **Gemma Terms of Use** (Vertragsbedingungen + Richtlinie).

### Karten & geografische Daten

- **Leaflet** (Karten-Engine): **BSD‑2‑Clause** — https://leafletjs.com
- **MapLibre GL JS** (PBF-Vektor-Rendering): **BSD‑3‑Clause** — https://maplibre.org
- **OpenStreetMap** (Online-Kartenkacheln): Kartendaten © OpenStreetMap-Mitwirkende, **ODbL 1.0** — Namensnennung erforderlich
- **OpenMapTiles** (PBF-Kachelschema): **BSD‑3‑Clause** (Schema); Daten unter ODbL
- **html2canvas** (Screenshots): **MIT**

### Wichtig

- Diese Seite ist eine Zusammenfassung. Siehe **THIRD_PARTY_NOTICES.md** im Repository für eine vollständige Liste.
- Für kommerzielle / organisatorische Nutzung achten Sie besonders auf **NLLB (CC‑BY‑NC)** und die Lizenzen Ihres gewählten LLM-Modells.

---

## 💬 Feedback / Support

Probleme, Vorschläge, Funktionswünsche: **pawlict@proton.me**
