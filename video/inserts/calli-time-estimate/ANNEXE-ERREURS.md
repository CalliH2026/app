# Calli : sensibilité aux erreurs et aux corrections

**Scénarios hypothétiques, pas des taux d'erreur mesurés.** Cette annexe complète le modèle de temps actif. Elle ne relève pas le chiffre mis en avant dans la vidéo.

Oui, le coût des erreurs peut être modélisé statistiquement : nombre attendu de commentaires à corriger × temps supplémentaire moyen de correction. Pour dix commentaires, un taux hypothétique de 10 % représente une correction en moyenne, pas une correction certaine.

On ajoute ce coût aux **deux** parcours : corrections de frappe côté humain ; corrections de transcription et intervention après incident d'écriture côté Calli. La relecture déjà comptée dans le modèle de base et les retours arrière déjà inclus dans une vitesse de frappe effective ne doivent pas être comptés deux fois.

## Calcul

`H = H0 + n × p_h × c_h`

`C = C0 + n × (p_transcription × c_transcription + p_interface × c_interface)`

`Gain = 1 − E[C] / E[H]`

Les coûts sont des temps humains actifs supplémentaires. L'addition des espérances ne suppose pas l'indépendance des incidents ; il faut toutefois attribuer chaque coût une seule fois. Ce ratio de temps moyens n'est pas la moyenne des pourcentages individuels.

Base centrale inchangée : 464.3 s manuellement et 239.0 s avec Calli, pour 10 textes déjà rédigés. Frappe 225 caractères/min, dictée 100 mots/min, relecture 8 s/commentaire dans les deux cas. Ce sont aussi des hypothèses.

| Scénario illustratif | Correction humaine ajoutée | Correction Calli ajoutée | Gain de temps actif estimé |
|---|---:|---:|---:|
| Base, sans correction supplémentaire | 0 s | 0 s | 48.5 % |
| Charge de correction égale | 15 s | 15 s | 47.0 % |
| Davantage de corrections Calli | 15 s | 60 s | 37.6 % |
| Scénario défavorable à Calli | 15 s | 240 s | 0.1 % |

Scénarios détaillés :

- Base : aucune correction supplémentaire dans les deux parcours.
- Charge égale : 10 % des commentaires demandent 15 s de correction dans chacun des parcours.
- Davantage de corrections Calli : côté manuel, 10 % × 15 s ; côté Calli, transcription 20 % × 15 s et interface 10 % × 30 s.
- Scénario défavorable à Calli : côté manuel, 10 % × 15 s ; côté Calli, transcription 40 % × 30 s et interface 20 % × 60 s.

**Seuil utile :** le gain disparaît si Calli demande environ 225 s de correction humaine **de plus** que le parcours manuel, soit 22.5 s supplémentaires par commentaire en moyenne. Ce seuil vaut uniquement pour le scénario central choisi.

## Ce qu'on peut dire au jury

« Notre scénario central estime environ 50 % de temps actif en moins. Nous avons aussi modélisé les corrections des deux côtés ; le résultat dépend du taux d'incident et du temps de reprise. La prochaine validation est un essai comparatif avec des enseignants. »

Les paramètres ci-dessus ne sont ni des moyennes de population, ni des résultats du prototype, ni un intervalle de confiance. Un taux d'erreur de mots de transcription ne se convertit pas directement en proportion de commentaires nécessitant une reprise. Une erreur non détectée reste un problème de qualité même si elle ne coûte pas de temps.

## Mesure suivante

Utiliser les mêmes commentaires fictifs, alterner l'ordre manuel/Calli, enregistrer le temps actif et le temps total, puis une personne indépendante compare identité et texte. Journaliser séparément corrections spontanées, erreurs détectées à la relecture, incidents d'interface, abstentions et erreurs restantes. Rapporter le nombre de participants et de commentaires, les dénominateurs et la distribution des temps de correction ; tenir compte des commentaires regroupés par participant pour estimer l'incertitude. Aucun de ces essais n'a encore été réalisé.

Paramètres et résultats reproductibles : `calli-erreurs-sensibilite.json`.
