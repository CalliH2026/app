# Calli · estimation du temps actif (insert vidéo, v2)

**Scénario modélisé, pas une mesure.** Ni la saisie manuelle ni l'usage de Calli n'ont été chronométrés auprès d'enseignants : les deux barres sont des estimations calculées. Aucun test utilisateur n'a été réalisé.

## Fichiers (v2)

| Fichier | SHA-256 | ffprobe |
|---|---|---|
| `video/inserts/calli-time-estimate/calli-estimation-temps-v2.mp4` | `e5e87c215d71b0066bc068782403fa4448aad24590eb7fc70c3c76565c4d7f0e` | H.264, 1920x1080, 30 fps, 270 images, 9,000 s, sans piste audio, 726 300 octets |
| `video/inserts/calli-time-estimate/calli-estimation-temps-v2.png` (dernière image, n° 269) | `9679f81727f59682d383b341e485b0b758d4c9e823e0722688fcc04e5384109a` | 1920x1080, 219 565 octets |
| `video/inserts/calli-time-estimate/model.json` (inchangé) | `d791b57560cfa2987287adeb30407f1a7b904ead47b04f3d893fa15da7dce51d` | — |

La v1 (`calli-estimation-temps.mp4/.png`, décrite dans `METHODOLOGIE.md`) est conservée telle quelle (rendue depuis le commit `4000a8a`). La v2 ne change aucune valeur du modèle : seule la hiérarchie du message change.

Rendu sur la machine Devin avec Remotion (composition `CalliTimeEstimate`, `video/explainer/src/inserts/CalliTimeEstimate.tsx`) :

```
cd video/explainer && npm run render:calli-estimate
```

## Ce qui change à l'écran (v2) et arrondis

- Message principal : « ≈ 50 % de temps actif en moins », accompagné d'une étiquette « estimation ». Valeur exacte du scénario central (225 caractères/min) : 48,521 %, arrondie à la dizaine la plus proche (50 %). Le signe ≈ indique l'arrondi.
- Ligne secondaire, en petit : « ≈ 3 min 45 économisées sur 10 appréciations (estimation) ». Valeur exacte : 225,267 s, arrondie à la seconde (3 min 45 s).
- Ligne tertiaire, en petit et en gris : « Ordre de grandeur approximatif : 40–60 % selon la vitesse de frappe (scénarios, pas un intervalle de confiance) ». Valeurs exactes : 36,806 % (300 car./min) à 62,445 % (150 car./min), arrondies à la dizaine (40 et 60 %). Le maximum de 62 % n'est pas mis en avant.
- Inchangés : les deux barres « estimée »/« estimé » sur le même axe en minutes partant de zéro (7 min 44 s et 3 min 59 s), le badge « Scénario modélisé · pas une mesure », et les hypothèses avec « aucun test utilisateur réalisé », visibles pendant les 4,4 dernières secondes.

Les arrondis sont calculés à partir de `model.json` au moment du rendu et vérifiés par `tests/test_calli_time_model.py`.

## Corpus

`data/pronote_batch_a.csv` (SHA-256 `c2ebde85…c1581d8bcdc1`) : 10 appréciations fictives déjà rédigées, 1 291 caractères (espaces compris), 215 mots dictés (comptage par espaces, prénoms et noms des élèves inclus). L'appréciation p03 contient volontairement une phrase d'injection de test. Ces comptages sont vérifiés par `tests/test_calli_time_model.py`.

## Modèle

- Saisie manuelle : `60 × caractères / frappe + 10 × (navigation et enregistrement 4 s + relecture 8 s)`.
- Avec Calli : `60 × mots / dictée + 10 × (transition de dictée 3 s + relecture 8 s) + intervention supplémentaire 0 s`.
- Hypothèses choisies pour l'illustration (ni moyennes de population, ni temps observés) : frappe 150, 225 ou 300 caractères/min ; dictée 100 mots/min.

| Frappe | Saisie manuelle (estimée) | Avec Calli (estimé) | Écart estimé |
|---|---|---|---|
| 150 car./min | 636,4 s (10 min 36 s) | 239,0 s (3 min 59 s) | 397,4 s, 62,4 % |
| **225 car./min (affiché)** | **464,3 s (7 min 44 s)** | **239,0 s (3 min 59 s)** | **225,3 s (≈ 3 min 45), 48,5 %** |
| 300 car./min | 378,2 s (6 min 18 s) | 239,0 s (3 min 59 s) | 139,2 s, 36,8 % |

La fourchette « environ 37 à 62 % » reflète uniquement la sensibilité aux vitesses de frappe choisies : ce n'est ni un intervalle de confiance ni une plage mesurée. L'écart estimé est aussi le temps d'intervention supplémentaire avec Calli au-delà duquel il n'y aurait plus de gain.

## Limites

- Les deux barres sont des estimations, y compris celle de l'enseignant qui utilise Calli. Il n'existe pas de mesure humaine de référence.
- Les textes sont déjà rédigés : l'évaluation pédagogique et la rédaction sont exclues des deux cas.
- La saisie manuelle suppose une frappe complète, sans import en lot, macro ni copier-coller.
- La relecture finale est la même dans les deux cas ; aucun clic de validation supplémentaire n'est compté pour Calli.
- Les écritures échouées, corrections de transcription, interruptions, installation et prise en main ne sont pas comptées ; toute intervention réduit le gain estimé.
- L'attente n'est exclue du temps actif que si l'enseignant peut réellement faire autre chose pendant ce temps.
- Ne pas extrapoler à des budgets, des emplois ou des économies annuelles sans données réelles d'usage et de coût.
