# Recherche bornée de combinaisons

La commande `classeur-nutrition search --dir <dossier> --max-candidates 100 --keep 3`
compare des remplacements déclarés dans une bibliothèque privée. Elle ne modifie
ni les semaines sources ni leurs consignes. Les profils v2 sont requis.

Créer `search.yaml` (privé et ignoré par Git) :

```yaml
version: 1
emplacements:
  - id: S01-R01
    choix: [plat_rapide, plat_econome]
  - id: S01-R02
    choix: [garniture_saison, autre_garniture]
```

Les noms désignent `bibliotheque/<nom>.json`, produit par `save-recipe` après
revue. L'historique de revue d'une recette n'est jamais une validation dans le
nouveau profil. Le nombre de portions source est explicite ; les ingrédients,
formes brutes, alternatives et eau retenue sont proportionnés avant recalcul.
Les recettes verrouillées ne sont modifiées ni par cette commande ni par `select`.

Le moteur énumère dans l'ordre déclaré au plus 200 combinaisons, avec huit
emplacements et vingt choix par emplacement au maximum. Le rapport indique
le nombre de combinaisons possibles, le nombre évalué et si la recherche est
tronquée. Une erreur impérative ou un budget impératif invérifiable exclut une
combinaison. Les achats déduisent le stock puis arrondissent aux conditionnements.
Un calendrier présent ajoute ses contrôles et son budget opérationnel aux calculs.

Parmi les essais admissibles, la frontière conserve les compromis non dominés
sur écarts préférentiels (incertitudes comprises), budget, temps actif, difficulté
et variété. Une valeur inconnue est moins favorable qu'une valeur connue pour
le même critère. Les priorités du profil puis l'identifiant ordonnent les résultats
retenus, au plus dix. Les durées, difficulté et variété concernent les fiches
sources ; en présence d'un calendrier, le budget concerne ses occurrences.
Le rapport conserve aussi tous les rejets et les données manquantes. Le résultat
porte uniquement sur les combinaisons effectivement évaluées, sans garantie
d'optimum universel ni recherche dans des recettes non fournies.

La sortie par défaut est `out/recherche/`, obligatoirement nouvelle. `--output`
permet de choisir une autre destination privée nouvelle. Elle contient les entrées
communes, les propositions retenues et `rapport.json`, sans revue transférée.
On peut comparer les résultats avec `select --dir <sortie>`, puis reprendre le
classeur choisi, refaire le rendu et sa revue. Les favoris restent un outil de
rangement ; aucune interdiction n'est compensée par un favori ou un prix bas.
