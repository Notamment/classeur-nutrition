---
name: meal-binder
description: Génère, modifie ou audite un classeur de recettes personnalisé, libre ou thématique, avec portions configurables, nutrition facultative, courses par rayon, stock, budget et audit. À utiliser pour un plan de repas, un classeur ou sa correction.
---

# Classeur de repas

Le modèle choisit et rédige. `scripts/binder.py` calcule.
Ne jamais écrire à la main : total, somme de courses, protéines, kcal, poids servi, statut de conformité. Ces valeurs sortent du script.

## Prérequis

- Dossier de travail `<dir>` contenant `profile.yaml`. Absent → skill `meal-setup`. `pantry.yaml` et `stores.yaml` sont facultatifs ; leur absence signifie qu'aucun stock ni magasin n'est renseigné.
- Python ≥ 3.10 et `pyyaml`.
- Chemins des scripts relatifs au dossier de ce skill.

## Lire avant d'agir

| Moment | Fichier |
|---|---|
| Avant le plan | `references/profiles.md`, `references/rules.md` |
| Avant de rédiger une recette | `references/recipe-format.md` ; `references/authenticity.md` si authenticité demandée |
| Modifier / auditer | `references/modes.md` |

## Mode générer

1. **Profil et plan.** Lancer `python scripts/binder.py show-profile --dir <dir>` pour lire les valeurs résolues et leur provenance, puis `check-profile`. Corriger les erreurs de configuration avant de générer. Écrire `<dir>/plan.yaml` (format : `recipe-format.md` § Plan). Respecter l'organisation libre/cuisines/thèmes et les options actives. Lancer :
   `python scripts/binder.py check-plan --dir <dir>`
   Corriger jusqu'à 0 erreur. Ne rien rédiger avant.
2. **Semaine par semaine**, dans l'ordre :
   1. Écrire `<dir>/weeks/SXX.json`.
   2. `python scripts/binder.py check-week SXX --dir <dir>`
   3. Corriger les erreurs, puis améliorer les préférences non satisfaites si possible, sans dégrader les contraintes impératives. Ordre : quantités → recette → thème/cuisine → ordre. Après 3 itérations sans résolution, livrer le diagnostic explicite ; ne pas annoncer de conformité.
   4. Aliment absent de la base : l'ajouter à `<dir>/foods.local.csv` avec `source=placeholder`. Ne jamais inventer un code Ciqual ni une valeur d'étiquette. Nutrition désactivée : valeurs nutritionnelles facultatives ; mode information : valeurs manquantes non calculables ; mode cibles : une cible impérative invérifiable reste une erreur.
3. **Rendu.** `python scripts/binder.py render --dir <dir>` → `<dir>/out/classeur.md` (fiches, récaps, courses, stock, budget, index, audit).
4. **Livrer** `classeur.md`. Message final ≤ 3 lignes : erreurs restantes, données provisoires, achats à vérifier.

## Interdits

- En mode authenticité documentée, ajouter un ingrédient étranger au plat traditionnel pour atteindre un quota : changer de recette. En mode libre, ne pas présenter une création comme traditionnelle.
- Relâcher une contrainte sans qu'elle apparaisse dans l'audit.
- Copier les sorties du script dans le JSON des recettes.
- Recopier ce skill ou les règles dans le classeur.
