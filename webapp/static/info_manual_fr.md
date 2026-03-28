# AISTATE Web Community — Manuel d'utilisation

> **Édition :** Community (open-source) · **Version :** 3.7.2 bêta
>
> L'édition Community est une version gratuite et complète d'AISTATE Web pour un usage individuel, éducatif et de recherche. Elle comprend tous les modules : transcription, diarisation, traduction, analyse (LLM, AML, GSM, Crypto), Chat LLM et rapports.

---

## 1. Projets

Les projets constituent l'élément central du travail avec AISTATE. Chaque projet stocke un fichier audio, les résultats de transcription, la diarisation, les traductions, les analyses et les notes.

### Création d'un projet
1. Accédez à l'onglet **Projets** dans la barre latérale.
2. Cliquez sur **Créer un projet** et saisissez un nom (par ex. « Interview_2026_01 »).
3. Ajoutez éventuellement un fichier audio (WAV, MP3, M4A, FLAC, OGG, OPUS, MP4, AAC).
4. Après la création, le projet devient actif — il est visible dans la barre supérieure.

### Ouverture et gestion
- Cliquez sur la carte d'un projet pour l'ouvrir et le définir comme actif.
- Exportez un projet vers un fichier `.aistate` (menu contextuel sur la carte) — transférez-le vers une autre machine.
- Importez un fichier `.aistate` pour ajouter un projet provenant d'une autre instance.

### Suppression
- Supprimez un projet depuis le menu contextuel de la carte. Vous pouvez choisir une méthode d'écrasement de fichiers (rapide / pseudo-aléatoire / HMG IS5 / Gutmann).

---

## 2. Transcription

Module de reconnaissance vocale (Speech-to-Text).

### Utilisation
1. Assurez-vous de disposer d'un projet actif contenant un fichier audio (ou ajoutez-en un à l'aide du bouton de la barre d'outils).
2. Sélectionnez le **moteur ASR** (Whisper ou NeMo) et le **modèle** (par ex. `large-v3`).
3. Sélectionnez la **langue** de l'enregistrement (ou `auto` pour la détection automatique).
4. Cliquez sur le bouton **Transcrire** (icône IA).

### Résultat
- Le texte apparaît en blocs avec des horodatages (`[00:00:05.120 - 00:00:08.340]`).
- **Cliquez** sur un bloc pour lire le segment audio.
- **Clic droit** sur un bloc pour ouvrir l'éditeur en ligne — modifiez le texte et le nom du locuteur.
- Toutes les modifications sont enregistrées automatiquement.

### Détection de sons *(expérimental)*
- Si vous disposez d'un modèle de détection de sons installé (YAMNet, PANNs, BEATs), activez l'option **Détection de sons** dans la barre d'outils.
- Les sons détectés (toux, rires, musique, sirène, etc.) apparaîtront sous forme de marqueurs dans le texte.

### Relecture du texte
- Utilisez la fonctionnalité **Relecture** pour corriger automatiquement la transcription à l'aide d'un modèle LLM (par ex. Bielik, PLLuM, Qwen3).
- Comparez l'original avec le texte corrigé dans une vue de comparaison côte à côte (diff).

### Notes
- Le panneau **Notes** (à droite) vous permet d'ajouter une note globale et des notes pour chaque bloc individuel.
- L'icône de note à côté de chaque bloc indique si une note lui est attribuée.

### Rapports
- Dans la barre d'outils, sélectionnez les formats (HTML, DOC, TXT) et cliquez sur **Enregistrer** — les rapports sont sauvegardés dans le dossier du projet.

---

## 3. Diarisation

Module d'identification des locuteurs — « qui parle quand ».

### Utilisation
1. Vous avez besoin d'un projet actif contenant un fichier audio.
2. Sélectionnez le **moteur de diarisation** : pyannote (audio) ou diarisation NeMo.
3. Définissez éventuellement le nombre de locuteurs (ou laissez en automatique).
4. Cliquez sur **Diariser**.

### Résultat
- Chaque bloc possède une étiquette de locuteur (par ex. `SPEAKER_00`, `SPEAKER_01`).
- **Correspondance des locuteurs** : remplacez les étiquettes par des noms (par ex. `SPEAKER_00` → « Jean Dupont »).
- Saisissez les noms dans les champs → cliquez sur **Appliquer la correspondance** → les étiquettes seront remplacées.
- La correspondance est enregistrée dans `project.json` — elle sera chargée automatiquement à la réouverture du projet.

### Édition
- Clic droit sur un bloc pour ouvrir l'éditeur : modifiez le texte, le locuteur, lisez le segment.
- Les notes fonctionnent de la même manière que dans la Transcription.

### Rapports
- Exportez les résultats au format HTML / DOC / TXT depuis la barre d'outils.

---

## 4. Traduction

Module de traduction multilingue basé sur les modèles NLLB (Meta).

### Utilisation
1. Accédez à l'onglet **Traduction**.
2. Sélectionnez un **modèle NLLB** (doit être installé dans les paramètres NLLB).
3. Collez du texte ou importez un document (TXT, DOCX, PDF, SRT).
4. Sélectionnez la **langue source** et les **langues cibles** (vous pouvez en sélectionner plusieurs).
5. Cliquez sur **Générer**.

### Modes
- **Rapide (NLLB)** — modèles plus petits, traduction plus rapide.
- **Précis (NLLB)** — modèles plus grands, meilleure qualité.

### Fonctionnalités supplémentaires
- **Conserver le formatage** — préserve les paragraphes et les sauts de ligne.
- **Glossaire terminologique** — utilisez un glossaire de termes spécialisés.
- **TTS (Lecteur)** — écoutez le texte source et la traduction (nécessite un moteur TTS installé).
- **Préréglages** — configurations prêtes à l'emploi (documents professionnels, articles scientifiques, transcriptions audio).

### Rapports
- Exportez les résultats au format HTML / DOC / TXT.

---

## 5. Chat LLM

Interface de conversation avec des modèles LLM locaux (via Ollama).

### Utilisation
1. Accédez à **Chat LLM**.
2. Sélectionnez un **modèle** dans la liste (doit être installé dans Ollama).
3. Saisissez un message et cliquez sur **Envoyer**.

### Options
- **Prompt système** — définissez le rôle de l'assistant (par ex. « Vous êtes un juriste spécialisé en droit français »).
- **Température** — contrôlez la créativité des réponses (0 = déterministe, 1.5 = très créatif).
- **Historique** — les conversations sont sauvegardées automatiquement. Revenez à une conversation précédente depuis la barre latérale.

---

## 6. Analyse

L'onglet Analyse contient quatre modules : LLM, AML, GSM et Crypto. Basculez entre eux à l'aide des onglets situés en haut.

### 6.1 Analyse LLM

Module d'analyse de contenu à l'aide de modèles LLM.

1. Sélectionnez les **sources de données** dans le panneau latéral (transcription, diarisation, notes, documents).
2. Choisissez des **prompts** — modèles prédéfinis ou créez les vôtres.
3. Cliquez sur **Générer** (icône IA dans la barre d'outils).

#### Analyse rapide
- Analyse automatique et légère déclenchée après la transcription.
- Utilise un modèle plus petit (configuré dans les paramètres LLM).

#### Analyse approfondie
- Analyse complète à partir des sources et des prompts sélectionnés.
- Prend en charge les prompts personnalisés : saisissez une instruction dans le champ « Prompt personnalisé » (par ex. « Rédigez un compte-rendu de réunion avec les décisions prises »).

### 6.2 Analyse AML (Anti-Money Laundering)

Module d'analyse financière pour les relevés bancaires.

1. Téléversez un relevé bancaire (PDF ou MT940) — le système détecte automatiquement la banque et analyse les transactions.
2. Consultez les **informations du relevé**, les comptes et cartes identifiés.
3. Classez les transactions : neutre / légitime / suspecte / surveillance.
4. Consultez les **graphiques** : solde dans le temps, catégories, canaux, tendance mensuelle, activité quotidienne, principaux contreparties.
5. **Anomalies ML** — l'algorithme Isolation Forest détecte les transactions inhabituelles.
6. **Graphe de flux** — visualisation des relations entre contreparties (dispositions : flux, montant, chronologie).
7. Posez des questions au modèle LLM sur les données financières (section « Question / instruction pour l'analyse »).
8. Téléchargez un **rapport HTML** avec les résultats de l'analyse.

#### Panneau analyste (AML)
- Panneau gauche avec recherche, note globale et notes par élément.
- **Ctrl+M** — ajoutez rapidement une note à l'élément en cours.
- Étiquettes : neutre, légitime, suspecte, surveillance + 4 étiquettes personnalisées (double-cliquez pour renommer).

### 6.3 Analyse GSM / BTS

Module d'analyse des données de facturation GSM.

1. Chargez les données de facturation (CSV, XLSX, PDF, ZIP contenant plusieurs fichiers).
2. Consultez le **résumé** : nombre d'enregistrements, période, appareils (IMEI/IMSI).
3. **Anomalies** — détection de schémas inhabituels (activité nocturne, itinérance, double-SIM, etc.).
4. **Numéros spéciaux** — identification des numéros d'urgence, de service, etc.
5. **Graphe de contacts** — visualisation des contacts les plus fréquents (Top 5/10/15/20).
6. **Enregistrements** — tableau de tous les enregistrements avec filtrage, recherche et gestion des colonnes.
7. **Graphiques d'activité** — carte de chaleur de la distribution horaire, activité nocturne et de fin de semaine.
8. **Carte BTS** — carte interactive avec plusieurs vues :
   - Tous les points, trajet, clusters, déplacements, frontière, couverture BTS, carte de chaleur, chronologie.
   - **Couches superposées** : bases militaires, aéroports civils, postes diplomatiques.
   - **Import KML/KMZ** — couches personnalisées depuis Google Earth.
   - **Cartes hors ligne** — prise en charge MBTiles (raster + vector PBF).
   - **Sélection de zone** — cercle / rectangle pour les requêtes spatiales.
9. **Lieux détectés** — clusters des emplacements les plus fréquents.
10. **Passages de frontières** — détection des déplacements à l'étranger.
11. **Nuitées** — analyse des lieux de nuitée.
12. **Analyse narrative (LLM)** — génération d'un rapport d'analyse GSM à l'aide d'un modèle Ollama.
13. **Rapports** — export au format HTML / DOCX / TXT. Notes analytiques DOCX avec graphiques.

#### Disposition des sections
- Le bouton **Personnaliser la disposition** dans le panneau analyste vous permet de modifier l'ordre et la visibilité des sections (glisser / cocher-décocher).

#### Panneau analyste (GSM)
- Panneau gauche avec recherche, note globale et notes par élément.
- **Ctrl+M** — ajoutez rapidement une note à l'enregistrement en cours.

#### Carte autonome
- Ouvrez une carte sans données de facturation (bouton carte dans la barre d'outils).
- Mode édition — ajoutez des points, des polygones, des couches utilisateur.

### 6.4 Analyse Crypto *(expérimentale)*

Module d'analyse hors ligne des transactions de cryptomonnaies (BTC / ETH) et des données d'échanges.

#### Import de données
1. Accédez à l'onglet **Crypto** dans le module Analyse.
2. Cliquez sur **Charger les données** et sélectionnez un fichier CSV ou JSON.
3. Le système détecte automatiquement le format :
   - **Blockchain** : WalletExplorer.com, Etherscan
   - **Échanges** : Binance, Kraken, Coinbase, Revolut et plus (16+ formats)
4. Après le chargement, les informations sur les données apparaissent : nombre de transactions, période, portefeuille de jetons.

#### Vue des données
- **Mode échange** — tableau des transactions d'échange avec types (dépôt, retrait, échange, staking, etc.).
- **Mode blockchain** — tableau des transactions on-chain avec adresses et montants.
- **Portefeuille de jetons** — liste des jetons avec descriptions, classification (connu / inconnu) et valeurs.
- **Dictionnaire des types de transactions** — survolez un type pour voir sa description (infobulle).

#### Classification et examen
- Classez les transactions : neutre / légitime / suspecte / surveillance.
- Le système classifie automatiquement certaines transactions en fonction de schémas.

#### Anomalies
- **Détection d'anomalies ML** — l'algorithme détecte les transactions inhabituelles (montants élevés, heures inhabituelles, schémas suspects).
- Types d'anomalies : peel chain, dust attack, round-trip, smurfing, structuring.
- Base de données d'adresses sanctionnées **OFAC** et recherche de contrats DeFi connus.

#### Graphiques
- **Chronologie du solde** — évolution du solde dans le temps (avec normalisation logarithmique).
- **Volume mensuel** — totaux des transactions par mois.
- **Activité quotidienne** — répartition des transactions par jour de la semaine.
- **Classement des contreparties** — partenaires de transaction les plus fréquents.

#### Graphe de flux
- **Graphe de transactions** interactif (Cytoscape.js) — visualisation des flux entre adresses/contreparties.
- Cliquez sur un nœud pour voir les détails.

#### Profilage utilisateur (Binance)
- 10 profils comportementaux : HODLer, Scalper, Day Trader, Swing Trader, Staker, Whale, Institutional, Alpha Hunter, Meme Trader, Bagholder.
- 18 fiches d'analyse forensique (contreparties internes, adresses on-chain, wash trading, P2P, analyse des frais et plus).

#### Analyse narrative (LLM)
- Cliquez sur **Générer l'analyse** → un modèle Ollama génère un rapport descriptif avec conclusions et recommandations.

#### Rapports
- Exportez les résultats au format **HTML / DOCX / TXT** depuis la barre d'outils.

#### Panneau analyste (Crypto)
- Panneau gauche avec note globale et notes par transaction.
- **Ctrl+M** — ajoutez rapidement une note à la transaction en cours.
- Étiquettes : neutre, légitime, suspecte, surveillance + 4 étiquettes personnalisées.

---

## 7. Journaux

Surveillance des tâches et diagnostics système.

- Accédez à l'onglet **Journaux** pour consulter l'état de toutes les tâches (transcription, diarisation, analyse, traduction).
- Copiez les journaux dans le presse-papiers ou enregistrez-les dans un fichier.
- Videz la liste des tâches (ne supprime pas les projets).

---

## 8. Panneau d'administration

### Paramètres GPU
- Surveillez les cartes GPU, la VRAM et les tâches actives.
- Définissez les limites de simultanéité (emplacements par GPU, fraction de mémoire).
- Consultez et gérez la file d'attente des tâches.
- Définissez les priorités par type de tâche (glissez pour réorganiser).

### Paramètres ASR
- Installez les modèles Whisper (tiny → large-v3).
- Installez les modèles ASR et de diarisation NeMo.
- Installez les modèles de détection sonore (YAMNet, PANNs, BEATs) *(expérimental)*.

### Paramètres LLM
- Parcourez et installez les modèles Ollama (analyse rapide, analyse approfondie, financier, relecture, traduction, vision/OCR).
- Ajoutez un modèle Ollama personnalisé.
- Configurez les jetons (Hugging Face).

### Paramètres NLLB
- Installez les modèles de traduction NLLB (distilled-600M, distilled-1.3B, base-3.3B).
- Consultez les informations sur les modèles (taille, qualité, prérequis).

### Paramètres TTS
- Installez les moteurs de lecture : Piper (rapide, CPU), MMS (plus de 1100 langues), Kokoro (qualité maximale).
- Testez les voix avant utilisation.

---

## 9. Paramètres

- **Langue de l'interface** — basculez entre PL / EN / KO.
- **Jeton Hugging Face** — requis pour les modèles pyannote (modèles à accès restreint).
- **Modèle Whisper par défaut** — préférence pour les nouvelles transcriptions.

---

## 10. Gestion des utilisateurs (mode multi-utilisateurs)

Si le mode multi-utilisateurs est activé :
- Les administrateurs créent, modifient, bannissent et suppriment les comptes utilisateurs.
- Les nouveaux utilisateurs attendent l'approbation de l'administrateur après leur inscription.
- Chaque utilisateur dispose d'un rôle attribué qui détermine les modules disponibles.

---

## 11. Chiffrement des projets

AISTATE permet de chiffrer les projets afin de protéger les données contre tout accès non autorisé.

### Configuration (administrateur)

Dans le panneau **Gestion des utilisateurs → Sécurité → Politique de sécurité**, l'administrateur configure :

- **Chiffrement des projets** — activer / désactiver la fonctionnalité de chiffrement.
- **Méthode de chiffrement** — choisissez l'une des trois méthodes :

| Niveau | Algorithme | Description |
|--------|-----------|-------------|
| **Léger** | AES-128-GCM | Chiffrement rapide, protection contre les accès occasionnels |
| **Standard** | AES-256-GCM | Niveau par défaut — équilibre entre vitesse et sécurité |
| **Maximum** | AES-256-GCM + ChaCha20-Poly1305 | Double couche de chiffrement pour les données sensibles |

- **Imposer le chiffrement** — lorsque cette option est activée, les utilisateurs ne peuvent pas créer de projets non chiffrés.

Le niveau de chiffrement sélectionné s'applique à tous les projets créés ultérieurement par les utilisateurs.

### Création d'un projet chiffré

Lors de la création d'un projet, une case à cocher **Chiffrer le projet** apparaît avec des informations sur la méthode en cours (par ex., « AES-256-GCM »). La case est cochée par défaut si l'administrateur a activé le chiffrement, et verrouillée si le chiffrement est imposé.

### Exportation et importation

- **Exportation** d'un projet chiffré — le fichier `.aistate` est toujours chiffré. Le système demande un **mot de passe d'exportation** (distinct du mot de passe du compte).
- **Importation** — le système détecte automatiquement si le fichier `.aistate` est chiffré. Si c'est le cas, il demande le mot de passe. Après l'importation, le projet est rechiffré conformément à la politique en vigueur de l'administrateur.
- Un projet non chiffré peut être exporté sans mot de passe OU avec l'option « chiffrer l'exportation ».

### <span style="color:red">⚠ Récupération d'accès — procédures étape par étape</span>

<span style="color:red">Chaque projet chiffré possède une clé de chiffrement aléatoire (Project Key), protégée par la clé de l'utilisateur (dérivée de son mot de passe). De plus, la clé du projet est sécurisée par la **Master Key** de l'administrateur. L'administrateur **ne peut pas déchiffrer un projet seul** — l'intervention de l'utilisateur est requise.</span>

#### <span style="color:red">Scénario 1 : L'utilisateur a oublié son mot de passe (récupération autonome)</span>

<span style="color:red">L'utilisateur dispose de sa phrase de récupération (12 mots reçus lors de la création du compte).</span>

<span style="color:red">**Étapes pour l'utilisateur :**</span>
<span style="color:red">1. Sur l'écran de connexion, cliquez sur **« Mot de passe oublié »**.</span>
<span style="color:red">2. Saisissez votre **phrase de récupération** (12 mots, séparés par des espaces).</span>
<span style="color:red">3. Le système vérifie la phrase — si elle est correcte, un formulaire de nouveau mot de passe apparaît.</span>
<span style="color:red">4. Définissez un **nouveau mot de passe** et confirmez.</span>
<span style="color:red">5. Le système rechiffre automatiquement les clés de tous vos projets chiffrés avec le nouveau mot de passe.</span>
<span style="color:red">6. Connectez-vous normalement avec le nouveau mot de passe.</span>

<span style="color:red">**Aucune intervention de l'administrateur n'est nécessaire** — le processus est entièrement automatique.</span>

#### <span style="color:red">Scénario 2 : L'utilisateur a oublié son mot de passe mais dispose de sa phrase de récupération (récupération assistée par l'administrateur)</span>

<span style="color:red">Si la réinitialisation en libre-service n'a pas fonctionné ou est désactivée par la politique :</span>

<span style="color:red">**Étapes pour l'administrateur :**</span>
<span style="color:red">1. Ouvrez **Gestion des utilisateurs** → trouvez le compte de l'utilisateur.</span>
<span style="color:red">2. Cliquez sur **« Générer un jeton de récupération »** — le système génère un jeton à usage unique (valide pendant 24 heures).</span>
<span style="color:red">3. Transmettez le jeton à l'utilisateur (en personne, par téléphone ou via un autre canal sécurisé).</span>

<span style="color:red">**Étapes pour l'utilisateur :**</span>
<span style="color:red">1. Accédez à la page de **récupération d'accès** (lien sur l'écran de connexion).</span>
<span style="color:red">2. Saisissez le **jeton de récupération** reçu de l'administrateur.</span>
<span style="color:red">3. Saisissez votre **phrase de récupération** (12 mots).</span>
<span style="color:red">4. Définissez un **nouveau mot de passe**.</span>
<span style="color:red">5. Le système rechiffre les clés des projets avec le nouveau mot de passe.</span>
<span style="color:red">6. Le jeton est invalidé après utilisation.</span>

#### <span style="color:red">Scénario 3 : L'utilisateur a perdu son mot de passe ET sa phrase de récupération (récupération par Master Key)</span>

<span style="color:red">Il s'agit du seul scénario où la **Master Key** est utilisée.</span>

<span style="color:red">**Étapes pour l'administrateur :**</span>
<span style="color:red">1. Ouvrez **Gestion des utilisateurs → Sécurité → Chiffrement**.</span>
<span style="color:red">2. Saisissez votre **mot de passe administrateur** pour déverrouiller la Master Key.</span>
<span style="color:red">3. Sélectionnez le compte utilisateur ayant perdu l'accès.</span>
<span style="color:red">4. Cliquez sur **« Récupération d'urgence »** — le système utilise la Master Key pour déchiffrer les clés de projet de l'utilisateur.</span>
<span style="color:red">5. Le système génère une **nouvelle phrase de récupération** pour l'utilisateur.</span>
<span style="color:red">6. Le système génère un **jeton de récupération à usage unique**.</span>
<span style="color:red">7. Transmettez à l'utilisateur : le jeton + la nouvelle phrase de récupération.</span>

<span style="color:red">**Étapes pour l'utilisateur :**</span>
<span style="color:red">1. Accédez à la page de **récupération d'accès**.</span>
<span style="color:red">2. Saisissez le **jeton** reçu de l'administrateur.</span>
<span style="color:red">3. Saisissez la **nouvelle phrase de récupération** reçue de l'administrateur.</span>
<span style="color:red">4. Définissez un **nouveau mot de passe**.</span>
<span style="color:red">5. Le système rechiffre les clés des projets avec le nouveau mot de passe.</span>

<span style="color:red">**IMPORTANT :** La nouvelle phrase de récupération doit être immédiatement sauvegardée et conservée dans un endroit sûr !</span>

### <span style="color:red">⚠ Sauvegarde de la Master Key</span>

<span style="color:red">**AVERTISSEMENT :** Si un utilisateur perd son mot de passe et sa phrase de récupération, et que l'administrateur perd la Master Key — **les données des projets chiffrés seront irrécupérables**. Il n'existe aucune « porte dérobée ».</span>

<span style="color:red">**Responsabilités de l'administrateur :**</span>
<span style="color:red">1. Après l'initialisation de la Master Key, cliquez sur **« Sauvegarder la Master Key »** dans le panneau de chiffrement.</span>
<span style="color:red">2. Saisissez le mot de passe administrateur — le système affiche la clé au format base64.</span>
<span style="color:red">3. **Enregistrez la clé sur un support hors ligne** (clé USB, impression dans un coffre-fort) — ne la stockez PAS dans le système ni par courriel.</span>
<span style="color:red">4. Vérifiez périodiquement la sauvegarde à l'aide du bouton **« Vérifier la Master Key »**.</span>

<span style="color:red">**Perte de la Master Key + mot de passe utilisateur + phrase de récupération = perte définitive des données.**</span>

### <span style="color:red">⚠ Recherche dans les projets chiffrés</span>

<span style="color:red">La liste des projets (nom, date de création) est toujours visible. Cependant, la **recherche de contenu** (transcriptions, notes, résultats d'analyse) nécessite le déchiffrement des données et fonctionne **uniquement dans le projet actif (ouvert)**. Il n'est pas possible d'effectuer une recherche simultanée dans plusieurs projets chiffrés.</span>

---

## 12. A.R.I.A. — Assistant IA

Le bouton flottant A.R.I.A. (coin inférieur droit) ouvre le panneau de l'assistant IA.

### Fonctionnalités
- **Discussion IA** — posez des questions sur le contexte actuel (transcription, analyse, données).
- **Contexte automatique** — l'assistant inclut automatiquement les données de la page actuellement ouverte.
- **Lecture des réponses** (TTS) — écoutez la réponse de l'assistant.
- **Suggestions rapides** — questions prêtes à l'emploi adaptées au module en cours.
- **Déplaçable** — le bouton A.R.I.A. peut être glissé n'importe où sur l'écran (la position est mémorisée).

---

## 13. Lecteur audio

La barre du lecteur audio apparaît dans Transcription et Diarisation lorsque le projet contient un fichier audio.

- **Lecture / Pause** — lancez ou arrêtez l'enregistrement.
- **Avance/retour** de ±5 secondes (boutons ou clic sur la barre de progression).
- **Vitesse de lecture** — 0.5×, 0.75×, 1×, 1.25×, 1.5×, 2× (enregistrée dans le navigateur).
- **Cliquez sur un segment de texte** pour lire le fragment audio correspondant.
- **Carte de forme d'onde** — visualisation de l'amplitude avec marqueurs de segments.

---

## 14. Recherche et édition de segments

### Recherche de texte
- Dans Transcription et Diarisation, utilisez **Ctrl+F** ou l'icône de loupe dans la barre d'outils.
- La recherche met en surbrillance les correspondances et affiche le nombre de résultats.
- Naviguez entre les correspondances avec les flèches ↑ ↓.

### Fusion et division de segments
- **Fusionner des segments** — sélectionnez deux blocs adjacents et cliquez sur « Fusionner » (icône de la barre d'outils).
- **Diviser un segment** — placez le curseur dans un bloc et cliquez sur « Diviser » → le bloc est scindé à la position du curseur.

---

## 15. Mode sombre / clair

- Cliquez sur l'icône de thème dans la barre latérale (icône soleil / lune).
- Le choix est mémorisé dans le navigateur.

---

## Raccourcis clavier

| Raccourci | Action |
|-----------|--------|
| **Esc** | Fermer l'éditeur de bloc / fermer la recherche |
| **Ctrl+F** | Ouvrir la recherche de texte (transcription / diarisation) |
| **Ctrl+Enter** | Enregistrer la note |
| **Ctrl+M** | Ajouter une note d'analyste (AML / GSM / Crypto) |
| **Clic droit** | Ouvrir l'éditeur de bloc (transcription / diarisation) |
| **Clic sur un segment** | Lire le fragment audio |
