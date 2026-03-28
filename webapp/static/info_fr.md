# AISTATE Web — Informations

**AISTATE Web** (*Artificial Intelligence Speech‑To‑Analysis‑Translation‑Engine*) est une application web pour la **transcription**, la **diarisation de locuteurs**, la **traduction**, l'**analyse GSM/BTS** et l'**analyse financière AML**.

---

## 🚀 Fonctionnalités

- **Transcription** — Audio → texte (Whisper, WhisperX, NeMo)
- **Diarisation** — « qui a parlé quand » + segments par locuteur (pyannote, NeMo)
- **Traduction** — Texte → autres langues (NLLB‑200, entièrement hors ligne)
- **Analyse (LLM / Ollama)** — résumés, analyses, rapports
- **Analyse GSM / BTS** — import de facturation, carte BTS, itinéraires, clusters, chronologie
- **Analyse financière (AML)** — analyse de relevés bancaires, scoring de risque, détection d'anomalies
- **Journaux et progression** — suivi des tâches + diagnostics

---

## 🆕 Nouveautés de la version 3.7.1 bêta

### 🔐 Analyse de cryptomonnaies — Binance XLSX
- Analyse étendue des données de l'exchange Binance
- Profilage comportemental (10 profils : HODLer, Scalper, Day Trader, Swing Trader, Staker, Whale, Institutional, Alpha Hunter, Meme Trader, Bagholder)
- 18 fiches d'analyse forensique :
  - Contreparties internes, Pay C2C, adresses on-chain, flux pass-through, cryptomonnaies de confidentialité, journaux d'accès, cartes de paiement
  - **NOUVEAU :** Analyse temporelle (distribution horaire, pics, dormance), chaînes de conversion de tokens, détection de structuration/smurfing, wash trading, analyse fiat on/off ramp, analyse P2P, vélocité dépôt-retrait, analyse des frais, analyse réseau blockchain, analyse de sécurité étendue (détection VPN/proxy)

---

## 🆕 Nouveautés de la version 3.6 bêta

### 📱 Analyse GSM / BTS
- Importation de données de facturation (CSV, XLSX, PDF)
- **Carte BTS** interactive avec multiples vues : points, trajet, clusters, voyages, couverture BTS, carte de chaleur, chronologie
- **Cartes hors ligne** — support MBTiles (raster PNG/JPG/WebP + vecteur PBF via MapLibre GL)
- **Couches superposées** : bases militaires, aéroports civils, ambassades (données intégrées)
- **Import KML/KMZ** — couches personnalisées depuis Google Earth et autres outils SIG
- Sélection de zone (cercle / rectangle) pour requêtes spatiales
- Graphe de contacts, carte de chaleur d'activité, analyse des contacts principaux
- Captures d'écran de carte avec filigrane (cartes en ligne et hors ligne + toutes les couches)

### 💰 Analyse financière (AML)
- Pipeline **Anti‑Money Laundering** pour relevés bancaires
- Détection automatique de banques et analyse PDF : PKO BP, ING, mBank, Pekao SA, Santander, Millennium, Revolut (+ fallback générique)
- Support du format MT940 (SWIFT)
- Normalisation des transactions, classification basée sur des règles et scoring de risque
- **Détection d'anomalies** : ligne de base statistique + ML (Isolation Forest)
- **Analyse de graphes** — visualisation du réseau de contreparties
- Analyse multi-comptes pour les investigations
- Analyse des dépenses, schémas comportementaux, catégorisation des commerces
- Analyse assistée par LLM (constructeur de prompts pour modèles Ollama)
- Rapports HTML avec graphiques
- Profils d'anonymisation des données pour un partage sécurisé

---

## 🆕 Nouveautés de la version 3.5.1 bêta

- **Correction de texte** — comparaison côte à côte de l'original vs. texte corrigé, sélecteur de modèle (Bielik, PLLuM, Qwen3), mode étendu.
- **Vue projet redessinée** — disposition en grille, info équipe, invitations par carte.
- Corrections mineures d'interface et de stabilité.

---

## 🆕 Nouveautés de la version 3.2 bêta

- **Module de traduction (NLLB)** — traduction multilingue locale (incl. PL/EN/ZH et plus).
- **Paramètres NLLB** — sélection de modèle, options d'exécution, visibilité du cache.

---

## 📦 Provenance des modèles

AISTATE web **n'inclut pas** les poids des modèles dans le dépôt. Les modèles sont téléchargés à la demande et mis en cache localement :

- **Hugging Face Hub** : pyannote + NLLB (cache HF standard).
- **NVIDIA NGC / NeMo** : modèles ASR/diarisation NeMo.
- **Ollama** : modèles LLM téléchargés par le service Ollama.
---

## 🔐 Sécurité et gestion des utilisateurs

AISTATE Web prend en charge deux modes de déploiement :

- **Mode utilisateur unique** — simplifié, sans connexion (local / auto-hébergé).
- **Mode multi-utilisateurs** — authentification complète, autorisation et gestion des comptes (conçu pour 50–100 utilisateurs simultanés).

### 👥 Rôles et permissions

**Rôles utilisateur** (accès aux modules) :
- Transkryptor, Lingwista, Analityk, Dialogista, Strateg, Mistrz Sesji

**Rôles administratifs :**
- **Architekt Funkcji** — gestion des paramètres de l'application
- **Strażnik Dostępu** — gestion des comptes utilisateurs (créer, approuver, bloquer, réinitialiser les mots de passe)
- **Główny Opiekun (superadmin)** — accès complet à tous les modules et fonctions d'administration

### 🔑 Mécanismes de sécurité

- **Hachage des mots de passe** : PBKDF2-HMAC-SHA256 (260 000 itérations)
- **Politique de mots de passe** : configurable (aucune / basique / moyenne / forte) ; les admins nécessitent toujours des mots de passe forts (12+ caractères)
- **Liste noire de mots de passe** : intégrée + liste personnalisée de l'admin
- **Expiration des mots de passe** : configurable (forcer le changement après X jours)
- **Verrouillage de compte** : après un nombre configurable de tentatives échouées (par défaut 5), déverrouillage auto après 15 min
- **Limitation de débit** : connexion et inscription limitées (5 par minute par IP)
- **Sessions** : jetons sécurisés, cookies HTTPOnly + SameSite=Lax, timeout configurable (par défaut 8h)
- **Phrase de récupération** : mnémonique BIP-39 de 12 mots (~132 bits d'entropie)
- **Bannissement d'utilisateurs** : permanent ou temporaire, avec motif
- **En-têtes de sécurité** : X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy

### 📝 Audit et journalisation

- Journal complet des événements : connexions, tentatives échouées, changements de mot de passe, création/suppression de comptes
- Enregistrement d'adresse IP et empreinte du navigateur
- Logs fichiers avec rotation horaire + base de données SQLite
- Historique de connexion + piste d'audit complète pour les administrateurs

### 📋 Inscription et approbation

- Auto-inscription avec approbation obligatoire de l'administrateur
- Changement obligatoire du mot de passe à la première connexion
- Phrase de récupération générée et affichée une seule fois

---

## ⚖️ Licences

### Licence de l'application

- **AISTATE Web** : **Licence MIT** (AS IS).

### Moteurs / bibliothèques (licences de code)

- **OpenAI Whisper** : **MIT**.
- **pyannote.audio** : **MIT**.
- **WhisperX** : **MIT**.
- **NVIDIA NeMo Toolkit** : **Apache 2.0**.
- **Ollama (serveur/CLI)** : **MIT**.

### Licences des modèles (poids / checkpoints)

> Les poids des modèles sont licenciés **séparément** du code. Vérifiez toujours les conditions du fournisseur.

- **Meta NLLB‑200 (NLLB)** : **CC‑BY‑NC 4.0** (restrictions non commerciales).
- **Pipelines pyannote (HF)** : dépend du modèle ; certains sont **restreints** et nécessitent l'acceptation des conditions.
- **Modèles NeMo (NGC/HF)** : dépend du modèle.
- **LLMs via Ollama** : dépend du modèle.

### Cartes et données géographiques

- **Leaflet** (moteur de cartes) : **BSD‑2‑Clause** — https://leafletjs.com
- **MapLibre GL JS** (rendu vecteur PBF) : **BSD‑3‑Clause** — https://maplibre.org
- **OpenStreetMap** (tuiles en ligne) : données © OpenStreetMap contributors, **ODbL 1.0** — attribution requise
- **OpenMapTiles** (schéma PBF) : **BSD‑3‑Clause** ; données sous ODbL
- **html2canvas** (captures) : **MIT**

### Important

- Cette page est un résumé. Consultez **THIRD_PARTY_NOTICES.md** dans le dépôt pour la liste complète.
- Pour un usage commercial / organisationnel, portez une attention particulière à **NLLB (CC‑BY‑NC)** et aux licences des modèles LLM choisis.

---

## 💬 Contact / support

Problèmes, suggestions, demandes de fonctionnalités : **pawlict@proton.me**
