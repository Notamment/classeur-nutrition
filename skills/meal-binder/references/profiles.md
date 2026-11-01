# Profils, préréglages et exigences

## Version et compatibilité

- `version: 1` ou version absente : comportement historique, y compris cibles et valeurs par défaut. Le modèle historique est conservé dans `meal-setup/assets/profile.v1.template.yaml`.
- `version: 2` : défauts neutres. Une semaine, cinq recettes, deux portions ; nutrition désactivée, aucun quota alimentaire, aucun régime imposé, aucun label demandé, aucune limite de temps ou de budget, cuisines répétées autorisées. Ces dimensions se configurent indépendamment.
- Changer uniquement le numéro d'un profil v1 conserve ses valeurs explicites : cela ne neutralise pas automatiquement ses contraintes. Pour repartir sans héritage personnel, copier le modèle v2.
- Le résolveur et ses défauts sont dans `scripts/profiles.py`, les schémas dans `scripts/schemas.py`.

## Composition

Ordre : **défauts de la version → préréglages → champs explicites du profil**. Fusion récursive des objets ; remplacement complet des listes et scalaires. Omettre un champ pour hériter ; `null` désactive une limite nullable ; `0` signifie réellement zéro, jamais « inconnu » ; `[]` signifie une liste vide. Un objet vide ne supprime pas ses valeurs héritées.

```yaml
version: 2
prereglages: [vegetarien, rapide, petit_budget]
projet:
  semaines: 2
  recettes_par_semaine: 4
  portions_par_recette: 3
repas:
  duree_totale_max_min: 25
budget:
  plafond_eur_semaine: 55
exigences:
  duree: imperative
  budget_depasse: preference
aliments:
  exclus: [champignon_paris]
  a_eviter: [brocoli]
```

| Préréglage | Effet |
|---|---|
| `rapide` | Temps total maximal de 30 min. |
| `vegetarien` | Régime ovo-lacto-végétarien : ni viande ni poisson. |
| `petit_budget` | Cible indicative de 40 EUR/semaine, traitée comme préférence. Montant à ajuster au nombre de repas et de portions ; aucune promesse de faisabilité. |
| `gamelles` | Deux portions et usage dîner + gamelle. Les notes de transport et réchauffage sont rédigées par l'agent. |
| `cuisines_du_monde` | Une cuisine par semaine, cuisines distinctes, authenticité documentée. |
| `recomposition` | Cibles du profil initial : protéines 32–40 g/portion, poids 450–580 g, légumineuses 80–120 g si présentes et non consécutives, marqueurs fer + vitamine C. Choix personnels, pas des recommandations universelles. |

Les définitions exécutables sont les YAML de `data/presets/`. Les préréglages sont orthogonaux ; deux valeurs contradictoires sur un même champ provoquent `prereglages_conflit`, sauf si ce choix est explicitement résolu dans le profil. Aucun « dernier préréglage gagnant » silencieux. Les noms inconnus et les doublons sont refusés.

```bash
python skills/meal-binder/scripts/binder.py list-presets
python skills/meal-binder/scripts/binder.py show-profile --dir mon-classeur
python skills/meal-binder/scripts/binder.py show-profile --dir mon-classeur --json
```

`show-profile` renvoie `profil` (valeurs effectives), `origines` (par champ : défaut/préréglage/profil) et `ecarts`. Pour un outil externe ou le prompt monolithique, extraire seulement `profil`. Les commandes de contrôle continuent à renvoyer une liste d'écarts avec `--json`. `list-presets` renvoie le catalogue.

## Nutrition facultative

| `nutrition.mode` | Calculs et rendu | Objectifs protéines, kcal, fer + vitamine C |
|---|---|---|
| `desactive` | Ni calcul ni colonnes nutritionnelles ; les courses et poids servis fonctionnent. | Inactifs. |
| `information` | Estimations si données présentes ; une métrique incomplète est `—`, jamais zéro ni un total partiel. | Inactifs. |
| `cibles` | Même calcul ; contrôle des cibles explicitement configurées. | Actifs. Une métrique requise absente est invérifiable et bloque une cible impérative. |

Les plages présentes hors mode `cibles` sont signalées `cibles_inactives`. Poids servi, quantité de légumineuses, variété et budget restent indépendants du mode nutritionnel. Les chiffres provisoires de la base restent des estimations, même en mode cibles. Les contrôles fer/C détectent des marqueurs, sans mesurer les apports.

## Contraintes et préférences

Une règle configurée est `imperative` par défaut. `exigences.<code>: preference` transforme son écart en alerte explicite, visible dans le classeur et l'audit. Le profil n'est jamais réécrit pour masquer un écart. La commande `select` compare des propositions complètes selon ces écarts et des priorités ordonnées, sans poids cachés : voir [adaptation et sélection](adaptation.md).

Codes configurables : `proteines`, `kcal`, `poids_servi`, `duree`, `duree_active`, `difficulte`, `repartition`, `legumineuses_g`, `legumineuses_consecutives`, `riz`, `feculents`, `substituts`, `espece_doublon`, `cruciferes`, `ala`, `diversite`, `cuisine_doublon`, `variete_plats`, `repetition_plat`, `ingredient_recurrent`, `variete_techniques`, `fer_vitc`, `sel`, `budget_depasse`.

Toujours stricts : schémas, identifiants, unités, quantités, conversions, temps actif supérieur au total, matériel renseigné, exclusions et régime. La somme d'une répartition configurée doit correspondre au nombre de recettes, même si la répartition est préférentielle. Les données de configuration incohérentes ne sont jamais déclassées.

- `aliments.exclus` : interdiction stricte par identifiant d'aliment.
- `aliments.a_eviter` : préférence fixe, ne pas confondre avec une allergie.
- `aliments.familles_exclues` / `familles_a_eviter` : mêmes politiques pour des familles et leurs dérivés identifiés ; catalogue via `list-options` et [référence](adaptation.md).
- `alimentation.regime` : `libre`, `vegetarien`, `vegetalien`, `pescetarien`. Contrôle selon `foods.csv.nature` ; vérifier les ingrédients composites et les étiquettes. Pas de moteur d'allergènes, de traces ou de certifications.
- `repartition: null` : aucun quota ; sinon nombres de recettes `vegetarien`, `poisson`, `viande`, et `mixte` facultatif (défaut 0). `mixte` signifie viande + poisson ; une recette végétalienne reste dans la catégorie `vegetarien`.
- `materiel: null` : équipement non renseigné ; `[]` : aucun appareil autorisé, à part `aucun`. Les instructions ne doivent pas inventer un équipement connu absent.

Budget : le plafond porte sur les achats des repas du classeur, épicerie incluse, et non toutes les dépenses du foyer. Un prix ou stock inconnu reste « non vérifié ». Dans l'évaluation et la sélection, un plafond impératif invérifiable empêche la conformité ; une préférence invérifiable ne bloque pas les autres contraintes et reste signalée. Les commandes de contrôle historiques conservent une alerte pour un budget inconnu : leur code 0 ne signifie pas qu'il est vérifié.

## Organisation

`projet.organisation` : `libre` (pas de cuisine exigée), `cuisines` (champ `cuisine` requis par semaine), `themes` (champ `theme` requis). `variete.cuisines_distinctes` active le contrôle des doublons. `projet.authenticite: documentee` rend la note `authenticite` obligatoire ; le script ne certifie pas sa véracité. En mode `libre`, une création est autorisée sans revendication traditionnelle trompeuse.

`gamelle` est facultatif dans le schéma v2. Le renseigner lorsque l'usage demandé le nécessite. Quantités des recettes pour toutes les portions : changer le nombre de portions sur un classeur existant ne multiplie pas automatiquement les ingrédients. L'agent doit redimensionner puis relancer les contrôles.

## Ajouter un préréglage

Créer `data/presets/<nom_snake_case>.yaml` avec `nom`, `description` et un `profil` partiel v2. Ne pas inclure `version` ni `prereglages`. Garder chaque préréglage concentré sur un usage. Les champs et types sont validés avant résolution ; ajouter un cas de test d'intégration et un exemple de combinaison.
