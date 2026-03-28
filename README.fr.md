# AISTATEweb Community (3.7.2 bêta)

[![English](https://flagcdn.com/24x18/gb.png) English](README.md) | [![Polski](https://flagcdn.com/24x18/pl.png) Polski](README.pl.md) | [![한국어](https://flagcdn.com/24x18/kr.png) 한국어](README.ko.md) | [![Español](https://flagcdn.com/24x18/es.png) Español](README.es.md) | [![Français](https://flagcdn.com/24x18/fr.png) Français](README.fr.md)

![Version](https://img.shields.io/badge/Version-3.7.2%20b%C3%AAta-orange)
![Édition](https://img.shields.io/badge/%C3%89dition-Community-blue)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Plateforme](https://img.shields.io/badge/Plateforme-Web-lightgrey)
![Licence](https://img.shields.io/badge/Licence-MIT-green)

* * *

AISTATEweb Community est un outil web pour la transcription audio, la diarisation des locuteurs, la traduction, l'analyse assistée par IA et la génération de rapports structurés — entièrement hors ligne, fonctionnant sur du matériel local.

#### Retours / Support

Si vous rencontrez des problèmes, avez des suggestions ou des demandes de fonctionnalités, veuillez me contacter à : **pawlict@proton.me**

* * *

## 🚀 Fonctionnalités principales

### 🎙️ Traitement de la parole
- Reconnaissance automatique de la parole (ASR) avec **Whisper**, **WhisperX** et **NVIDIA NeMo**
- Prise en charge de l'audio multilingue (PL / EN / UA / RU / BY et plus)
- Exécution locale et hors ligne des modèles (aucune dépendance au cloud)
- Transcription de haute qualité optimisée pour les enregistrements longs

### 🧩 Diarisation des locuteurs
- Diarisation avancée des locuteurs avec **pyannote** et **NeMo Diarization**
- Détection et segmentation automatiques des locuteurs
- Prise en charge des conversations multi-locuteurs (réunions, entretiens, appels)
- Moteurs et modèles de diarisation configurables

### 🌍 Traduction multilingue
- Traduction neuronale automatique propulsée par **NLLB-200**
- Pipeline de traduction entièrement hors ligne
- Sélection flexible des langues source et cible
- Conçu pour les flux de travail OSINT et d'analyse multilingue

### 🧠 Intelligence et analyse
- Analyse de contenu assistée par IA à l'aide de **modèles LLM** locaux
- Transformation de la parole brute et du texte en informations structurées
- Prise en charge des rapports analytiques et des flux de travail orientés renseignement

### 📱 Analyse GSM / BTS
- Import et analyse de **données de facturation GSM** (CSV, XLSX, PDF)
- **Visualisation cartographique** interactive des emplacements BTS (Leaflet + OpenStreetMap)
- Prise en charge des **cartes hors ligne** via MBTiles (raster PNG/JPG/WebP + vecteur PBF via MapLibre GL)
- Vues multiples : tous les points, parcours, clusters, trajets, couverture BTS, carte de chaleur, chronologie
- **Sélection de zone** (cercle / rectangle) pour les requêtes spatiales
- **Couches superposées** : bases militaires, aéroports civils, postes diplomatiques (données intégrées)
- **Import KML/KMZ** — couches superposées personnalisées depuis Google Earth et autres outils SIG
- Captures d'écran de carte avec filigrane (cartes en ligne et hors ligne + toutes les couches superposées)
- Graphe de contacts, carte de chaleur d'activité, analyse des contacts principaux
- Lecteur de chronologie avec animation par mois/jour

### 💰 AML — Analyse financière
- Pipeline d'analyse **anti-blanchiment d'argent** pour les relevés bancaires
- Détection automatique de banque et analyse de PDF pour les banques polonaises :
  PKO BP, ING, mBank, Pekao SA, Santander, Millennium, Revolut (+ repli générique)
- Prise en charge du format de relevé MT940 (SWIFT)
- Normalisation des transactions, classification basée sur des règles et notation des risques
- **Détection d'anomalies** : référence statistique + basée sur le ML (Isolation Forest)
- **Analyse de graphe** — visualisation du réseau de contreparties
- Analyse inter-comptes pour les enquêtes multi-comptes
- Résolution d'entités et mémoire des contreparties (étiquettes/notes persistantes)
- Analyse des dépenses, schémas comportementaux, catégorisation des commerçants
- Analyse assistée par LLM (constructeur de prompts pour les modèles Ollama)
- Génération de rapports HTML avec graphiques
- Profils d'anonymisation des données pour un partage sécurisé

### 🔗 Crypto — Analyse des transactions blockchain *(expérimental)*
- Analyse hors ligne des transactions de cryptomonnaies **BTC** et **ETH**
- Import depuis **WalletExplorer.com** (CSV) et plusieurs formats d'échanges (Binance, Etherscan, Kraken, Coinbase, et plus)
- Détection automatique du format à partir des signatures de colonnes CSV
- Notation des risques avec détection de schémas : peel chain, dust attack, round-trip, smurfing
- Base de données d'adresses sanctionnées OFAC et recherche de contrats DeFi connus
- **Graphe interactif des flux de transactions** (Cytoscape.js)
- Graphiques : chronologie du solde, volume mensuel, activité quotidienne, classement des contreparties (Chart.js)
- Analyse narrative assistée par LLM via Ollama
- *Ce module est actuellement en phase de test précoce — les fonctionnalités et formats de données peuvent évoluer*

### ⚙️ Gestion du GPU et des ressources
- **Gestionnaire de ressources GPU** intégré
- Planification et priorisation automatiques des tâches (ASR, diarisation, analyse)
- Exécution sécurisée des tâches concurrentes sans surcharge GPU
- Repli sur CPU lorsque les ressources GPU ne sont pas disponibles

### 📂 Flux de travail par projet
- Organisation des données orientée projet
- Stockage persistant de l'audio, des transcriptions, traductions et analyses
- Flux de travail analytiques reproductibles
- Séparation des données utilisateur et des processus système

### 📄 Rapports et export
- Export des résultats en **TXT**, **HTML**, **DOC** et **PDF**
- Rapports structurés combinant transcription, diarisation et analyse
- Rapports financiers AML avec graphiques et indicateurs de risque
- Résultats prêts à l'emploi pour la recherche, la documentation et les enquêtes

### 🌐 Interface web
- Interface web moderne (**AISTATEweb**)
- Suivi en temps réel de l'état et des journaux des tâches
- Interface multilingue (PL / EN)
- Conçue pour les environnements autonomes et multi-utilisateurs (bientôt)


* * *

## Prérequis

### Système (Linux)

Installez les paquets de base (exemple) :
    sudo apt update -y
    sudo apt install -y python3 python3-venv python3-pip git

### Python

Recommandé : Python 3.11+.

* * *
## pyannote / Hugging Face (requis pour la diarisation)

La diarisation utilise les pipelines **pyannote.audio** hébergés sur le **Hugging Face Hub**. Certains modèles pyannote sont **restreints**, ce qui signifie que vous devez :
  * posséder un compte Hugging Face,
  * accepter les conditions d'utilisation sur les pages des modèles,
  * générer un jeton d'accès **READ** et le fournir à l'application.

### Étape par étape (jeton + permissions)

  1. Créez un compte Hugging Face ou connectez-vous.
  2. Ouvrez les pages des modèles pyannote requis et cliquez sur **"Agree / Accept"** (conditions d'utilisation).
     Modèles typiques que vous devrez peut-être accepter (selon la version) :
     * `pyannote/segmentation` (ou `pyannote/segmentation-3.0`)
     * `pyannote/speaker-diarization` (ou `pyannote/speaker-diarization-3.1`)
  3. Accédez à vos **Paramètres Hugging Face → Jetons d'accès** et créez un nouveau jeton avec le rôle **READ**.
  4. Collez le jeton dans les paramètres d'AISTATE Web (ou fournissez-le comme variable d'environnement — selon votre configuration).
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

## Exécution
```
python3 AISTATEweb.py
```
Exemple (uvicorn) :
    python -m uvicorn webapp.server:app --host 0.0.0.0 --port 8000

Ouvrir dans le navigateur :
    http://127.0.0.1:8000

* * *
# AISTATEweb — Windows (WSL2 + GPU NVIDIA) Configuration

> **Important :** Sous WSL2, le pilote NVIDIA est installé **côté Windows**, pas à l'intérieur de Linux. N'installez **pas** les paquets `nvidia-driver-*` dans la distribution WSL.

---

### 1. Côté Windows

1. Activez WSL2 (PowerShell : `wsl --install` ou Fonctionnalités Windows).
2. Installez le dernier **pilote NVIDIA Windows** (Game Ready / Studio) — il fournit la prise en charge du GPU dans WSL2.
3. Mettez à jour WSL et redémarrez :
   ```powershell
   wsl --update
   wsl --shutdown
   ```

### 2. Dans WSL (Ubuntu recommandé)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3 python3-venv python3-pip ffmpeg
```

Vérifiez que le GPU est visible :
```bash
nvidia-smi
```

### 3. Installer AISTATEweb

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/pawlict/AISTATEweb.git
cd AISTATEweb

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel

# PyTorch avec CUDA (exemple : cu128)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

pip install -r requirements.txt
```

Vérifiez l'accès au GPU :
```bash
python -c "import torch; print('CUDA:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
```

### 4. Exécution

```bash
python3 AISTATEweb.py
```
Ouvrir dans le navigateur : http://127.0.0.1:8000

### Dépannage

Si `nvidia-smi` ne fonctionne pas dans WSL, assurez-vous que vous n'avez **pas** installé de paquets NVIDIA Linux. Supprimez-les si nécessaire :
```bash
sudo apt purge -y 'nvidia-*' 'libnvidia-*' && sudo apt autoremove --purge -y
```

---

## Références

- [NVIDIA : Guide utilisateur CUDA sur WSL](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
- [Microsoft : Installer WSL](https://learn.microsoft.com/windows/wsl/install)
- [PyTorch : Démarrage](https://pytorch.org/get-started/locally/)
- [pyannote.audio (Hugging Face)](https://huggingface.co/pyannote)
- [Whisper (OpenAI)](https://github.com/openai/whisper)
- [NLLB-200 (Meta)](https://huggingface.co/facebook/nllb-200-distilled-600M)
- [Ollama](https://ollama.com/)

---

"Ce projet est sous licence MIT (TEL QUEL). Les composants tiers sont sous licences séparées — voir THIRD_PARTY_NOTICES.md."

## bêta 3.7.2
- **Panneau Analyste** — nouveau panneau latéral remplaçant la barre de notes dans les pages de transcription et de diarisation
- **Notes par blocs avec étiquettes** — les notes peuvent désormais avoir des étiquettes colorées, affichées sous forme de bordure gauche sur les segments
- **PDF crypto Revolut** — analyseur pour les relevés de cryptomonnaies Revolut, intégré au pipeline AML
- **Base de données de jetons (TOP 200)** — classification des jetons connus/inconnus pour l'analyse crypto
- **Rapports améliorés** — rapports DOCX/HTML avec graphiques, filigranes, conclusions dynamiques, descriptions de sections
- **Déclencheur ARIA** — déclencheur flottant déplaçable avec persistance de position et placement intelligent du HUD
- Correction de la traduction bloquée à 5 % (cache de détection automatique du modèle)
- Correction du rapport de traduction perdant le formatage (retours à la ligne supprimés)
- Correction des résultats obsolètes de transcription/diarisation lors d'un nouvel envoi audio
- Middleware sans cache pour les fichiers statiques JS/CSS

## bêta 3.7.1
- **Analyse de cryptomonnaies — Binance** — analyse étendue des données de l'échange Binance
- Profilage comportemental des utilisateurs (10 profils : HODLer, Scalper, Day Trader, Swing Trader, Staker, Whale, Institutionnel, Alpha Hunter, Meme Trader, Bagholder)
- 18 cartes d'analyse forensique : contreparties internes, Pay C2C, adresses on-chain, flux de transit, cryptomonnaies de confidentialité, journaux d'accès, cartes de paiement + **NOUVEAU :** analyse temporelle, chaînes de conversion de jetons, détection de structuring/smurfing, wash trading, rampes d'accès fiat, analyse P2P, vélocité dépôt-retrait, analyse des frais, analyse des réseaux blockchain, sécurité étendue (VPN/proxy)
- Toutes les limites d'enregistrements supprimées — données complètes avec tableaux défilants
- Téléchargement des rapports sous forme de fichiers (HTML, TXT, DOCX)

## bêta 3.7
- **Analyse Crypto** *(expérimental)* — module d'analyse hors ligne des transactions blockchain (BTC/ETH), import CSV (WalletExplorer + 16 formats d'échanges), notation des risques, détection de schémas, graphe de flux, graphiques Chart.js, narration LLM — actuellement en phase de test approfondi
- Détection automatique de la langue source lors de l'envoi de fichier et du collage de texte (module de traduction)
- Export multilingue (toutes les langues traduites en une fois)
- Correction des noms de fichiers d'export DOCX (problème de tirets bas)
- Correction de l'erreur de synthèse de forme d'onde MMS TTS
- Correction de la langue coréenne manquante dans les résultats de traduction

## bêta 3.6
- **Analyse GSM / BTS** — module complet d'analyse de facturation GSM avec cartes interactives, chronologie, clusters, trajets, carte de chaleur, graphe de contacts
- **Analyse financière AML** — pipeline anti-blanchiment : analyse PDF (7 banques polonaises + MT940), détection d'anomalies basée sur des règles + ML, analyse de graphe, notation des risques, rapports assistés par LLM
- **Couches cartographiques** — bases militaires, aéroports, postes diplomatiques + import personnalisé KML/KMZ
- **Cartes hors ligne** — prise en charge MBTiles (raster + vecteur PBF via MapLibre GL)
- **Captures d'écran de carte** — capture complète incluant toutes les couches de tuiles, superpositions et marqueurs KML
- Correction de l'analyseur KML/KMZ (bug d'élément falsy ElementTree)
- Correction de la capture d'écran MapLibre GL canvas (preserveDrawingBuffer)
- Correction du changement de langue sur la page d'information

## bêta 3.5.1/3
- Correction de la sauvegarde/affectation des projets.
- Amélioration de l'analyseur pour ING banking

## bêta 3.5.0 (SQLite)
- Migration JSON -> SQLite

## bêta 3.4.0
- Ajout du multi-utilisateur

## bêta 3.2.3 (mise à jour traduction)
- Ajout du module de traduction
- Ajout de la page de paramètres NLLB
- Ajout de la possibilité de modifier les priorités des tâches
- Ajout du Chat LLM
- Analyse des sons d'arrière-plan

## bêta 3.0 - 3.1
- Introduction des modules LLM Ollama pour l'analyse de données
- Attribution / Planification GPU (mise à jour)

Cette mise à jour introduit un concept de **Gestionnaire de ressources GPU** dans l'interface et le flux interne pour réduire le risque de **chevauchement des charges de travail GPU** (par exemple, exécuter la diarisation + la transcription + l'analyse LLM en même temps).

### Quel problème cela résout
Lorsque plusieurs tâches GPU démarrent simultanément, cela peut entraîner :
- un épuisement soudain de la VRAM (OOM),
- des réinitialisations de pilote / erreurs CUDA,
- un traitement extrêmement lent dû à la contention,
- un comportement instable lorsque plusieurs utilisateurs déclenchent des tâches en même temps.

### Compatibilité ascendante
- Aucune modification de la disposition fonctionnelle des onglets existants.
- Seules la coordination d'admission GPU et l'étiquetage d'administration ont été mis à jour.

## bêta 2.1 - 2.2

- Changement de méthodologie d'édition des blocs
- Cette mise à jour se concentre sur l'amélioration de l'observabilité et de la convivialité des journaux de l'application.
- Correction : Refonte de la journalisation (Whisper + pyannote) + Export vers fichier
