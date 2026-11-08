# New PRONOTE — espace professeur & H Parallel

Interface professeur moderne : accueil, classes, évaluations, discussions, agenda, documents et rapports H. L’ouverture de la copie déclenche la chaîne H → Gladia / Linkup → MP4 en arrière-plan, sans prompt. Identité visuelle H Company, Plus Jakarta Sans et Fira Code locales. Le dossier de l’accueil est fictif ; la connexion au PRONOTE de l’établissement est séparée dans `/pilot`, et le diagnostic du client natif dans `/native`.

## Connexion PRONOTE autonome

Dans `/pilot` ou le paquet bureau reconstruit, deux choix sont disponibles :

- **Ouvrir mon PRONOTE** : accès direct (option officielle `?login=true`, si autorisée par l’établissement) ou redirection ENT. Après connexion dans la fenêtre dédiée et confirmation dans l’app, le texte de la vue ouverte est actualisé toutes les 10 secondes. La lecture automatique peut être désactivée ; elle ne navigue pas à votre place. La fermeture, l’arrêt ou une erreur de connexion interrompt la lecture. Les pièces jointes, grilles dessinées et iframes ne sont pas importées.
- **Connexion automatique** : authentification par identifiants PRONOTE, adaptateur ENT proposé, ou contenu JSON d’un QR mobile et son PIN. L’app effectue la première synchronisation, puis actualise toutes les 5 minutes par défaut (fréquence réglable entre 1 minute et 1 heure), tant qu’elle reste ouverte. Le connecteur `pronotepy==2.15.7` est non officiel. Les comptes élèves et parents peuvent fournir le profil, les cours et devoirs des 14 prochains jours, et les notes de la période courante ; les indisponibilités restent affichées. Pour un parent, les données pédagogiques concernent le premier enfant, explicitement indiqué. Le compte professeur fournit uniquement son profil : les classes, notes et cours professeur ne sont pas pris en charge par ce connecteur. Le parcours navigateur reste disponible.

La première authentification et les validations de sécurité restent à effectuer par l’utilisateur. La mémorisation facultative ne sauvegarde qu’un jeton mobile issu du parcours QR, jamais le mot de passe personnel. Si la session est mémorisée, l’app tente de la reprendre à son lancement et remplace le jeton après rotation. Une session expirée nécessite une nouvelle connexion. **Déconnecter et oublier la session** supprime le jeton et les données en mémoire. Fermer l’app arrête les tâches mais conserve un jeton volontairement mémorisé pour le prochain lancement.

Les préférences et le jeton sont dans le dossier de données local du pilote (`mvp/data` en développement, `~/Library/Application Support/PronotePilot` sur Mac, `%LOCALAPPDATA%/PronotePilot` sur Windows). Sur POSIX, les fichiers privés ont le mode 0600. Les données synchronisées restent en mémoire et ne sont pas envoyées aux services IA ni injectées dans l’accueil fictif. Les routes `/api/pronote/connection*` sont désactivées sur le serveur hébergé partagé.

Installer les dépendances actualisées puis relancer le serveur en développement. Pour distribuer les deux choix dans le paquet autonome, reconstruire avec `mvp/desktop/build.sh` sur Mac ou `mvp/desktop/build-windows.ps1` sur Windows. Les anciennes archives de téléchargement ne sont pas mises à jour par une modification du code local.

## Lancer

Depuis la racine du dépôt :

```sh
./mvp/run.sh
```

Prérequis : Python 3.12, `uv`, `ffmpeg` et `ffprobe`. Sur macOS, la voix française `Thomas` de `say` produit les vocaux de test et la narration. Linux : installer `espeak-ng`, ainsi que DejaVu Sans. Ouvrir http://127.0.0.1:8000.

1. Ouvrir la copie d’Alex depuis l’accueil ou les évaluations. Le mode connecté est sélectionné par défaut.
2. Continuer dans Discussions, Agenda ou Documents pendant que H travaille. Son volet affiche les actions réellement reçues.
3. Relire la transcription, ses repères, les citations scolaires et les ressources Linkup. Chaque lien scolaire ouvre la version exacte utilisée par H.
4. Regarder la capsule MP4, puis la valider. Aucun message n’est envoyé aux parents.
5. Keep conserve le rapport dans Rapports H ; Dismiss ferme le volet sans effacer le dossier.
6. Dans le profil en bas à gauche, remplacer le vocal par « Comment peut-il progresser ? », puis rouvrir la copie. Le même déclencheur produit une autre recherche et une autre vidéo.

Le rapport affiche un résumé, la capsule et l’accès à l’entraînement. **Voir le détail** ouvre une modale défilante contenant l’analyse complète, la transcription, l’évaluation figée, les preuves, les sources et le suivi. L’en-tête et le bouton de fermeture restent visibles pendant la lecture.

Les préférences choisies sont conservées localement. Le mode hors ligne est explicitement scénarisé, utile sans crédits API. La recherche de documents fonctionne aussi avec ⌘K.

**Noter un élève** : depuis l’accueil, les évaluations, la copie ou « Mes élèves », cliquer sur **Noter l’élève**. Choisir l’évaluation, saisir la note, le maximum et l’appréciation, puis **Enregistrer et préparer**. Pour le dossier d’Alex, cette action lance un nouveau rapport et une capsule dans le mode sélectionné. La saisie est figée dans une pièce `teacher-assessment` : la note et l’appréciation figurent dans le résumé, les preuves, la narration et les sous-titres. Les modifications changent l’empreinte du dossier, sans modifier les anciens rapports ni remplacer la copie d’origine. Une nouvelle évaluation d’Alex peut également être sélectionnée. Les autres élèves ajoutés localement conservent leur suivi ; aucun dossier de copie n’est inventé pour eux. Aucune synchronisation avec PRONOTE.

**Dicter la note avec Gladia** : dans le même formulaire, cliquer sur **Dicter une note**, autoriser le micro, parler puis **Arrêter et transcrire**. Exemple : « Note Alex pour le devoir et mets-lui douze sur vingt, appréciation : bon travail, pense à justifier ton raisonnement. » L’import d’un vocal est aussi disponible. Le serveur transmet l’audio à Gladia, puis extrait une seule note et son barème (chiffres, nombres français, zéro et décimales). La transcription est affichée et les champs sont remplis. Relire puis **Enregistrer et préparer**. Un nom ambigu, une autre évaluation ou une valeur incohérente ne modifie pas la note. Fermer le formulaire arrête le micro. Maximum : 60 secondes au micro, 20 Mo à l’import. `GLADIA_API_KEY` reste côté serveur ; un service indisponible produit une erreur visible. La dictée Gladia est réelle, y compris si la préparation du rapport est réglée sur le scénario hors ligne.

Le lancement `POST /api/workspace/documents/copie/open` accepte la saisie validée dans `teacher_assessment` (élève, évaluation, titre, date, note, maximum, appréciation et date de saisie). `POST /api/workspace/grading/transcribe` reçoit un multipart `audio` et retourne la transcription Gladia et les valeurs reconnues sans enregistrer la note. Les fichiers audio temporaires sont effacés après transcription.

L’ouverture directe de `/school/copie` déclenche aussi le mode démo. Les URL utilisées par H portent `agent=1` pour éviter une boucle de déclenchement.

## Deux modes explicites

- **Démo hors ligne** : vocaux fictifs synthétisés, transcriptions de référence et dossiers scénarisés. Aucun appel H/Gladia/Linkup. Le MP4 est réellement rendu par Python + FFmpeg. Aucune source externe n’est inventée : l’absence de résultat Linkup est affichée.
- **Réel** : H utilise le navigateur Chrome dédié du SDK (`host=user_device`, mode texte en lecture seule) pour visiter le portail local. Six fonctions Python sont exposées comme custom tools : `get_evidence_catalog(document_ids)`, `transcribe_audio()`, `search_resources(topic, purpose)`, `validate_dossier(dossier)`, `render_capsule(validated_dossier_id)` et `inspect_capsule(render_id)`. Le parcours demande deux recherches distinctes, `reference` puis `exercise`, soit sept invocations utiles au minimum. Le cache Linkup est propre à la requête et à son objectif ; les sources sont fusionnées avec des identifiants stables. H sélectionne des extraits exacts des pièces figées, soumet son dossier à la validation, corrige les erreurs éventuelles, puis déclenche et inspecte le MP4. Le programme vérifie encore les références et les identifiants en fin de session. Un rendu réussi est réutilisé plutôt que facturé deux fois. Une erreur API reste une erreur visible, sans bascule silencieuse vers le scénario hors ligne.

### Appels réels visibles dans le volet H

Le volet affiche les invocations effectivement exécutées, les outils distincts, les réussites, les erreurs, les appels en cours et les résultats réutilisés depuis le cache. Chaque appel conserve son nom, ses paramètres résumés, son résultat, sa durée et la session H. Le compteur est indépendant des messages de suivi : deux messages « début / fin » ne font jamais deux appels. Un appel servi depuis le cache compte comme une invocation, avec la mention « en cache », sans prétendre à un nouvel appel fournisseur.

Le périmètre est explicitement celui des **outils métier H** ; les actions du navigateur H ne sont pas incluses dans ce compteur. Le mode hors ligne affiche zéro et les anciens rapports sans trace affichent « Non mesuré ». Les nouvelles préparations utilisent une version de workflow distincte afin de ne pas réutiliser un ancien résultat non instrumenté. Les traces persistent dans `state.json` et sont accessibles via `/api/jobs/{id}` (`tool_calls` et `tool_call_summary`). Les connecteurs natif et PRONOTE en fond disposent également de traces de leurs propres outils, distinctes du parcours web de préparation.

L’inspection vérifie le fichier MP4, une durée positive, la présence d’une vidéo et d’une piste audio, ainsi qu’une piste de sous-titres ou un fichier WebVTT associé. Les éventuels sous-titres incrustés par DemoBro restent à confirmer visuellement ; ils ne sont jamais déclarés vérifiés par la simple configuration du rendu. La validation humaine et le partage manuel restent inchangés.

Après mise à jour, relancer le serveur avec `./mvp/run.sh`, choisir **Réel**, puis ouvrir la copie pour suivre les appels dans le volet H. Les validations automatisées n’utilisent aucun crédit API : `.venv/bin/python -m pytest -q mvp`.

Le mode réel lit les clés dans `credentials/.env.hackathon`, `mvp/.env` ou l’environnement : `H_COMPANY_API_KEY`, `H_COMPANY_BASE_URL`, `GLADIA_API_KEY`, `LINKUP_API_KEY`. Les clés restent côté Python. Le navigateur dédié est géré par le SDK H et utilise son propre profil ; il peut rester ouvert après une session. Les appels utilisent les crédits des comptes existants.

Les recherches Linkup sont limitées à des domaines pédagogiques, sans nom d’élève. Les réponses conservent titre, URL, extrait et requête. Le barème et la copie expliquent la note ; une référence externe aide à comprendre et progresser. Les citations ne constituent pas une vérification automatique de toute la justesse pédagogique : la validation humaine reste nécessaire.

## Entraînement interactif Pythagore

Depuis un rapport d’évaluation prêt portant sur Pythagore, **Essayer l’entraînement** ouvre un parcours guidé : repérer l’hypoténuse, choisir l’égalité de Pythagore, puis compléter une conclusion avec la longueur et son unité. Le professeur peut essayer les réponses, recommencer avec un autre triangle, puis valider l’activité avant de télécharger son fichier HTML autonome.

La version livrée par défaut est une **simulation locale explicite, sans appel Devin**. Elle utilise une activité de démonstration préconstruite ; ni le suivi ni le fichier exporté ne la présentent comme du code produit par Devin. Une analyse de démonstration reste indiquée comme scénarisée. L’analyse des copies, les sources et les capsules H restent inchangées ; les sorties scolaires conservent leur parcours H.

Le raccordement réel utilise l’API Devin pour créer une session, suivre sa progression et récupérer le fichier HTML produit. L’accès nécessite `DEVIN_API_KEY` et `DEVIN_ORG_ID` dans l’environnement ou `mvp/.env`, puis un redémarrage du serveur. Ne pas placer ces secrets dans une issue, un fichier versionné ou le navigateur. Le brief envoyé contient les compétences et contraintes de l’exercice, sans copie, vocal, identité d’élève ni texte privé du rapport. La session réelle est une action explicite distincte de la simulation ; un échec ne bascule pas silencieusement en démo.

La prévisualisation utilise un iframe isolé, autorisé à exécuter ses scripts mais sans accès à l’origine de l’application. Sa politique de contenu bloque les connexions réseau et formulaires externes. Les fichiers sont conservés séparément de l’analyse, avec une empreinte et une validation du professeur propres à l’entraînement. La correction est limitée aux choix guidés et réponses structurées ; aucune note scolaire n’est modifiée.

Routes : `GET/POST /api/jobs/{id}/practice`, `POST /api/jobs/{id}/practice/approve`, `GET /api/jobs/{id}/practice/preview` et `/download`. Le lancement accepte explicitement `mode: "simulation"` ou `mode: "live"`. Les réponses distinguent la simulation de l’appel fournisseur et conservent l’état, la provenance et le suivi de l’activité.

Presentation layer (`mvp/practice_theme.py`, `mvp/static/practice-theme.css`, version `new-pronote-v1`): the preview response only appends one trusted `<style>` (H tokens plus the Latin subsets of Plus Jakarta Sans as `data:` fonts) and one constant Escape bridge script before `</head>`. The CSP changes in exactly one directive, `font-src 'none'` → `font-src data:` (HTTP header and the artifact's meta policy of the preview); `sandbox allow-scripts`, `connect-src 'none'`, `frame-ancestors 'self'` and the iframe `sandbox="allow-scripts"` (no `allow-same-origin`) are unchanged. The stored file is checked against its SHA-256 before theming and never rewritten; the download stays the original bytes. The response carries `X-Calli-Presentation` and `X-Calli-Original-SHA256`, and the practice status exposes `presentation.original_sha256`.

Référence : [sessions et fichiers de l’API Devin](https://docs.devin.ai/api-reference/common-flows). La vérification de l’API authentifiée reste à réaliser avec l’accès de Wilfred ; les tests locaux utilisent des réponses simulées. Le raccordement est suivi dans [l’issue #1, avec @wilfred-dore](https://github.com/Fran-cois/H-Hack-nov26/issues/1).

## Données et fichiers

- `fixtures/alex.json` : un élève, un rendez-vous, trois messages, quatre pièces et deux textes de vocaux.
- `fixtures/*.wav` : vocaux fictifs générés au premier lancement, ignorés par Git.
- `data/<job>/` : état, dossier JSON, quatre diapositives PNG, narrations WAV, SRT/VTT et MP4 H.264/AAC avec piste de sous-titres. Résultats locaux ignorés par Git.
- `pronote-reference/` : paquet Mac officiel et fichiers web publics examinés. Ignorés par Git, non redistribués avec le code.
- `pronote-analysis.json` : provenance, signature, empreinte et observations d’inspection.

La préparation est dédupliquée par le vocal, les documents, les messages, l’identité, le rendez-vous et le mode. Un instantané complet et une copie du vocal sont figés avant le lancement de H. Les tâches sont exécutées en arrière-plan et leur résultat est conservé. Après un redémarrage, une tâche interrompue est signalée en échec. Dans le parcours natif, sa reprise doit être explicite : rouvrir une copie déjà acquittée ne relance pas les appels fournisseurs. Les imports vocaux sont limités à 20 Mo et nécessitent le mode réel. Le rendez-vous est positionné à deux heures après la création de l’espace puis conservé ; les horizons ne sont pas des délais d’attente.

Le serveur écoute uniquement sur la boucle locale et bloque les hôtes et origines étrangers. Il ne s’agit pas d’un serveur multi-utilisateur de production. La validation marque la capsule relue ; le téléchargement local du brouillon reste disponible. Ce n’est pas un contrôle d’accès.

## Vérifier

```sh
uv pip install --python .venv/bin/python pytest
.venv/bin/python -m pytest -q mvp/test_mvp.py mvp/test_workspace.py mvp/test_native_pipeline.py mvp/native/test_native_documents.py
```

Tests sans crédit API : documents disponibles, isolation des fichiers, validation après rendu, lancement unique, changement de scénario et filtrage de domaines Linkup. Pour vérifier la chaîne réelle, choisir « Réel » puis ouvrir la copie et attendre le statut prêt. Un simple test de connexion API ne valide pas la navigation ni les custom tools.

Notation et dictée (sans crédits API) : `node --test mvp/test_management_grading.cjs` puis `.venv/bin/python -m pytest -q mvp/test_teacher_assessment.py mvp/test_teacher_assessment_routes.py mvp/test_grading_voice.py`. Les tests couvrent la saisie, la transcription simulée, les limites, l’identité, le nettoyage du micro et des fichiers, l’invalidation du cache, les instantanés et la transmission de la note et de l’appréciation au rendu hors ligne et aux outils H.

## Références

- Téléchargement PRONOTE : https://www.index-education.com/fr/telecharger-pronote.php
- Démo officielle : https://demo.index-education.net/pronote/professeur.html?fd=1
- H custom tools : https://hub.hcompany.ai/agents-api/custom-tools
- H navigateur local : https://hub.hcompany.ai/agents-api/your-browser
- H mode texte : https://hub.hcompany.ai/agents-api/browser/configuration
- Gladia : https://docs.gladia.io/chapters/pre-recorded-stt/quickstart
- Linkup : https://docs.linkup.so/pages/documentation/endpoints/search/overview

## Intégration au vrai PRONOTE Mac et mode local

L’entrée principale `http://127.0.0.1:8000/` ouvre New PRONOTE. Le compagnon natif est accessible à `/native`. Le prototype scolaire fictif reste séparé à `/demo`, et le film DemoBro du prototype à `/demo-video`.

La rétro-ingénierie de l’installateur a permis d’extraire le vrai PRONOTE Monoposte 2026.2.8 et l’archive officielle `Base Exemple PRONOTE 2026.zip`. Le paquet Mac téléchargé ne contenait que le client réseau, sans base locale. La démo native utilise le moteur Windows fourni avec ce paquet Mac, dans une bouteille séparée, et les exécutables Monoposte extraits du paquet officiel. Les exécutables PRONOTE ne sont pas patchés et l’enregistrement/licence n’est pas modifié : la fenêtre indique « Version non enregistrée ». Le lanceur `PRONOTE Démo locale.app` est un assemblage de développement propre à ce projet, distinct du client réseau signé d’origine.

Les fichiers installés par PRONOTE au lancement peuvent produire des caches et journaux dans le paquet extrait. L’installateur Mac original conserve sa signature vérifiée ; le contrôle strict de l’application extraite peut signaler ces caches/journaux. Aucun contournement Gatekeeper ou changement de protection système n’est effectué.

- `native/extract_installshield.py` extrait les fichiers embarqués dans le conteneur InstallScript, sans exécuter l’installation.
- `unshield` extrait ensuite `data1.cab` et `data2.cab`.
- `native/prepare_demo.py` prépare une copie séparée et le lanceur local. La base .not de travail n’est jamais écrasée lorsqu’elle existe déjà.
- `native/pronote_context.c` est compilé avec MinGW. Il lit uniquement les fenêtres de `PRONOTE Monoposte.exe` / `Client PRONOTE.exe` dans la bouteille de démonstration, via Win32. Il n’injecte aucun code, ne change aucune note et ignore les champs de saisie.
- `native/win32_bridge.py` transmet ces relevés au compagnon local. Le titre de fenêtre confirme l’ouverture de la vraie Base Exemple.
- `native_ai.py` expose ces relevés comme custom tool à une vraie session H, sans lui donner le contrôle du poste du professeur. Les rapports gardent les citations vérifiées et les inconnues. Le dossier Alex du prototype n’est jamais injecté dans les données natives.
- `native/Notifier.swift` fournit un volet macOS flottant et les actions natives Keep/Dismiss. Les notifications restent soumises à l’autorisation macOS. L’OCR optionnel d’une fenêtre nécessite une autorisation distincte ; les contrôles Win32 n’en ont pas besoin.

Les grilles dessinées sur mesure ne sont pas forcément exposées par Win32. Pour le dossier fictif de Fanny, copie, barème et consigne ont été importés dans le vrai client, puis ouverts depuis leurs liens natifs. PRONOTE décode ses pièces dans son répertoire Temp et les ouvre dans Aperçu. Le connecteur lit ces PDF réellement exportés, sans prétendre lire toutes les notes de la base.

Pour reconstruire le lanceur après extraction des deux paquets officiels :

```sh
.venv/bin/python -c 'from mvp.native.prepare_demo import bundle; print(bundle())'
```

Puis utiliser « Ouvrir PRONOTE en démo locale » sur `/native`. Prérequis supplémentaires : `unshield` et `x86_64-w64-mingw32-gcc` pour l’extraction et le connecteur.

## Vidéo DemoBro vérifiée

`data/product-demo-v2/h-parallel-demo.mp4` : film privé de 65,97 secondes, H.264/AAC, narration et sous-titres français, généré via le MCP DemoBro. Il montre le prototype du rapport parallèle (copie → rapport → Keep → retour à la copie), pas l’intégration native. Le script `generate_demo.py` maintient un serveur de snapshot isolé et un tunnel temporaire ; validation, sonde des sélecteurs et estimation précèdent le rendu. Les ressources du serveur principal et les identifiants ne sont pas exposés.

## Vérification de New PRONOTE

Deux exécutions connectées conservées en local : `78f6163fe6ec` (points, 87,77 s) et `272502a01533` (progression, 85,68 s). Même copie, mêmes documents, même rendez-vous ; vocal, passages retenus, requête Linkup et vidéo différents. Les scripts de ces exemples ont été relus : le journal de chaque dossier conserve cette étape, les réponses H originales et les sources. La capsule reste non validée tant que le professeur ne l’approuve pas.

`data/new-pronote-verification.json` conserve les sessions, empreintes vidéo, fournisseurs et comparaison des deux scénarios. Rejouer la vérification :

```sh
.venv/bin/python -m mvp.verify_workspace_run 78f6163fe6ec
.venv/bin/python -m mvp.verify_workspace_run 272502a01533
```

Le film de l’interface moderne se génère avec `python -m mvp.generate_workspace_demo --job-id ID --render`. Son snapshot ne contient que les données fictives autorisées et les médias du dossier ; le bandeau précise qu’il s’agit d’une relecture condensée de l’exécution enregistrée. Le serveur natif, ses titres de fenêtres, les API sensibles et les identifiants ne sont pas exposés.

## Synchroniser Google Calendar

Agenda → **Connecter Google Calendar**, autoriser Google, puis **Synchroniser les rendez-vous**. Un calendrier « New PRONOTE · Démonstration » reçoit les rendez-vous fictifs. Relancer la synchronisation met à jour les mêmes événements sans doublons. Synchronisation manuelle à sens unique ; les modifications Google ne sont pas importées. Aucun participant n’est invité. Déconnecter révoque l’accès et efface les jetons locaux ; les événements Google restent disponibles.

Configuration développeur : activer Google Calendar API dans votre projet Google Cloud, configurer l’écran de consentement (ajouter votre compte comme utilisateur test si nécessaire), créer un client OAuth de type **Application Web**, et enregistrer exactement cette URI de redirection :

```
http://127.0.0.1:8000/api/calendar/callback
```

Dans `mvp/.env` (ignoré par Git), ajouter `GOOGLE_CLIENT_ID=...` et `GOOGLE_CLIENT_SECRET=...`, puis redémarrer l’app. Ouvrir l’app sur `http://127.0.0.1:8000`. Le scope `calendar.app.created` limite l’accès aux calendriers créés par l’app. Les jetons sont stockés côté serveur dans `mvp/data/google-calendar-private.json`, avec permissions privées, jamais exposés au navigateur.

Références : [OAuth Google](https://developers.google.com/identity/protocols/oauth2/web-server), [Calendar API](https://developers.google.com/workspace/calendar/api/v3/reference).

## Pilote : un professeur avec son PRONOTE local ou distant

Lancer `./mvp/run.sh`, puis ouvrir **http://127.0.0.1:8000/pilot**.
Ce parcours local ne nécessite pas de clé API : il vérifie d’abord la lecture réelle.

1. Installer le Client PRONOTE réseau officiel adapté au serveur de l’établissement. Demander à l’administrateur l’adresse, le port et le parcours de connexion professeur (direct ou ENT). Le port proposé dans le formulaire doit être confirmé par l’établissement.
2. Dans `/pilot`, enregistrer l’établissement, l’URL HTTPS de l’espace professeur (facultative, sans paramètres de connexion), le serveur, le port et le chemin absolu de l’application `.app` installée. Les paramètres serveur sont un aide-mémoire : le compagnon ne modifie pas la configuration interne de PRONOTE. Pour utiliser l’espace web plutôt que le Client Mac, choisir le mode distant décrit ci-dessous.
3. Cliquer « Ouvrir le client et activer la lecture texte ». Saisir le serveur et le port dans le Client PRONOTE, puis s’authentifier directement dans ce client. Aucun identifiant, mot de passe ou code MFA n’est stocké par le formulaire du pilote.
4. Autoriser le compagnon Parallèle dans les réglages macOS d’accessibilité si nécessaire. Les contrôles Windows peuvent ne pas exposer de texte. Après connexion seulement, ouvrir la vue pédagogique utile puis cliquer « Activer la lecture visuelle de la fenêtre ». Autoriser la capture d’écran macOS si demandée. L’OCR vise une fenêtre du processus de l’application sélectionnée ; si PRONOTE utilise un processus auxiliaire non reconnu, le diagnostic peut rester « fenêtre non trouvée ». Aucun repli vers une autre fenêtre n’est utilisé dans le pilote.
5. Vérifier le texte et son horodatage sur `/pilot`. Vérifier avec le professeur que les éléments affichés correspondent exactement à la vue ouverte. Utiliser `/native` pour conserver le relevé si utile. Cliquer « Arrêter la lecture » avant d’ouvrir une autre vue sensible ou de quitter la séance.

Le fichier de configuration `mvp/data/pronote-pilot.json` est privé (0600), local et ignoré par Git. Les relevés sont dans `mvp/data/native-context.json` et, après Keep, `mvp/data/native-reports/`. L’arrêt conserve ces fichiers ; ce n’est pas une suppression. Le compagnon doit être relancé après une recompilation. Ne pas exposer ce serveur local par tunnel ou sur le réseau.

Critère de réussite du pilote : le bon client est ouvert, le professeur se connecte lui-même, le relevé horodaté contient des éléments pédagogiques vérifiés, puis l’arrêt empêche de nouveaux relevés. Un état « observed » seul ne prouve pas l’accès à une copie ou au barème.

Le pilote ne transmet pas automatiquement les relevés réels à un fournisseur IA. La préparation H existante reste limitée à la base d’exemple. L’accueil New PRONOTE reste sur données fictives : aucune importation des classes, des rendez-vous ou des notes réelles, aucun rapport complet ni vidéo depuis le compte réel n’est annoncé. Ce pilote est une validation du connecteur local, pas une mise en production multi-utilisateur.


### Espace PRONOTE distant (sans Client Mac)

Dans `/pilot`, choisir **Espace PRONOTE distant dans le navigateur**, renseigner l’URL HTTPS exacte de l’espace professeur de l’établissement (sans paramètres de session), puis enregistrer. Le serveur, le port et le chemin du client Mac ne sont pas nécessaires dans ce mode.

1. Cliquer « Ouvrir l’espace PRONOTE distant ». Chrome/Chromium doit être installé sur la machine qui exécute l’application. Le navigateur dédié est distinct de votre navigateur habituel ; le pilote n’utilise aucun service de navigateur hébergé.
2. S’authentifier personnellement dans cette fenêtre, via PRONOTE ou la redirection ENT. Revenir sur le domaine de l’espace PRONOTE configuré puis ouvrir la vue pédagogique utile.
3. Dans `/pilot`, cocher la confirmation de connexion puis cliquer « Relever la vue web ». L’application lit le texte rendu visible, sans champs de saisie. Une origine différente ou un champ de mot de passe bloque le relevé. Ce contrôle ne prouve pas à lui seul que l’utilisateur est connecté : le professeur doit vérifier le résultat affiché.
4. Vérifier le texte, l’URL sans paramètres et l’horodatage. Les contenus d’iframes, copies jointes et grilles dessinées peuvent manquer. Aucun clic dans PRONOTE ni modification de notes n’est automatisé.
5. « Arrêter la lecture » ferme le navigateur dédié et efface le relevé web en mémoire. Le pilote ne sauvegarde ni ce relevé web ni les identifiants/cookies. Il faudra se reconnecter lors d’une nouvelle ouverture.

Changer et enregistrer la configuration arrête la connexion précédente. Le mode web ne requiert pas de clé H, Gladia ou Linkup et ne leur transmet pas les données. Le serveur de l’application reste local ; « distant » désigne le PRONOTE de l’établissement, pas un déploiement public de notre application. L’import des classes et les rapports depuis les données réelles restent à développer. La connexion automatique proposée séparément synchronise uniquement les données réellement exposées par le connecteur pour le type de compte choisi.

## Application Mac en un clic — pilote web autonome

Le paquet professeur est `dist-pilot/PRONOTE-Pilote-Mac-Apple-Silicon.zip`. Décompresser puis ouvrir **PRONOTE Pilote.app**. Python et Chromium sont embarqués : aucune commande, installation de Python, clé API, FFmpeg ou Client PRONOTE n’est nécessaire. Une connexion Internet et le compte PRONOTE/ENT habituel du professeur sont nécessaires. Cette construction vise les Mac Apple Silicon ; aucune version Windows ou Intel n’a été construite ou vérifiée ici.

Le professeur choisit le parcours navigateur ou la connexion automatique décrits en début de document. En mode navigateur, il renseigne l’adresse de son espace PRONOTE, se connecte dans la fenêtre dédiée puis confirme la vue utile ; le relevé est ensuite actualisé automatiquement si cette option reste cochée. « Terminer et effacer le relevé » ferme cette session. Fermer la fenêtre principale arrête aussi le serveur local et le navigateur. Les tableaux dessinés, pièces jointes et iframes restent des limites du relevé texte.

L’interface utilise un port local libre, sans conflit avec le MVP sur 8000. L’application autonome n’importe ni le moteur IA, ni les fixtures scolaires, ni les clés du projet. Elle ne lit pas les profils du navigateur habituel. Le nom, l’adresse et le parcours de connexion sont conservés dans `~/Library/Application Support/PronotePilot/pronote-pilot.json` (0600). Les préférences de synchronisation et le jeton mobile facultatif sont dans des fichiers privés distincts du même dossier. Le relevé et les cookies du navigateur restent en mémoire pendant la session ; ils ne sont pas exportés. Le contenu des pages n’est pas journalisé.

Le paquet possède une signature ad hoc pour son intégrité locale, mais **n’est pas notarisé Apple** : un Mac recevant le fichier téléchargé peut demander une autorisation à la première ouverture. Ne pas présenter ce paquet comme une distribution grand public sans friction. Une distribution avec reconnaissance automatique de l’éditeur nécessite un certificat Developer ID et une notarisation Apple. Aucun certificat Developer ID disponible n’a été trouvé pour cette construction.

Construction mainteneur uniquement (pas une étape pour le professeur) :

```sh
./mvp/desktop/build.sh
```

Les dépendances de construction sont isolées dans `.venv-pilot`. Les ressources du paquet sont explicitement sélectionnées ; le navigateur est copié avec sa structure signée. L’archive conserve les liens symboliques macOS. Le test `--smoke-test` du lanceur utilise une page synthétique interceptée localement et un dossier de données distinct, jamais le compte d’un professeur.

## Lancer H sur le vrai PRONOTE Mac depuis iTerm2

Les deux accès macOS doivent être accordés à l’application qui lance Python : ici iTerm2. Relancer iTerm2 après activation dans Confidentialité et sécurité → Accessibilité et Enregistrement de l’écran.

```sh
cd "/chemin/vers/H-Hack-nov26"
open -a "$PWD/mvp/data/PRONOTE Démo locale.app"
.venv/bin/python -m mvp.recordings start --desktop-prepared
```

Après la commande, sélectionner **PRONOTE Démo locale** dans le Dock ou avec Cmd-Tab. Le programme attend jusqu’à 90 secondes que cette application soit réellement au premier plan macOS ; le premier plan interne de Wine ne suffit pas. H ne démarre pas avant cette vérification. Une seule commande peut posséder le pilote desktop à la fois.

Le bridge H est explicitement routé vers un pilote gardé. Chaque capture est vérifiée avant/après, chaque action est bloquée hors PRONOTE, la saisie de texte et l’accès aux fichiers/shell sont désactivés pour cette démonstration. Passer dans une autre application arrête le pilote ; Ctrl+C dans iTerm2 termine la commande. Double Échap n’est disponible que si l’écoute clavier est déjà autorisée, sans demande de permission supplémentaire.

Le replay existant `32992b92-467d-4190-9f53-1b087d4fcea7` n’est pas un enregistrement PRONOTE : H s’est arrêté sans clic lorsque l’application attendue n’était pas au premier plan. Aucune image ou vidéo de cette tentative n’est publiée dans la galerie native. Les replays PRONOTE Web officiels restent distincts de cette session Mac.

## Application Windows autonome — pilote web

La construction Windows x64 est définie dans `.github/workflows/pronote-pilot-windows.yml`, avec un runner Windows et Python 3.12. Elle produit `dist-pilot-windows/PRONOTE-Pilote-Windows-x64.zip`. Le script PowerShell `mvp/desktop/build-windows.ps1` est réservé au mainteneur : le professeur ne l’exécute pas.

Parcours professeur : **Extraire tout** le ZIP, ouvrir le dossier extrait, puis double-cliquer sur **PRONOTE Pilote.exe**. Conserver les dossiers `_internal` et `browsers` à côté du `.exe`. Python et Chromium sont embarqués ; le professeur n’installe rien et n’ouvre aucun terminal. Le paquet cible Windows 11 x64. Le nom et l’adresse de l’établissement sont conservés dans `%LOCALAPPDATA%\PronotePilot`, sans identifiant ni mot de passe.

Le test automatique Windows extrait le ZIP dans un autre emplacement, retire Python du PATH, lance le `.exe`, ouvre l’interface et relève une page synthétique, puis vérifie l’effacement du relevé à l’arrêt. Ce contrôle ne remplace pas une connexion au véritable établissement du professeur. Le paquet n’est pas signé avec un certificat éditeur Windows : SmartScreen ou les règles d’un poste scolaire géré peuvent bloquer le lancement ; faire valider le paquet par l’équipe informatique si nécessaire.

## PRONOTE en arrière-plan et routes établies par Codex

Depuis `/?view=agent`, **Connecter PRONOTE en fond** ouvre la vraie démonstration officielle dans Chrome headless. H travaille par custom tools `list_pronote_routes()` et `read_pronote_view(route_id)`, sans environnement desktop : aucun clic global, focus macOS ou capture des autres applications. Le panneau conserve le journal réel, les extraits exacts et un MP4 qui rejoue les captures du navigateur dédié à raison de 3 secondes par vue. Ce replay est distinct de la capsule pédagogique du dossier Alex.

Le catalogue provient d’observations DOM faites avec Codex puis rejouées dans le navigateur dédié. Le harness Codex local structure ces preuves avec une vraie exécution `codex exec --json --sandbox read-only --output-schema`. Python refuse une route, un sélecteur ou une action absent des preuves, puis le connecteur vérifie à chaque lecture l’origine, la version PRONOTE, le nom du contrôle et le fil d’Ariane. Les numéros internes `data-genre` observés sont des attributs DOM de la SPA, pas des URL ni une API privée appelée directement.

Pour refaire le catalogue à partir d’un relevé local existant :

```sh
.venv/bin/python -m mvp.codex_routes establish --input mvp/data/pronote-routes/observations.json
```

Prérequis : le CLI `codex` installé et authentifié. Le job de découverte ne reçoit que les observations publiques du site officiel de démonstration. Les traces JSONL, le candidat et le catalogue validé restent dans `mvp/data/pronote-routes/`.

Le lancement de la connexion déclenche une première lecture. L’ouverture de la copie dans New PRONOTE déclenche également le relevé si aucune préparation n’a déjà démarré pour cette connexion ; les ouvertures suivantes sont dédupliquées. **Relire les vues** relance explicitement une nouvelle session. **Arrêter** coupe le connecteur, annule H et interdit la publication d’un relevé tardif. Keep/Dismiss et les rapports restent conservés dans `mvp/data/pronote-background/runs/`.

Périmètre vérifié : PRONOTE Web 2026.2.8, site de démonstration INDEX ÉDUCATION. Le client Mac n’expose pas de routes de fond vérifiées : `background_native_analysis.json` conserve les résultats de la sonde. Les copies et barèmes joints ne sont pas encore lus par ce connecteur. Les données du site officiel et celles du dossier fictif Alex ne sont jamais fusionnées. Chaque établissement devra disposer de ses propres contrôles observés et vérifiés ; le catalogue de démonstration n’est jamais appliqué à un compte réel.


## Téléchargements partageables du pilote

La [page publique de téléchargement](https://github.com/Fran-cois/pronote-pilot-downloads/releases/tag/pilote-2026-11-07) regroupe les deux versions et le mode d’emploi professeur. Les fichiers sont publiés dans un dépôt de distribution distinct ; le dépôt de développement reste privé. Aucun compte GitHub n’est nécessaire.

- [PRONOTE-Pilote-Mac-Apple-Silicon.zip](https://github.com/Fran-cois/pronote-pilot-downloads/releases/download/pilote-2026-11-07/PRONOTE-Pilote-Mac-Apple-Silicon.zip)
- [PRONOTE-Pilote-Windows-x64.zip](https://github.com/Fran-cois/pronote-pilot-downloads/releases/download/pilote-2026-11-07/PRONOTE-Pilote-Windows-x64.zip)
- [SHA256SUMS.txt](https://github.com/Fran-cois/pronote-pilot-downloads/releases/download/pilote-2026-11-07/SHA256SUMS.txt)

## Instance Azure et connexion Google

Instance hébergée : https://pronote-parallele-20261107.azurewebsites.net

Ressources dédiées dans `pronote-parallele-prod` (France Central) : App Service Linux B1 et registre `pronoteparallele20261107`. Le serveur HTTPS exige Google OIDC (`openid email profile`), vérifie l’identité et l’adresse e-mail, et conserve une session signée HttpOnly pendant huit heures. Le client OAuth du projet Google `new-pronote-hackathon-20261107` autorise `/auth/callback` sur ce domaine.

Les réglages sont dans Azure App Settings : `PUBLIC_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SESSION_SECRET`, `ALLOWED_EMAILS`, `PRONOTE_DATA_DIR`, ainsi que les clés des fournisseurs. `ALLOWED_EMAILS=*` accepte tout compte Google vérifié ; une liste d’adresses séparées par des virgules limite l’accès. Le démarrage hébergé refuse une configuration de sécurité incomplète. Aucune valeur secrète n’est embarquée dans l’image.

Cette instance est un **pilote partagé avec données fictives**, pas un espace scolaire individuel. Les rapports et modifications du dossier de démonstration sont communs aux utilisateurs. L’import audio, le calendrier personnel et les fonctions natives sont désactivés sur le serveur ; ils restent locaux. Les données générées sont conservées dans `/home/pronote-data` sur le stockage persistant App Service. Une seule instance et un seul worker sont utilisés, car l’état des tâches reste en mémoire du processus.

Redéployer après connexion Azure : `./deploy/azure.sh`. Ce script construit un contexte temporaire contenant uniquement les sources Python, le frontend et la fixture fictive. Il exclut les données locales, les archives et les credentials. L’image cloud installe uniquement les dépendances navigateur du SDK H et génère ses vocaux fictifs avec espeak-ng. Le contrôle de santé est `/healthz`.

Vérifications : `python -m pytest mvp/test_auth.py mvp/test_workspace.py mvp/test_google_calendar.py mvp/test_mvp.py -q`.

Validation publique du 7 novembre 2026 : `/healthz` répond 200, l’accueil sans session redirige vers `/login`, `/api/workspace` sans session répond 401 et `/privacy` répond 200. La connexion réelle Google, le retour OAuth et le chargement du dossier avec le profil connecté ont été vérifiés dans le navigateur. 22 tests locaux passent. Les chaînes H en mode connecté et les connecteurs PRONOTE ne sont pas validés sur Azure ; les fonctionnalités nécessitant le bureau restent réservées au compagnon local.


## Préparation depuis l’ouverture native d’une copie

Pour reprendre la démonstration installée sur ce Mac, lancer depuis la racine du dépôt et laisser le terminal ouvert :

```sh
./mvp/run.sh
```

Ouvrir **http://127.0.0.1:8000/native**, puis **Ouvrir PRONOTE en démo locale**. Le lanceur choisit la base `.not` enregistrée dans `data/native-attachments.json` lorsqu’elle existe dans la bouteille isolée ; ici **Base Exemple PRONOTE 2026_Archive.not**, qui contient les pièces importées. Une inscription absente ou invalide conserve la base d’exemple officielle initiale. Le connecteur doit afficher sa lecture de fond active avant l’ouverture de la copie.

Dans PRONOTE : **Ressources → Élèves → Dossiers de la vie scolaire** (icône dossier « VS »), retrouver **BERNARD Fanny · 3A · DEMO - Bilan mathematiques Pythagore · 07/11/26**, double-cliquer sur le libellé du dossier, puis ouvrir **Copy_Fanny_Pythagore.pdf**. Si ce document était déjà ouvert au démarrage du serveur, fermer sa fenêtre dans **Aperçu**, laisser l’observateur relever cette fermeture, puis rouvrir le lien dans PRONOTE. Le rapport apparaît dans `/native` ou `/?view=agent` ; le professeur peut poursuivre son travail pendant le traitement, sans prompt.

Le connecteur local `native/document_service.py` démarre avec le serveur local. Il lit les fenêtres de la bouteille PRONOTE isolée avec le programme Win32 en lecture seule, sans accès desktop H ni capture globale. Une nouvelle visionneuse ou un export PDF réellement ouvert dans Aperçu fournit le déclencheur. Pour Aperçu, `lsof` confirme le processus et le fichier exact sous `drive_c/users/<utilisateur>/Temp/{GUID}` ; SHA-256, MD5 et taille sont rapprochés du stockage natif FSFB. La création d’un fichier seule ne suffit pas. Le traitement vérifie également la base ouverte et le dossier, puis fige les octets avant H et le rendu MP4. La déduplication n’est acquittée qu’après acceptation par la file de traitement.

`GET /api/native/documents` expose l’état de l’observateur et le vrai dossier préparé. Le composant natif apparaît dans `/native` et `/?view=agent`, avec actions, textes et PDF figés, capsule et Keep/Dismiss. Les liens de notification natifs ouvrent `/native?job=<id>` et conservent le nom du dossier concerné.

Les sources s’enregistrent dans `data/native-attachments.json` **après vérification de l’import dans le vrai client** : `attachment_roots`, `database_path`, `dossier_id`, `native_context_id`, `identity`, et `sources` (id, rôle, chemin, nom affiché, SHA256, provenance et preuve d’import). Le registre n’est pas créé par le générateur de fichiers. Un premier relevé établit uniquement la référence ; il faut fermer puis rouvrir la copie pour produire un nouvel événement. Un barème externe non importé est refusé.

Préparation des pièces fictives pour la base d’exemple :

```sh
.venv/bin/python -m mvp.native.demo_documents
.venv/bin/python -m mvp.native.demo_documents --audio
```

Les trois PDF de Fanny portent une mention de données fictives. L’import a été effectué depuis `C:\H-Demo\Pieces` ; choisir un fichier hors du disque de la bouteille a échoué dans ce client. La base d’exemple a été sauvegardée. Le registre actif `data/native-attachments.json` pointe maintenant sur les trois PDF réellement décodés par PRONOTE. Le manifeste du générateur reste distinct du registre vérifié. Le vocal de37secondes est une voix Thomas synthétique ; son origine reste `attached_test_dossier`, séparée de la provenance des pièces natives. Sans vocal, H prépare une explication de la copie et du barème sans appeler Gladia ni inventer une question parentale.

Les liens du barème et de la consigne sont dans la même fenêtre native. Le premier clic sur la copie a émis l’événement réel `native_export_file_open` et lancé H sans prompt. `data/native-demo-documents/native-scenario-verification.json` conserve cette preuve.

Le dossier vérifié `0a1b88b9beac` conserve les véritables résultats H, Gladia et Linkup. Une première capsule a été produite automatiquement, puis retirée pour des erreurs de français. La capsule finale de 77 secondes utilise une révision éditoriale Codex du brouillon H, signalée dans le rapport : dix corrections sont consignées dans `data/0a1b88b9beac/revisions/002/editorial-review.json`, sans modifier la question, les citations ou les sources. Les reprises H distantes bloquées ne sont pas présentées comme terminées. La validation du professeur reste requise avant tout partage.

Les trois exports réellement observés ont été archivés dans `data/native-export-cache/<contexte>/`, avec leur chemin Temp d’origine et leurs preuves FSFB. Après cette installation, le professeur ouvre uniquement la copie : les pièces complémentaires restent lisibles même si PRONOTE nettoie Temp. Une copie dans le cache ne déclenche rien ; la copie active doit toujours être un export natif effectivement ouvert dans Aperçu. Une pièce modifiée ou une archive sans preuve est refusée.

La déduplication persiste après fermeture du serveur : les mêmes pièces et le même vocal conservent leur préparation. Un autre vocal enregistré dans le dossier vérifié crée une nouvelle identité de préparation lors d’une nouvelle ouverture réelle. Une préparation échouée reste consultable : **Reprendre la préparation** relance H depuis la même ouverture et les mêmes fichiers, sans nouvel appel Gladia ou Linkup. Ni un redémarrage ni un clic identique ne soumettent automatiquement une autre session H. Une pièce ou un vocal figé modifié empêche la reprise.

Deux vocaux synthétiques sont disponibles dans `data/native-demo-documents` : `Question_parents_Fanny.wav` (37 s, question sur les points) et `Question_progress_Fanny.wav` (47 s, question sur la progression). Le registre actif prépare actuellement le second pour la prochaine ouverture réelle. Le premier a réellement déclenché Gladia, Linkup et H ; le second n’est pas présenté comme testé tant qu’une nouvelle ouverture native et ses appels API ne sont pas constatés.

Le schéma natif exige une visionneuse Win32 identifiée ou un export réellement ouvert dans Aperçu, ainsi qu’une base et un dossier cohérents. H sélectionne la question dans les utterances Gladia par identifiant ; le programme restitue le texte exact et ses bornes audio. Les corrections H réutilisent uniquement les sources et résultats API figés. La narration, les sous-titres et le MP4 sont générés en fond ; aucune diffusion aux parents n’est automatique. Les tests de fenêtres utilisent des doubles ; la preuve d’import et le déclencheur du dossier Fanny proviennent de la session réelle.

## Organiser une sortie scolaire

Huit destinations sont proposées : musée d’Orsay, musée du Louvre, Cité des sciences et de l’industrie, Grande Galerie de l’Évolution, musée du quai Branly – Jacques Chirac, musée Rodin, musée des Arts et Métiers et château de Versailles. Chaque lieu dispose de son adresse, de son site officiel et de coordonnées pour l’estimation routière. Les horaires, tarifs et conditions sont recherchés pour la visite choisie ; aucun tarif n’est fixé par le catalogue.

Depuis **Sorties scolaires** (ou la carte de l’accueil), choisir la classe fictive de 4e B, une destination et une date, puis **Préparer la sortie**. Le formulaire regroupe les informations de visite et l’objectif pédagogique ; la durée, les accompagnateurs et le budget restent dans les options repliables. L’objectif pédagogique reste modifiable pendant la préparation et alimente le dossier et le courrier aux familles.

Holo4 (`holo4-27b`, modèle explicitement sélectionné) démarre avant toute collecte et orchestre lui-même les appels : `search_museum_visit`, `prepare_transport_and_calendar` et `read_class_and_template`. Chaque fonction démarre seulement le travail demandé et retourne immédiatement un ticket ; les recherches Linkup, le trajet OSRM et la lecture de classe peuvent donc réellement se chevaucher, même avec un SDK qui distribue les callbacks successivement. Aucun appel manquant n’est lancé automatiquement. Holo4 utilise une workstation H cloud éphémère pendant ces travaux, puis demander `wait_for_outing_results`, relire les résultats avec `read_outing_evidence` et appeler `fill_administrative_dossier`. Les résultats alimentent un budget calculé en décimal. Il consulte la page publique officielle du musée, puis appelle les fonctions dans la même session. Le préremplissage attribué à Holo4 exige une capture réellement jointe d’une page du domaine officiel et une action `web` effectivement terminée dans la workstation, conservées dans la trace du fournisseur, ainsi que les appels de fonctions réussis. Une simple configuration de navigateur ne suffit pas. La workstation est séparée du poste du professeur. Sa configuration impose `kind: "workstation"`, `host: "cloud"` et `storage: {"ephemeral": true}` : aucune réutilisation de session, de volume ou de profil existant. La session est à usage unique (`idle_timeout_s=None`) ; les fichiers de la machine ne survivent pas à la session. Les résultats et le journal nécessaires au dossier sont conservés par New PRONOTE, hors de cette machine. Ce mode workstation est en préversion ouverte pendant le hackathon. Aucune clé ne passe au navigateur.

Le départ est un point fictif Place de la République à Paris. OSRM fournit une estimation automobile sans trafic ; l’accès autocar, le devis, la réservation et les autorisations restent à confirmer. Le calendrier vérifié est celui du dossier de démonstration, pas l’emploi du temps complet ni Google Calendar. Un tarif ou un effectif inconnu ne devient pas zéro ; les échecs restent visibles et le budget partiel distingue les montants connus.

**Enregistrer le dossier** conserve un brouillon dans l’espace administratif fictif de New PRONOTE (`data/outings/administrative/`). **Télécharger** exporte le dossier et le courrier en texte. Modifier l’objectif invalide la version enregistrée. Aucune saisie dans le vrai PRONOTE, réservation ou diffusion aux familles n’est effectuée. Les données du pilote hébergé restent partagées entre ses utilisateurs.

Un état compact apparaît après le lancement, sans interrompre la rédaction. **Voir le détail** ouvre le suivi à la demande. Les résultats s’affichent dès qu’ils sont disponibles ; aucun bloc vide n’est montré avant le lancement. Cette vue réunit les fonctions, leur état et les résultats sur un seul écran pour la démonstration vidéo ; l’objectif pédagogique reste modifiable sans fermer ce suivi. Le panneau « Holo4 aux commandes » distingue les appels de lancement reçus des exécutions encore actives. Il affiche chaque fonction, les heures de demande/début/fin, la durée écoulée, les réponses et les erreurs. Le nombre d’exécutions simultanées et leur maximum sont mesurés à partir du travail réel. La file d’attente du fournisseur est distinguée du travail du modèle. Un outil jamais appelé est indiqué comme tel ; les appels répétés réutilisent le même ticket. Un arrêt ou redémarrage termine explicitement les états actifs et empêche la publication tardive des résultats.

Les flux animés suivent les états réels : le projet se divise en trois branches, puis converge vers le dossier. Attente calme, activité animée, réussite verte et échec ambre ; les animations respectent la préférence de réduction des mouvements.

Vérification sans appels aux fournisseurs : `.venv/bin/python -m pytest mvp/test_outings.py mvp/test_outings_routes.py mvp/test_outings_holo.py mvp/test_outings_holo_integration.py mvp/test_outings_orchestration.py mvp/test_outings_provider_state.py mvp/test_tool_calls.py -q`.

Références : [modèle et configuration des agents H](https://hub.hcompany.ai/agents-api/agents/overview), [workstation et mode éphémère](https://hub.hcompany.ai/agents-api/workstation).

### Démonstration familles et logistique

Sur une sortie déjà préparée, **Jouer la suite de démonstration** lance une session Holo4 distincte et affiche la phase **Familles & logistique** dans la même modale. Le bandeau rappelle en permanence qu’aucun message n’est envoyé et qu’aucune réservation réelle n’est effectuée.

**Démo complète** relance d’abord la préparation réelle puis enchaîne une seule fois sur la simulation, dans la même modale. Cette suite ne démarre qu’après ce clic explicite et la réception d’un dossier et d’une liste de classe. Le mode **Présentation auto** met en avant les nouveaux résultats reçus et se suspend dès qu’un résultat est choisi manuellement. Les mails, confirmations, relances, familles et matériel s’animent à partir des changements enregistrés, sans inventer d’avancement. Le résumé du matériel reste visible à côté des messages. Les logos Gmail, Google Docs et Google Agenda illustrent des interfaces simulées ; aucun compte ni connecteur de ces services n’est sollicité.

Holo4 lit le contexte, puis appelle sept fonctions `*_demo` : messages aux familles, réponses fictives avec confirmations, relances ciblées, autorisation photo, contrôle du matériel, réservation dans le planning fictif et assemblage administratif. L’agent de cette phase ne dispose d’aucun navigateur, shell, connecteur ou transport mail : ses fonctions modifient uniquement le scénario local. La préparation initiale conserve sa workstation éphémère.

`H_OUTING_OPERATIONS_PROVIDER=models_api` utilise le function calling officiel de Holo4 directement via la [Models API](https://hub.hcompany.ai/models-api/build-an-agent/function-calling), sans consommer une session Agents supplémentaire pour cette phase. Holo4 choisit toujours chaque fonction et ses arguments ; les dépendances sont vérifiées par les reçus des appels précédents. Les identifiants des réponses du modèle sont conservés séparément des sessions Agents, et la modale affiche le chemin utilisé. Un aperçu isolé peut être lancé sur un autre port avec `H_LOCAL_PREVIEW_PORT=8001`, en conservant les vérifications d’origine.

Pour 28 élèves, le scénario produit 20 confirmations, 2 refus et 6 familles sans réponse ; seules ces 6 dernières reçoivent une relance simulée. Le choix photo est indépendant : 18 accords fictifs, 4 refus respectés, 6 réponses attendues. Aucun de ces choix ne vaut consentement ni signature réelle. Le stock fictif propose 6 tablettes sur 8 demandées et compense le manque avec des kits papier ; les quantités allouées ne dépassent jamais les disponibilités. Le dossier administratif reste un ensemble de brouillons, avec les accords et signatures à obtenir.

L’onglet **Collecte Stripe** montre un aperçu de lien individuel par élève, repris dans chaque invitation, le montant à collecter et le règlement attendu. Le budget doit être complet et positif ; un montant inconnu ou nul ne produit aucun lien. Les refus sont exclus du total et des rappels de paiement, lesquels ciblent uniquement les participations confirmées non réglées. La confirmation de participation ne vaut jamais paiement. Cette extension reste une simulation locale : aucune API Stripe appelée, aucun lien utilisable créé, aucun message envoyé et aucun encaissement. Les aperçus utilisent `checkout.example.invalid`. Une connexion Stripe réelle avec suivi des paiements par webhooks signés reste à implémenter pour passer à une collecte effective.

Les destinataires sont exclusivement des adresses `example.invalid`. Chaque message porte `actual_sent=false` ; chaque réservation porte `actual_reserved=false`. L’API refuse les paramètres d’envoi réel ou de destinataire. Les appels H et leurs résultats sont enregistrés avec leur session propre, sans remplacer les preuves de préparation. Modifier l’objectif rend la simulation obsolète ; la rejouer archive l’ancien scénario puis repart de la nouvelle version.

Vérification locale sans appel fournisseur : `.venv/bin/python -m pytest mvp/test_outings_operations.py mvp/test_outings_operations_routes.py mvp/test_outings_operations_runner.py -q`.
