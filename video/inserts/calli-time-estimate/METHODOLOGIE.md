# Calli · estimation du temps actif (insert vidéo)

**Scénario modélisé, pas une mesure.** Ni la saisie manuelle ni l'usage de Calli n'ont été chronométrés auprès d'enseignants : les deux barres sont des estimations calculées. Aucun test utilisateur n'a été réalisé.

## Fichiers

| Fichier | SHA-256 | ffprobe |
|---|---|---|
| `video/inserts/calli-time-estimate/calli-estimation-temps.mp4` | `226010682129b342eb44cfb3222c137f520da1bc74d23a5cc671406ebbee9b0f` | H.264, 1920x1080, 30 fps, 270 images, 9,000 s, sans piste audio, 711 681 octets |
| `video/inserts/calli-time-estimate/calli-estimation-temps.png` (dernière image, n° 269) | `bd7a595340b002225828c22e60f74897fa26578faf35ad98b2bf6594c07bd13b` | 1920x1080, 217 465 octets |
| `video/inserts/calli-time-estimate/model.json` (modèle et limites) | `d791b57560cfa2987287adeb30407f1a7b904ead47b04f3d893fa15da7dce51d` | — |

Rendu sur la machine Devin avec Remotion (composition `CalliTimeEstimate`, `video/explainer/src/inserts/CalliTimeEstimate.tsx`) :

```
cd video/explainer && npm run render:calli-estimate
```

Tous les nombres affichés sont lus dans `model.json` au moment du rendu ; aucune valeur n'est saisie à la main dans l'animation.

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
