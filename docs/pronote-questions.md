# PRONOTE: questions only the real client can answer

The official documentation describes the comment-entry display but not the low-level behaviour the
Calligraphe writer depends on (SPEC.md section 4, `agent/targets/pronote.md`). Each question below
says what the documentation does say, with its source, and what remains open. Answer them on the
trial install (see `docs/pronote-setup.md`), in the teacher-mode Client, on the display
"Bulletins > Saisie des appréciations > Saisie des appréciations des professeurs par matière".
Write the answer, the date, the PRONOTE build (e.g. 2026.2.8) and the platform (Windows Client, or
macOS Client through Wine) next to each question.

Documented baseline, for reference: the teacher selects the service in the left list and the period
in the drop-down, then double-clicks in the "Appréciations" column to write
([fiche 1096-4341][f4341]). Data is saved automatically, except in "Usage exclusif" mode
([fiche 324-2117][f2117]).

## A. Typing and validating a comment

1. **Does the cell accept paste (Ctrl+V on Windows, Cmd+V or Ctrl+V on the macOS/Wine Client)?**
   The documentation only describes double-clicking and writing ([fiche 1096-4341][f4341]). It does
   not mention the clipboard in the cell.
2. **How is a comment validated: Enter, Tab, clicking another row, or clicking elsewhere?** Not
   documented for this display. The only Enter rule found concerns mandatory fields when creating
   resources in a list, and that passage is tagged EDT ([Guide pratique, PDF p. 28][guide28]).
3. **Does Enter insert a line break inside the comment or validate it? Is there a key for a line
   break (Shift+Enter, Ctrl+Enter)?** Not documented.
4. **Does Escape cancel the edit and restore the previous text? Does Ctrl+Z work inside the cell?**
   Not documented.
5. **When the "assistant de saisie" is authorised, does a double-click open the assistant instead of
   a free-text cell?** The assistant exists and is enabled per profile under "Ressources >
   Professeurs > Profils d'autorisations > Appréciations > Utiliser l'assistant de saisie"
   ([fiche 1680-4303][f4303]); the documentation does not say how it changes the double-click.
   Test both with the box ticked and unticked.

## B. Length and characters

6. **What happens at the maximum length?** Documented: 255 characters by default, a counter shows
   the remaining characters, and an administrator can change the maximum in "Paramètres >
   Évaluation > Bilans périodiques" ([fiche 1096-4346][f4346], [fiche 1680-4304][f4304]). Open:
   does typing stop at the limit, is a pasted longer text truncated silently or refused, and are
   spaces, line breaks and accented letters each counted as one character?
7. **What is the highest value the administrator can set?** Not stated on the pages above.
8. **Are accented capitals, typographic apostrophes (’), non-breaking spaces, « guillemets » and
   emoji kept exactly as typed?** Not documented. Check on Windows and on the macOS Client (Wine),
   because the Mac Client runs the Windows application through Wine
   ([fiche 456-4122][f4122]).

## C. Reading back and already-filled cells

9. **What does the teacher see when the cell already contains text?** Not documented: is the
   existing text shown in full, truncated with an ellipsis, or in a tooltip; does a double-click
   place the cursor at the end, select everything, or replace the text on the first keystroke?
10. **Is a long comment fully readable in the cell after leaving the row** (needed for the
    read-back in `agent/targets/pronote.md`), or does it need a wider column, a tooltip or
    another display? Not documented. The administrator's "Bulletins > Vérification > Vérification
    des bulletins" only marks missing teacher comments with a red cross in "App. professeurs"
    ([fiche 1680-6795][f6795]).
11. **What does the teacher see when the period is closed?** Documented: after the closure date a
    comment can no longer be created, changed or deleted, and an administrator moves the date in
    "Ressources > Classes > Clôture des périodes" ([fiche 4087-4300][f4300]). Open: is the cell
    greyed, does a double-click do nothing, or does a message appear (exact wording)?
12. **When is the comment written to the server: on validation, on leaving the row, or on leaving
    the display?** Saving is automatic in general ([fiche 324-2117][f2117]) but the moment is not
    stated. Test: validate, then read the cell from a second Client (administrative mode) without
    leaving the row.
13. **What happens if two users edit the same comment at once** (teacher Client and administrator
    Client)? Not documented: lock, last write wins, or warning.

## D. Finding the right student

14. **How are students displayed and sorted in the grid** ("MARTIN Léa", "Léa MARTIN", with or
    without a number)? Not documented. Needed to tell apart the two Lucas and the
    Gaël / Gaëlle pair in the fictitious roster (`scripts/pronote/import-files/`).
15. **How is the service labelled in the left list** (subject only, subject and class, subject and
    teacher)? Not documented beyond "sélectionnez le service" ([fiche 1096-4341][f4341]).
16. **Which period is selected by default in the drop-down?** Not documented.

## E. Session and environment

17. **Does the teacher-mode Client disconnect after inactivity, and after how long?** Not found in
    the documentation.
18. **Does "Utilisateur monoposte 2026" offer the teacher mode at all?** The teacher-side pages are
    filed under "Client & Monoposte" ([teacher support index][ens]) but no page says how a teacher
    logs in to the monoposte application. If it does not, use the server set-up.
19. **Which TCP port does a non-hosted "SERVEUR 2026" publish by default?** Documented: the
    address and port are shown in the Server's "Paramètres de publication"
    ([fiche 456-4121][f4121], [fiche 456-2077][f2077]); the port 49300 appears only in the hosted
    example ([fiche 456-1822][f1822]). Also open: does the Windows firewall need a manual rule for
    the Mac to connect?
20. **At what screen scaling is the grid readable for the agent's screenshots?** Index Education
    recommends the system resolution and scaling, with a tolerance of one step
    ([fiche 456-1886][f1886]); the agent needs a fixed value. On the Mac Client, check the
    dual-screen issue mentioned on the macOS page ([fiche 456-4122][f4122]).

## F. Import

21. **What is the exact "Type de données à importer" label for students, and which fields are
    mandatory?** The import window, the "Tabulation" separator and the column mapping are
    documented ([fiche 4032-4187][f4187], [fiche 323-1868][f1868]); the student label and mandatory
    fields are not. "Elèves et leurs responsables" is one documented type
    ([fiche 4070-4439][f4439]).
22. **Which encoding does "Imports/Exports > TXT/CSV/XML > Importer un fichier texte" expect
    (UTF-8, UTF-8 with BOM, Windows-1252)?** Not documented. Check that "LEFÈVRE", "Gaël", "Gaëlle",
    "Inès" and "Chloé" import correctly.
23. **Where are the teacher's login and password set when the teacher is created by hand?** The
    guide documents sending them with the "Connexion" letter template from "Ressources >
    Professeurs > Liste" and forcing a password change via "Modifier la sélection > Mot de passe et
    code PIN" ([Guide pratique, PDF p. 207][guide207], [PDF p. 139][guide139]); it does not say
    whether PRONOTE generates the login or the administrator types it.

[f4341]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1096-4341-saisir-les-appreciations.php
[f2117]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-324-2117-que-dois-je-faire-pour-enregistrer-les-modifications-dans-la-base.php
[f4303]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1680-4303-comment-s-effectue-la-saisie-des-appreciations-cote-professeurs.php
[f4346]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1096-4346-peut-on-augmenter-la-longueur-maximale-des-appreciations.php
[f4304]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1680-4304-comment-augmenter-la-taille-maximale-des-appreciations.php
[f4122]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-4122-nous-n-utilisons-pas-le-systeme-d-exploitation-windows-comment-installer-pronote-sur-macos-ou-linux.php
[f6795]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-1680-6795-superviser-le-remplissage-des-bulletins.php
[f4300]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-4087-4300-je-ne-peux-plus-modifier-un-bulletin-car-la-date-de-cloture-est-passee-comment-faire.php
[ens]: https://docs.index-education.com/docs_fr/fr-support-pronote-enseignants-client.php
[f4121]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-4121-nous-n-avons-pas-choisi-pronote-en-mode-heberge-comment-installer-pronote-sur-windows.php
[f2077]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-2077-ou-trouver-l-adresse-ip-du-serveur-pronote.php
[f1822]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-1822-installer-le-client.php
[f1886]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-456-1886-quelle-est-la-configuration-minimale--recommandee-pour-utiliser-correctement-le-client-pronote-avec-windows.php
[f4187]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-4032-4187-comment-importer-les-donnees-d-un-tableur-dans-une-liste.php
[f1868]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-323-1868-comment-completer-la-base-avec-les-donnees-qui-ne-proviennent-ni-de-pronote-ni-d-edt.php
[f4439]: https://docs.index-education.com/docs_fr/fr-pronote-support-fiche-4070-4439-j-ai-essaye-d-importer-les-responsables-dans-la-base-mais-je-n-arrive-pas-a-associer-plusieurs-responsables-a-un-meme-eleve-.php
[guide28]: https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=28
[guide207]: https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=207
[guide139]: https://www.index-education.com/contenu/telechargement/edt/v2026.0/pdf/Guide-Pratique-EDT-PRONOTE-FR-2026.pdf#page=139
