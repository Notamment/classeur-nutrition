# Classeur nutrition

Skills pour agents IA qui génèrent des **classeurs de recettes personnalisés** : repas du quotidien, menus végétariens, gamelles ou cuisines du monde. Semaines, portions, nutrition, temps, budget et préférences sont configurables. Courses par rayon, suivi du stock et audit sont calculés depuis les recettes.

**Principe : le modèle rédige, des scripts calculent.** Les scripts ne génèrent pas eux-mêmes de recettes par appel à un modèle. Ils valident les données, calculent les courses, rendent le document et contrôlent les exigences actives. Protéines et kcal sont facultatives. La fiabilité dépend des ingrédients, rendements et prix renseignés.

Les nouveaux profils utilisent `version: 2`, avec des défauts neutres. Les profils `version: 1` et sans version conservent leur comportement. Aucun objectif nutritionnel, régime, quota ni label bio n'est imposé en v2.

## Configurer son classeur

Partir de [`profile.template.yaml`](skills/meal-setup/assets/profile.template.yaml). Exemple :

```yaml
version: 2
prereglages: [vegetarien, rapide, petit_budget]
projet:
  semaines: 2
  recettes_par_semaine: 4
  portions_par_recette: 3
budget:
  plafond_eur_semaine: 55
nutrition:
  mode: information
exigences:
  budget_depasse: preference
aliments:
  exclus: [champignon_paris]
  a_eviter: [brocoli]
```

Les choix explicites priment sur les préréglages, qui priment sur les défauts. Les listes sont remplacées ; une option absente hérite. `null` désactive une limite nullable, `0` reste zéro. Un conflit entre préréglages exige un choix explicite au lieu d'un arbitrage silencieux.

```bash
python skills/meal-binder/scripts/binder.py list-presets
python skills/meal-binder/scripts/binder.py show-profile --dir mon-classeur
```

`show-profile` présente la configuration effective et l'origine de chaque valeur. Six préréglages : `rapide`, `vegetarien`, `petit_budget`, `gamelles`, `cuisines_du_monde`, `recomposition`. Le dernier reprend les cibles personnelles du projet initial ; il n'est pas activé par défaut.

| Choix | Comportement |
|---|---|
| Nutrition `desactive` | Courses et recettes sans calcul nutritionnel. |
| Nutrition `information` | Estimations affichées ; données absentes indiquées, sans objectif imposé. |
| Nutrition `cibles` | Contrôle des plages configurées ; une cible impérative invérifiable échoue. |
| Exigence `imperative` | Écart bloquant. |
| Exigence `preference` | Écart visible, non bloquant. |

Les erreurs de données, conversions, exclusions et régimes restent strictes. [Référence complète des profils](skills/meal-binder/references/profiles.md).

## Adapter les recettes et comparer les choix

Ces options v2 s'ajoutent au profil ; les limites absentes restent désactivées :

```yaml
repas:
  difficulte_max: facile
  duree_active_max_min: 15
variete:
  recettes_distinctes_min_par_semaine: 4
  ingredient_principal_max_par_semaine: 2
  repetition_plat_max: 1
aliments:
  familles_exclues: [soja]
  familles_a_eviter: [champignons]
exigences:
  duree_active: preference
selection:
  priorites: [budget, temps_actif, difficulte, variete]
```

La difficulté est estimée à partir des techniques et des tâches simultanées déclarées ; le temps actif est distinct du temps total. La variété repose sur des identifiants de plats stables, des ingrédients principaux et des techniques renseignés. Les exclusions par familles incluent les dérivés identifiés dans la base, par exemple miso et sauce soja pour le soja.

L'agent peut proposer plusieurs classeurs complets sous `propositions/<id>/weeks/`. La commande `select` écarte les violations impératives, minimise les préférences insatisfaites ou invérifiables, puis départage selon les priorités. Le budget compare les **achats en caisse**, stock et emballages compris. Le rapport explique chaque rejet et le critère qui départage les propositions admissibles.

```bash
python skills/meal-binder/scripts/binder.py list-options
python skills/meal-binder/scripts/binder.py select --dir examples/adaptation
python skills/meal-binder/scripts/binder.py check-all --dir examples/adaptation/out/selection
```

→ [Exemple complet](examples/adaptation/README.md), avec trois propositions et des **prix fictifs réservés à la démonstration**. Le classeur retenu est copié sous `out/selection/out/classeur.md`, avec ses données et ses rapports ; les entrées sont conservées. La comparaison porte sur les propositions fournies, sans garantie d'optimum global. [Paramètres, formats et méthode détaillés](skills/meal-binder/references/adaptation.md).

## Démarrage

### Avec un agent compatible Agent Skills (recommandé)

Claude Code, Codex, Gemini CLI, Cursor, Copilot et d'autres lisent le format `SKILL.md`.

1. Copier `skills/meal-setup/` et `skills/meal-binder/` dans le dossier de skills de votre agent (ex. `~/.claude/skills/` pour Claude Code ; voir la documentation de votre agent).
2. Python 3.10 ou plus récent (`python --version`), puis `pip install -r requirements.txt`
3. Demander : « Configure mon profil pour le classeur de repas », puis « Génère mon classeur automne ».

L'agent a besoin d'exécuter du Python.

### Dans un chat sans exécution de code

Copier [`dist/prompt.md`](dist/prompt.md), y coller votre profil, l'envoyer. Le prompt embarque les défauts et préréglages ; le modèle les applique sans vérification automatisée des calculs.

### Voir le résultat sans agent

```bash
python skills/meal-binder/scripts/binder.py check-plan --dir examples/generaliste/vegetarien_rapide_budget
python skills/meal-binder/scripts/binder.py render --dir examples/generaliste/vegetarien_rapide_budget
```

→ [`examples/generaliste/vegetarien_rapide_budget/out/classeur.md`](examples/generaliste/vegetarien_rapide_budget/out/classeur.md). Les [trois exemples v2](examples/generaliste/README.md) couvrent famille sans nutrition, végétarien rapide et objectifs protéiques avec gamelles. Les prix sont absents, donc les budgets restent non vérifiés.

La [démo historique v1](examples/demo/out/classeur.md) conserve ses cinq écarts intentionnels et sert de test de compatibilité.

## Fonctionnement

`meal-setup` configure le profil et, si nécessaire, le stock et les magasins. `meal-binder` résout ce profil, rédige un plan puis les semaines, corrige les écarts et produit `out/classeur.md`. Les paramètres restent dans les fichiers YAML ; il n'est pas nécessaire de modifier le code pour changer d'usage.

| Dossier | Contenu |
|---|---|
| `skills/meal-setup/` | Création du profil, du stock et de la liste de magasins. |
| `skills/meal-binder/` | Workflow (`SKILL.md`), règles (`references/`), base d'aliments (`data/`), scripts. |
| `examples/demo/` | Dossier de travail complet, profil fictif. |
| `examples/generaliste/` | Trois parcours v2 complets, contrôlés de bout en bout. |
| `examples/adaptation/` | Comparaison de propositions : prix fictifs, temps actif, difficulté, variété et familles. |
| `skills/meal-binder/data/presets/` | Préréglages composables et validés. |
| `evals/` | Profils de test et score par modèle. |
| `tools/` | Build du prompt monolithique, détection de données personnelles. |
| `dist/prompt.md` | Version monolithique **générée** : ne pas l'éditer. |
| `CHANGELOG.md` | Corrections et changements de comportement. |

Contrôles automatiques : protéines et poids par portion, durées totale et active, difficulté déclarée, matériel, répartition végétarien/poisson/viande, quantité et alternance des légumineuses, riz, féculents distincts, répétition des plats et ingrédients principaux, variété des techniques, crucifères et ALA (optionnels), espèces de poisson uniques, fer + vitamine C, sel avec fromages salés, aliments, familles et cuisines exclus, fraîcheur selon le jour de consommation, emballages, stock suivi semaine par semaine, budget.

Non contrôlé par script : authenticité, saison, labels des produits réels, goût et cohérence sémantique des étapes en texte libre. Les quantités de fer et de vitamine C ne sont pas calculées : le contrôle détecte la présence d'aliments tagués. Les rendements et les durées restent des estimations déclarées.

## Conventions et contrôles

- Les quantités d'ingrédients sont strictement positives, dans l'état de référence de l'aliment. Un ingrédient à quantité nulle doit être retiré. Le stock peut valoir `0` (vide) ou `null` (quantité inconnue).
- Besoin et stock sont exprimés en **forme comestible de référence**, avant cuisson. Un bloc `achat` décrit son équivalent brut : le stock est déduit avant conversion. Prix et conditionnements du produit brut se renseignent dans ce bloc ; ceux des filets ne sont pas réutilisés pour un poisson entier.
- `report_ok=0` empêche le report intersemaine des restes achetés **et du stock initial**. Un achat différé doit donc être prévu pour les semaines suivantes.
- `analyse()` calcule les mêmes écarts pour `check-week`, `check-all`, `render`, `audit` et `evals/score.py`. Un budget dépassé est une erreur s'il est impératif, une alerte s'il est préférentiel. Un budget incomplet reste explicitement non vérifié.
- `--json` écrit une liste d'écarts seule sur stdout pour les contrôles, le rendu et l'audit. `show-profile` renvoie un objet `profil`/`origines`/`ecarts` ; `list-presets` et `list-options` renvoient leurs catalogues ; `select` renvoie son rapport. Codes de sortie : `0` sans erreur détectée (ou sélection réussie), `1` données non conformes (ou aucune proposition admissible), `2` entrée illisible/manquante ou sortie protégée, `3` panne interne. **Le code 0 n'atteste pas les points signalés non vérifiés.** Les fichiers de diagnostic peuvent être rendus malgré des erreurs de conformité.

Les schémas déclaratifs sont centralisés dans `skills/meal-binder/scripts/schemas.py` ; les règles métier dans `checks.py` ; les conversions dans `core.py` ; le stock, les emballages et le budget dans `shopping.py`. Aucune dépendance ajoutée. Voir les [formats et conventions détaillés](skills/meal-binder/references/recipe-format.md).

## Données nutritionnelles

`skills/meal-binder/data/foods.csv` contient des **valeurs provisoires** (`source=placeholder`). Tant qu'elles restent, l'audit classe la nutrition en « estimation ».

Pour les remplacer par la table Ciqual de l'Anses (diffusée en open data ; vérifier la licence de la version téléchargée et citer la source) :

1. Télécharger la table depuis le site Ciqual.
2. Renseigner les codes dans `data/ciqual_map.csv`, en respectant l'état de pesée (cru, sec, égoutté…).
3. `python skills/meal-binder/scripts/build_foods.py --ciqual <fichier>`

Vos produits précis (étiquette, prix) : `foods.local.csv` dans votre dossier de travail.

## Vie privée

Le profil contient des données personnelles : objectifs, santé, stock, zone d'achat. Elles restent dans votre dossier de travail.

- `profile.yaml`, `pantry.yaml`, `stores.yaml`, `plan.yaml`, `foods.local.csv`, `weeks/`, `propositions/` et `out/` sont ignorés par git dans tous les dossiers (ex. `mon-classeur/`), sauf sous `examples/`.
- `meal-setup` demande une zone (ville ou code postal), jamais une adresse.
- Avant de publier un fork : créer `.privacy-patterns` (ignoré par git) avec vos mots sensibles, puis `python tools/check_privacy.py`.

## Évaluer un modèle

Voir [`evals/README.md`](evals/README.md). Le taux local de recettes sans erreur est séparé du score global : une erreur globale ou un plafond budgétaire impératif invérifiable ramène le score à zéro. Les préférences non satisfaites sont décomptées séparément.

## Tests

Les [parcours professionnels](skills/meal-binder/references/professional.md)
documentent les diagnostics structurés et la protection des sorties.

```bash
python -m unittest discover tests
python tools/check_demo.py
```

## Avertissement

Outil de planification, pas un avis médical ni diététique. Les régimes sont contrôlés selon les natures déclarées dans la base d'aliments ; cela ne garantit ni les allergènes, ni les traces, ni les certifications des produits. Les contraintes et cibles sont des choix du profil.

## Licence

MIT, voir [LICENSE](LICENSE).
