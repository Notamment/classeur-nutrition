# Adaptation et sélection — profils v2

Les réglages ci-dessous sont facultatifs et désactivés par défaut. Les profils v1 restent inchangés. La génération des recettes appartient toujours à l'agent ; la sélection compare les classeurs qu'il propose, sans inventer ni recombiner des recettes.

## Paramètres à modifier

```yaml
version: 2
projet:
  semaines: 2
  recettes_par_semaine: 4
repas:
  difficulte_max: facile
  duree_active_max_min: 15
  duree_totale_max_min: 40
variete:
  recettes_distinctes_min_par_semaine: 3
  ingredient_principal_max_par_semaine: 2
  techniques_distinctes_min_par_semaine: 2
  repetition_plat_max: 2
aliments:
  familles_exclues: [soja]
  familles_a_eviter: [champignons]
budget:
  plafond_eur_semaine: 45
exigences:
  duree_active: preference
  variete_plats: preference
selection:
  priorites: [budget, temps_actif, difficulte, variete]
```

| Paramètre | Mesure et portée | Code d'exigence |
|---|---|---|
| `repas.difficulte_max` | Niveau maximal par recette : `facile`, `intermediaire`, `avancee`. | `difficulte` |
| `repas.duree_active_max_min` | Minutes de gestes et de surveillance active par préparation, toutes les portions ensemble. | `duree_active` |
| `repas.duree_totale_max_min` | Durée écoulée, préparation, cuisson et attente comprises. | `duree` |
| `variete.recettes_distinctes_min_par_semaine` | Nombre de `plat_id` distincts dans une semaine. | `variete_plats` |
| `variete.ingredient_principal_max_par_semaine` | Nombre de recettes d'une semaine ayant le même aliment déclaré principal. | `ingredient_recurrent` |
| `variete.techniques_distinctes_min_par_semaine` | Nombre de techniques différentes utilisées dans une semaine. | `variete_techniques` |
| `variete.repetition_plat_max` | Nombre maximal d'occurrences d'un même `plat_id` dans tout le classeur. | `repetition_plat` |

`null` désactive chaque limite. `0` est une vraie valeur : un minimum nul n'impose rien ; un maximum nul interdit toute occurrence ou toute minute active. Une limite active est impérative par défaut ; `exigences.<code>: preference` rend ses écarts non bloquants. Une limite sans métadonnées suffisantes est explicitement invérifiable, jamais considérée comme satisfaite. Des temps négatifs, un temps actif supérieur au total ou des métadonnées invalides restent des erreurs strictes.

## Métadonnées à fournir dans le plan et les recettes

```yaml
plat_id: omelette_pommes_de_terre
ingredients_principaux: [oeuf, pomme_de_terre]
temps_actif_min: 15
temps_total_min: 30
execution:
  techniques: [decoupe_simple, cuisson_poele]
  taches_simultanees: 2
```

- `plat_id` décrit le plat, indépendamment de l'identifiant `SXX-RYY` de sa préparation. Réutiliser le même identifiant lorsque seul le titre, la portion ou un assaisonnement mineur change. Il n'y a pas de détection automatique des synonymes.
- `ingredients_principaux` : un à trois identifiants distincts, réellement présents dans la recette ; choisir ce qui caractérise le repas. Les condiments communs ne deviennent pas automatiquement des ingrédients principaux. Le plan les annonce ; les recettes permettent de vérifier leur présence.
- `execution.techniques` : identifiants du catalogue, sans doublons. Déclarer tous les gestes nécessaires, y compris une préparation préalable. Une technique absente du catalogue doit être ajoutée à celui-ci et testée, pas remplacée par un identifiant inventé.
- `execution.taches_simultanees` : maximum de tâches demandant de l'attention au même moment, entier au moins égal à 1. Une cuisson passive n'est pas une tâche active.
- Le temps actif est le temps d'attention de la personne qui cuisine ; il ne cumule pas deux fois une période de tâches simultanées. Le script ne déduit pas les durées des étapes.

La difficulté est **le maximum** du niveau des techniques et du niveau de coordination : 1–2 tâches simultanées = facile, 3 = intermédiaire, 4 ou plus = avancée. Ce barème explicite est une estimation, pas une certification du niveau d'un cuisinier. Le rendu donne les raisons du niveau retenu.

```bash
python skills/meal-binder/scripts/binder.py list-options
python skills/meal-binder/scripts/binder.py list-options --json
```

`list-options` expose les techniques, familles et critères disponibles depuis `data/techniques.yaml` et `data/families.yaml`. Sans nouvelles limites actives, les recettes v2 précédentes restent valides sans ces métadonnées ; leurs métriques de sélection restent inconnues.

## Familles d'ingrédients

`aliments.familles_exclues` est toujours strict. `aliments.familles_a_eviter` est une préférence fixe. Ces règles complètent les identifiants individuels `exclus` et `a_eviter` ; elles s'appliquent aux ingrédients et aux alternatives poisson proposées.

Une famille rassemble des aliments selon leur nature, leurs tags ou leurs identifiants. L'appartenance aux familles parentes est héritée. Ainsi, `soja` inclut le tofu et les condiments tagués `soja_condiment`, dont miso et sauce soja ; exclure `legumineuses`, parent du soja, couvre aussi ces dérivés. Cette famille culinaire est distincte de la règle de quantité et d'alternance des légumineuses, qui conserve ses conventions historiques.

Pour un produit composite de `foods.local.csv`, ajouter un ou plusieurs tags `famille:<identifiant>` selon sa composition renseignée. Un tag inconnu est une erreur ; ne pas modifier les colonnes du CSV. Le catalogue n'analyse ni le nom du produit ni son étiquette et ne couvre pas automatiquement tous les dérivés. Une famille absente des correspondances doit être documentée avant de prétendre appliquer son exclusion. Ce n'est pas un moteur d'allergènes, de traces ni de certifications.

## Comparer des propositions complètes

Pour chercher un compromis, l'agent produit quelques classeurs complets, par exemple économique, rapide et varié, avec les mêmes contraintes. Les données communes restent à la racine :

```text
mon-classeur/
  profile.yaml
  pantry.yaml                 # facultatif, stock commun
  stores.yaml                 # facultatif
  foods.local.csv             # prix et produits communs, si renseignés
  propositions/
    economique/weeks/S01.json
    economique/weeks/S02.json
    rapide/weeks/S01.json
    rapide/weeks/S02.json
```

De 1 à 30 dossiers, identifiants commençant par une lettre minuscule puis lettres minuscules, chiffres, `_` ou `-`. Pas de lien symbolique pour un dossier de proposition. Les fichiers de configuration à l'intérieur d'une proposition sont refusés : une proposition ne peut pas assouplir son profil ni changer son stock pour gagner.

```bash
python skills/meal-binder/scripts/binder.py select --dir mon-classeur
python skills/meal-binder/scripts/binder.py select --dir mon-classeur --json
```

Ordre de décision, sans poids cachés :

1. Rejeter les propositions incomplètes, les données invalides, les violations impératives et les plafonds budgétaires impératifs invérifiables. Une proposition invalide n'empêche pas l'examen des autres.
2. Minimiser les écarts préférentiels : **un écart par règle et portée** (recette, semaine ou classeur). Une préférence invérifiable compte aussi. Si une règle est déjà connue comme violée à cette portée, son incertitude ne la pénalise pas une deuxième fois ; tous les détails restent dans les écarts.
3. Départager selon l'ordre de `selection.priorites`. Une priorité est un critère de départage, pas une nouvelle limite. Liste vide : seulement les préférences, puis l'identifiant. Critères inconnus ou dupliqués refusés.
4. Pour chaque critère, classer une valeur inconnue après une valeur connue. Ne jamais remplacer une donnée absente par zéro.
5. En cas d'égalité, départager par ordre alphabétique des identifiants ; le rapport le dit explicitement.

| Critère | Mesure | Sens |
|---|---|---|
| `budget` | Somme des montants caisse hebdomadaires, stock commun déduit, achats bruts, emballages et reports compris. Inconnue si une semaine est invérifiable. | Minimiser |
| `temps_actif` | Somme des minutes actives de toutes les préparations prévues. | Minimiser |
| `difficulte` | Niveau maximal parmi les recettes (1, 2 ou 3). | Minimiser |
| `variete` | Nombre de `plat_id` distincts dans le classeur. | Maximiser |

Le plafond budgétaire reste **hebdomadaire**, même si le départage compare le coût total. Le coût consommé n'est pas le montant à payer en caisse. Les alternatives poisson non retenues ne sont pas achetées. Les prix sont ceux du dossier, sans recherche commerciale automatique. Les coûts non finis ou partiels ne constituent pas des mesures classables.

### Sortie et reprise

La commande écrit `out/selection/rapport.md` et `rapport.json` : méthode, classement, premier critère décisif, motifs de rejet et écarts visibles. Si une proposition est admissible, ce dossier contient aussi une copie des semaines retenues, du profil résolu, du stock initial et des données locales, ainsi que `out/classeur.md`.

```bash
python skills/meal-binder/scripts/binder.py check-all --dir mon-classeur/out/selection
python skills/meal-binder/scripts/binder.py render --dir mon-classeur/out/selection
```

Ce dossier est réanalysable avec la même version du dépôt ; le catalogue et la base globale restent ceux du dépôt. Il ne contient pas de `plan.yaml`. Les sources ne sont pas modifiées. Une nouvelle sélection remplace atomiquement cette sortie générée ; si aucun candidat ne convient, elle conserve uniquement les rapports, sans ancien classeur ambigu. Un dossier `out/selection` non reconnu comme généré n'est pas écrasé.

Avec `--json`, le rapport seul est écrit sur stdout. Code `0` si une proposition est retenue ; `1` si aucune n'est admissible ou si la configuration est invalide ; `2` si les entrées sont absentes/illisibles ou le dossier de sortie protégé ; `3` pour une panne interne. Une erreur avant comparaison conserve le format historique de liste d'écarts. Les alertes n'interdisent pas forcément la sélection ; consulter le rapport.

Cette méthode compare **l'ensemble fourni**, pas toutes les recettes possibles. Elle ne garantit pas un optimum global et ne fabrique pas une recette pour résoudre une contradiction. L'agent peut améliorer ses propositions à partir du rapport, sans modifier les exigences en silence.
