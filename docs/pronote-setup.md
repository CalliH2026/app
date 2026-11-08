# PRONOTE 2026 trial environment: setup checklist

Goal: a PRONOTE 2026 trial base on Windows with one class of 10 fictitious students, one teacher
who can log in, one subject and service, one grading period open for comments, and a Client in
teacher mode showing "Bulletins > Saisie des appréciations > Saisie des appréciations des
professeurs par matière" (the display used by `agent/targets/pronote.md`, see SPEC.md section 4).
Target time: under one hour, downloads included.

Sources: only Index Education pages (docs.index-education.com, index-education.com,
forum.index-education.com), read on 2026-11-07 for build 2026.2.8. Link labels such as
[fiche 456-4121] point to the support page with that number; the URLs are listed at the end.

Legend, applied to every step:

- **DOC**: the cited page states this step and its menu names.
- **FLAG**: the documentation is unclear, only describes EDT or the hosted console, is a video
  without text, or does not name the menu. Do the step, then record what you saw in
  `docs/pronote-questions.md`.

Nothing in this file has been tried on a real PRONOTE install yet.

## 0. Choose a set-up (2 min)

| | Path A: monoposte | Path B: server + Mac client |
|---|---|---|
| Downloads ([download page][dl]) | "Utilisateur monoposte 2026 - 2.8" | "SERVEUR 2026 - 2.8", "Administration du SERVEUR 2026", "CLIENT PRONOTE 2026 - 2.8 MAC OS" |
| Machines | one Windows PC/VM | Windows VM (server) + Mac (client) |
| Matches SPEC.md section 4 (Mac client to Windows server) | no | yes |

- [ ] **DOC** Requirements: Windows 10 minimum, Windows 11 advised, 4 GB RAM, 100 GB free disk;
  the applications are 64-bit; every application is free to evaluate for 8 weeks
  ([fiche 456-1886][f1886], [download page][dl]).
- [ ] **FLAG** No public page describes the PRONOTE "Utilisateur monoposte" application itself
  (installation, base creation, users); the monoposte pages found are about EDT. Path A is faster
  but may not offer the teacher mode at all (question 18 in `docs/pronote-questions.md`). If the
  goal is the Calligraphe writer, prefer Path B.

## 1. Download the installers (10 min, mostly waiting)

- [ ] **DOC** The official download page lists, for build 2026.2.8: "CLIENT PRONOTE 2026 - 2.8",
  "CLIENT PRONOTE 2026 - 2.8 MAC OS", "SERVEUR 2026 - 2.8", "Utilisateur monoposte 2026 - 2.8" and
  "Administration du SERVEUR 2026" ([download page][dl]).
- [ ] On the Windows machine, in PowerShell, from the repository folder:

  ```powershell
  # Path A
  powershell -ExecutionPolicy Bypass -File .\scripts\pronote\setup-windows.ps1
  # Path B (add -IncludeMacClient to also fetch the Mac .pkg, then copy it to the Mac)
  powershell -ExecutionPolicy Bypass -File .\scripts\pronote\setup-windows.ps1 -Mode Server
  ```

  The script reads the links from the [download page][dl], downloads them, checks each size
  against the server's Content-Length and against the sizes recorded on 2026-11-07, then opens each
  installer. Without the script: click the same entries on the [download page][dl].
- [ ] **DOC** Silent install is documented only for the Client, with a recorded InstallShield
  response file (`-r`, then `-s -f1<file.iss> -f2<log>`, success when the log says `ResultCode=0`)
  ([fiche 456-6924][f6924]). Nothing is documented for the monoposte, Server or Administration
  installers, so the script never runs them silently.
- [ ] **FLAG** The installer wizards themselves are not described on any page found ("laissez-vous
  guider par le programme d'installation" appears only in the EDT section of the
  [Guide pratique, PDF p. 12][guide12]). Accept the defaults.

## 2. Install and start the server (Path B, 10 min)

- [ ] **DOC** In non-hosted mode, a network set-up uses the Client, the Server and PRONOTE.net;
  the Server makes the base available to the Clients ([fiche 456-4121][f4121]).
  PRONOTE.net (web spaces) is not needed for this test.
- [ ] **DOC** Install "SERVEUR 2026" on the Windows VM. In the Server, pane "Paramètres de
  publication", the window "Création d'un superadministrateur" asks for an identity, a login and a
  password: this becomes the first administrator account ([fiche 456-4121][f4121]). Choose the
  password yourself; never write it in this repository.
- [ ] **DOC** In "Paramètres de publication", note the IP address and the TCP port
  ([fiche 456-4121][f4121], [fiche 456-2077][f2077]).
- [ ] **FLAG** The default non-hosted port is not stated; 49300 appears only in the hosted example
  ([fiche 456-1822][f1822]). Use the value displayed. Whether the Windows firewall needs a rule for
  that port is not documented; if the Mac cannot connect, allow the port inbound and note it.
- [ ] **DOC** (optional) "Administration du SERVEUR 2026" drives the Server from another machine:
  in the Server, pane "Administration à distance", tick "Autoriser l'administration à distance",
  check the port and enter the allowed address(es); in the Administration application, pane
  "Liste des serveurs", enter a name plus the IP and port from "Paramètres de publication"
  ([fiche 456-4123][f4123]). It is not needed when you work directly on the VM.

## 3. Create a new empty base, non-hosted (5 min)

- [ ] **FLAG** The page titled "Créer une nouvelle base vide" is a 46-second video with no text
  ([fiche 1231-2545][f2545]); no written PRONOTE procedure for a non-hosted Server or for the
  monoposte application was found. Closest written procedures, neither of which is this case:
  - EDT Server, "Mettre en service une nouvelle base vide": unlock the Server with the button at
    the top right (login and password), then "Pour créer une nouvelle base vide, cliquez sur le
    bouton situé en haut à droite de l'écran" ([Guide pratique, PDF p. 21][guide21], tagged EDT).
  - PRONOTE hosted console: pane "Serveur PRONOTE", button "Créer une base", "Valider" in the
    "Paramétrage de la grille horaire" window, name the base, then "Mettre en service" so the
    Client can open it ([fiche 1678-1866][f1866]).

  Expected on the PRONOTE Server (unconfirmed): an icon at the top right creates the base, a
  timetable-grid window appears (keep the defaults), you name the base, then "Mettre en service".
  Path A: look for "Créer une nouvelle base vide" on the monoposte start screen (unconfirmed).
- [ ] **DOC** Changes are saved automatically, except in "Usage exclusif" mode, where a validation
  is needed; quit with the window cross or "Fichier > Quitter" ([fiche 324-2117][f2117]).

## 4. Connect a Client in administrative mode (Path B, 3 min)

- [ ] **DOC** Install the Mac Client (or the Windows "CLIENT PRONOTE 2026"). The Mac package is
  the Windows Client bundled with Wine; it needs macOS 10.13 or later and permission to run
  applications from any source ([fiche 456-4122][f4122]).
- [ ] **DOC** On the Client home page, click "Ajouter les coordonnées d'un nouveau serveur", enter
  the "Adresse IP" and "Port TCP" from the Server's "Paramètres de publication" and a
  "Désignation du serveur", then "Valider" ([fiche 456-1822][f1822], [fiche 456-4121][f4121]).
- [ ] **DOC** Click the server entry, choose "Mode administratif", type the superadministrator
  login and password, click "Se connecter" ([fiche 456-1822][f1822]).
- [ ] **FLAG** Path A: no page says how to open the monoposte application as administrator.

## 5. School year (3 min)

- [ ] **DOC** "Paramètres > Établissement > Calendrier": the first and last day of the year must
  be defined; "Calcul des vacances et fériés" can fill holidays from an académie
  ([fiche 4031-4219][f4219]). Use 2026-09-01 to 2027-07-04 or similar so today is inside the year.
- [ ] **FLAG** Whether the year dates are asked when the base is created (step 3) or only here is
  not documented.

## 6. Grading period (3 min)

- [ ] **DOC** "Paramètres > Établissement > Périodes de notation": in "Type de notation par défaut
  pour les classes" choose "trimestrielle" (or semestrielle/continue), and adjust dates by
  double-clicking the "Du ..." and "Au ..." columns ([Guide pratique, PDF p. 171][guide171]).
  Custom periods are also possible from the same menu ([fiche 4031-1475][f1475]).
- [ ] Make sure today's date falls inside the first period (for a test in November: Trimestre 1
  from 2026-09-01 to 2026-11-30). **FLAG** This is our choice, not an Index Education instruction.

## 7. Class `3A` (3 min)

- [ ] **FLAG** No PRONOTE page found states how to create a class by hand. The guide describes, for
  EDT, clicking the first line of a resource list ("Créer une classe" etc.) and pressing Enter
  after each mandatory field ([Guide pratique, PDF p. 28][guide28]). Try "Ressources > Classes >
  Liste", first line, type `3A`, Enter.
- [ ] **DOC** Give the class its grading periods: "Ressources > Classes > Liste", select `3A`,
  right-click, "Modifier la sélection > Notation", pick the type, "Valider"
  ([Guide pratique, PDF p. 171][guide171]).

## 8. Ten students (5 min)

- [ ] **DOC** Import by copy-paste from a spreadsheet, or through "Imports/Exports > TXT/CSV/XML >
  Importer un fichier texte"; in the import window check the "type de données à importer", choose
  the separator "Tabulation", map each column ("Champ ignoré" to skip), tick "Ne pas importer les x
  premières lignes" for the header, click "Importer" ([fiche 323-1868][f1868]). It requires the
  "Mode administratif" and the "Administration" group ([fiche 4032-4187][f4187]).
- [ ] Use `scripts/pronote/import-files/eleves.txt` and follow its
  [README](../scripts/pronote/import-files/README.md). **FLAG** No fixed column layout, field
  names, mandatory fields or file encoding are documented publicly; the student list display name
  ("Ressources > Élèves > Liste") and the student data-type label are unconfirmed.
- [ ] Fallback: type the 10 rows by hand (table in the README; same **FLAG** as step 7).

## 9. One teacher with a login (5 min)

- [ ] **DOC** Add the teacher by hand in "Ressources > Professeurs > Liste"
  ([fiche 1523-1779][f1779]): `DURAND` / `Sophie` (`scripts/pronote/import-files/professeurs.txt`
  can also be pasted with the import window of step 8).
- [ ] **DOC** Check the teacher's authorisation profile in the "Autorisation" column of
  "Ressources > Professeurs > Liste" ([fiche 1523-1783][f1783]).
- [ ] **DOC** In "Ressources > Professeurs > Profils d'autorisations", tick "Activer le Mode
  Enseignant" (one switch for the whole school), then review each profile
  ([fiche 1523-5313][f5313]); the guide names the box "Activer le Mode enseignant (connexion au
  Client PRONOTE)" ([Guide pratique, PDF p. 146][guide146]).
- [ ] **FLAG** The per-profile box quoted on [fiche 1523-5313][f5313] is "Avec le Client PRONOTE
  (mode Vie scolaire)", which reads like the staff setting; the exact box for teachers is unclear.
- [ ] **FLAG** Where the teacher's login and password are set is not documented for a manual
  creation. Documented nearby: logins and passwords are sent from "Ressources > Professeurs >
  Liste" with the "Connexion" letter template ([Guide pratique, PDF p. 207][guide207]); a
  "Mot de passe" column exists and "Modifier la sélection > Mot de passe et code PIN > Forcer le
  changement de mot de passe" forces a change ([Guide pratique, PDF p. 139][guide139]; that page
  gives the EDT path "Emploi du temps > Professeurs > Liste"). Try right-click on the teacher in
  "Ressources > Professeurs > Liste" and look for "Mot de passe" / "Identifiant". Do not store the
  password in the repository.

## 10. One subject and one service (4 min)

- [ ] **FLAG** No PRONOTE page found states how to create a subject by hand. Try
  "Ressources > Matières > Liste", first line, type `FRANCAIS`, Enter (EDT pattern,
  [Guide pratique, PDF p. 28][guide28]).
- [ ] **DOC** "Ressources > Classes > Services par classe", select `3A`, click "Créer un service",
  double-click the subject, tick the teacher, "Valider" ([fiche 363-6784][f6784]).
- [ ] **DOC** In the same display, the "Mode" column switches "Avec notes" / "Sans notes"; both
  modes let teachers enter comments; an active service shows a green bullet
  ([Guide pratique, PDF p. 172][guide172]).

## 11. Open the comment-entry period (2 min)

- [ ] **DOC** After the closure date, comments can no longer be created, changed or deleted. As an
  "Administration" user, open "Ressources > Classes > Clôture des périodes", use the button above
  the "App. prof." column and set a date after today or "Aucune clôture"
  ([fiche 4087-4300][f4300]).
- [ ] **DOC** Comments are limited to 255 characters by default; the administrator can change the
  maximum in "Paramètres > Évaluation > Bilans périodiques" ([fiche 1096-4346][f4346],
  [fiche 1680-4304][f4304]). Leave the default for the first test.
- [ ] **DOC** (optional) The "assistant de saisie" is controlled by "Ressources > Professeurs >
  Profils d'autorisations > Appréciations > Utiliser l'assistant de saisie"
  ([fiche 1680-4303][f4303]). **FLAG** Whether it changes the double-click behaviour is open
  (question 5).

## 12. Connect the Client in teacher mode (3 min)

- [ ] **DOC** Teachers enter comments from the Client in "Mode Enseignant" or from the Espace
  Professeurs ([fiche 1680-4303][f4303]).
- [ ] **DOC** Path B: on the Mac Client home page, use the server entry from step 4 (or "Ajouter
  les coordonnées d'un nouveau serveur" with the IP address and TCP port from "Paramètres de
  publication"), choose "Mode enseignant", type the teacher's login and password, click
  "Se connecter" ([fiche 456-1822][f1822], [fiche 456-4121][f4121], [fiche 456-2077][f2077]).
- [ ] **FLAG** Path A: no page says whether or how a teacher logs in to the monoposte application.

## 13. Check the comment display (3 min)

- [ ] **DOC** In teacher mode, open "Bulletins > Saisie des appréciations > Saisie des
  appréciations des professeurs par matière", select the service in the left list and the period
  in the drop-down, double-click a cell in the "Appréciations" column and write
  ([fiche 1096-4341][f4341]).
- [ ] **DOC** Administrator cross-check: "Bulletins > Vérification > Vérification des bulletins",
  column "App. professeurs" shows a red cross where no comment exists ([fiche 1680-6795][f6795]).
- [ ] For the injection fixture (SPEC.md section 6), type the pre-filled text of the
  `fixture=injection` row of `data/truth.csv` in the comment of that student (GARNIER Maximilien)
  and leave the others empty. This is our test setting,
  not an Index Education instruction.
- [ ] Answer `docs/pronote-questions.md` while you are on this display.

## 14. After the trial

- [ ] **DOC** The trial lasts 8 weeks; the data is kept once a licence is bought
  ([download page][dl]); in non-hosted mode the licence is registered with "Fichier > Utilitaires >
  Enregistrer automatiquement votre licence" ([fiche 456-4121][f4121]).

## Summary of flags

| Step | What is not confirmed |
|---|---|
| 0, 3, 4, 12 | Everything specific to "Utilisateur monoposte 2026", including teacher mode |
| 1 | Installer wizard screens; no silent flag for monoposte/Server/Administration |
| 2 | Default non-hosted port; firewall rule |
| 3 | Exact "Créer une nouvelle base vide" sequence (video only) |
| 5 | Whether the year is set at base creation |
| 7, 10 | Manual creation of a class and of a subject (EDT pattern only) |
| 8 | Student list display, data-type label, field names, mandatory fields, encoding |
| 9 | Per-profile teacher-mode box; where the teacher login and password are set |
| 11 | Effect of the "assistant de saisie" on the cell |

## Sources

- dl: <https://www.index-education.com/fr/telecharger-pronote.php>
- f1886: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-1886-quelle-est-la-configuration-minimale--recommandee-pour-utiliser-correctement-le-client-pronote-avec-windows.php>
- f6924: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-6924-comment-installer-rapidement-des-clients-sur-tous-les-postes-d-un-reseau-installation-silencieuce.php>
- f4121: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-4121-nous-n-avons-pas-choisi-pronote-en-mode-heberge-comment-installer-pronote-sur-windows.php>
- f2077: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-2077-ou-trouver-l-adresse-ip-du-serveur-pronote.php>
- f1822: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-1822-installer-le-client.php>
- f4123: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-4123-nous-n-avons-pas-choisi-pronote-en-mode-heberge-a-quoi-servent-les-autres-applicatifs-relais-administration-a-distance--.php>
- f2545: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1231-2545-creer-une-nouvelle-base-vide.php>
- f1866: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1678-1866-la-creation-automatique-de-la-nouvelle-base-pronote-a-lieu-fin-aout-comment-faire-si-je-souhaite-commencer-a-travailler-dessus-avant.php>
- f2117: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-324-2117-que-dois-je-faire-pour-enregistrer-les-modifications-dans-la-base.php>
- f4122: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-4122-nous-n-utilisons-pas-le-systeme-d-exploitation-windows-comment-installer-pronote-sur-macos-ou-linux.php>
- f4219: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-4031-4219-saisir-le-calendrier-vacances-jours-feries-et-les-semaines-q1-q2.php>
- f1475: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-4031-1475-definir-des-periodes-personnalisees.php>
- f1868: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-323-1868-comment-completer-la-base-avec-les-donnees-qui-ne-proviennent-ni-de-pronote-ni-d-edt.php>
- f4187: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-4032-4187-comment-importer-les-donnees-d-un-tableur-dans-une-liste.php>
- f1779: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1523-1779-mettre-a-jour-les-donnees-des-enseignants.php>
- f1783: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1523-1783-ou-puis-je-changer-le-profil-d-autorisations-d-un-professeur.php>
- f5313: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1523-5313-verifier-l-activation-du-mode-enseignant-en-debut-d-annee.php>
- f6784: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-363-6784-modifier-les-services-d-enseignement.php>
- f4300: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-4087-4300-je-ne-peux-plus-modifier-un-bulletin-car-la-date-de-cloture-est-passee-comment-faire.php>
- f4346: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1096-4346-peut-on-augmenter-la-longueur-maximale-des-appreciations.php>
- f4304: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1680-4304-comment-augmenter-la-taille-maximale-des-appreciations.php>
- f4303: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1680-4303-comment-s-effectue-la-saisie-des-appreciations-cote-professeurs.php>
- f4341: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1096-4341-saisir-les-appreciations.php>
- f6795: <https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1680-6795-superviser-le-remplissage-des-bulletins.php>
- guide12: <https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=12>
- guide21: <https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=21>
- guide28: <https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=28>
- guide139: <https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=139>
- guide146: <https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=146>
- guide171: <https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=171>
- guide172: <https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=172>
- guide207: <https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=207>

[dl]: https://www.index-education.com/fr/telecharger-pronote.php
[f1886]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-1886-quelle-est-la-configuration-minimale--recommandee-pour-utiliser-correctement-le-client-pronote-avec-windows.php
[f6924]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-6924-comment-installer-rapidement-des-clients-sur-tous-les-postes-d-un-reseau-installation-silencieuce.php
[f4121]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-4121-nous-n-avons-pas-choisi-pronote-en-mode-heberge-comment-installer-pronote-sur-windows.php
[f2077]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-2077-ou-trouver-l-adresse-ip-du-serveur-pronote.php
[f1822]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-1822-installer-le-client.php
[f4123]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-4123-nous-n-avons-pas-choisi-pronote-en-mode-heberge-a-quoi-servent-les-autres-applicatifs-relais-administration-a-distance--.php
[f2545]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1231-2545-creer-une-nouvelle-base-vide.php
[f1866]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1678-1866-la-creation-automatique-de-la-nouvelle-base-pronote-a-lieu-fin-aout-comment-faire-si-je-souhaite-commencer-a-travailler-dessus-avant.php
[f2117]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-324-2117-que-dois-je-faire-pour-enregistrer-les-modifications-dans-la-base.php
[f4122]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-4122-nous-n-utilisons-pas-le-systeme-d-exploitation-windows-comment-installer-pronote-sur-macos-ou-linux.php
[f4219]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-4031-4219-saisir-le-calendrier-vacances-jours-feries-et-les-semaines-q1-q2.php
[f1475]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-4031-1475-definir-des-periodes-personnalisees.php
[f1868]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-323-1868-comment-completer-la-base-avec-les-donnees-qui-ne-proviennent-ni-de-pronote-ni-d-edt.php
[f4187]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-4032-4187-comment-importer-les-donnees-d-un-tableur-dans-une-liste.php
[f1779]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1523-1779-mettre-a-jour-les-donnees-des-enseignants.php
[f1783]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1523-1783-ou-puis-je-changer-le-profil-d-autorisations-d-un-professeur.php
[f5313]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1523-5313-verifier-l-activation-du-mode-enseignant-en-debut-d-annee.php
[f6784]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-363-6784-modifier-les-services-d-enseignement.php
[f4300]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-4087-4300-je-ne-peux-plus-modifier-un-bulletin-car-la-date-de-cloture-est-passee-comment-faire.php
[f4346]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1096-4346-peut-on-augmenter-la-longueur-maximale-des-appreciations.php
[f4304]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1680-4304-comment-augmenter-la-taille-maximale-des-appreciations.php
[f4303]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1680-4303-comment-s-effectue-la-saisie-des-appreciations-cote-professeurs.php
[f4341]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1096-4341-saisir-les-appreciations.php
[f6795]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1680-6795-superviser-le-remplissage-des-bulletins.php
[guide12]: https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=12
[guide21]: https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=21
[guide28]: https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=28
[guide139]: https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=139
[guide146]: https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=146
[guide171]: https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=171
[guide172]: https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=172
[guide207]: https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=207
