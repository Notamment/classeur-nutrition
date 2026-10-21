# Calendrier de production

`schedule.yaml` est un format opérationnel **version 1**, facultatif, distinct
des profils v1/v2 et de `plan.yaml`. Il n'en change ni les portions globales,
ni les quotas ni les défauts. `classeur-nutrition schedule --dir <dossier>` donne
son rapport JSON ; les mêmes contrôles alimentent analyse, sélection, rendu,
audit, revue et évaluation lorsque le fichier existe.

Exemple fictif pour un dossier contenant `S01-R01` :

```yaml
version: 1
stock_mode: lots_exclusifs
equipements:
  plaque: 1
preparations:
  - id: preparation_midi
    debut: '2026-01-02T10:00+01:00'
    duree_min: 60
    equipements: [plaque]
    utilisable_jusqua: '2026-01-02T13:00+01:00'
services:
  - id: midi
    debut: '2026-01-02T12:00+01:00'
    plats:
      - recette: S01-R01
        portions: 8
        preparation: preparation_midi
lots:
  - id: carottes_fictives
    food: carotte
    quantite: 500
    unite: g
    etat: cru
    disponible_le: '2026-01-01'
    limite: '2026-01-03'
    type_limite: DLC
    source: exemple fictif à remplacer
```

Les instants précisent leur décalage UTC. Les préparations référencées doivent
finir avant le service et déclarer une limite de conservation qui le couvre.
Les capacités d'équipement sont des nombres de préparations simultanées ; elles
ne modélisent pas la contenance des bacs ou fours. Un matériel requis par la
recette doit figurer dans la préparation. Une préparation absente est une donnée
impérative invérifiable. Les durées et limites restent déclaratives, à relire
pour les quantités réelles et les règles sanitaires applicables.

Chaque plat référence soit `recette`, soit `composant`. Les composants facultatifs
se déclarent sous `composants.<id>` avec `portions` et `recette` (même format de
recette que les semaines, avec un identifiant `SXX-RYY`). Ils sont des lignes
de service explicites ; aucun ingrédient d'une autre fiche n'est remplacé ou
soustrait automatiquement. Une garniture déjà comprise dans une recette ne doit
pas être ajoutée une seconde fois. Les mêmes exclusions, familles, cibles par
portion et contrôles de difficulté s'appliquent aux composants.

Les quantités sont proportionnées pour chaque occurrence, sans modifier la fiche
source. Les lots sont consommés à la date de préparation, par limite croissante,
puis identifiant. Un lot futur ou hors limite n'est jamais mobilisé. DLC et DDM
sont toutes deux exclues après la date déclarée, par précaution ; cela ne constitue
pas une validation sanitaire. Une quantité `null` reste inconnue et empêche un
budget impératif vérifiable. Quantités et état doivent correspondre à la référence
comestible de l'aliment. Les achats utilisent les conversions brutes et arrondis
de conditionnements du moteur historique.

Le mode `lots_exclusifs` exige de convertir explicitement le stock non daté de
`pantry.yaml` : sa présence avec des entrées est refusée pour éviter le double
comptage. Les restes d'achats sont affichés, **sans report automatique** tant
qu'un lot daté n'est pas déclaré. Les prix de `products.yaml` sont aussi vérifiés
à la date de préparation ; un tarif hors période devient inconnu. Le budget
opérationnel s'agrège par semaine ISO des préparations. Les calculs et plafonds
des semaines sources restent contrôlés séparément ; aucun impératif historique
n'est assoupli par l'ajout d'un calendrier. Les quotas et objectifs de variété
ne sont pas réinterprétés en nouveaux objectifs de calendrier.

Le calendrier, les lots et leurs sources restent privés. Ils font partie des
empreintes et des archives ; leur modification invalide la revue précédente.
Le classeur et l'audit donnent le calendrier et ses limites ; l'export production
ajoute les achats par occurrence et les lots effectivement mobilisés.
