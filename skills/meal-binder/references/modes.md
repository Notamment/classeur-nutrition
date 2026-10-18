# Modes modifier et auditer

## Modifier

Entrée : dossier de travail existant (`plan.yaml`, `weeks/`), cibles (`S03-R02`, `S03`), changement demandé.

1. Résoudre le profil avec `show-profile`, puis lire les fichiers des semaines ciblées. Conserver leur version et les niveaux d'exigence.
2. Appliquer le changement dans `weeks/SXX.json` ; garder les `id`. Mettre à jour `plan.yaml` si catégorie, féculent ou légumineuses changent. Si le nombre de portions change, redimensionner explicitement les ingrédients : changer le profil seul ne multiplie pas les quantités.
3. `check-plan`, puis `check-week` sur chaque semaine touchée.
4. `render` : courses, stock des semaines suivantes, budget, index et audit sont recalculés automatiquement.
5. Livrer `out/classeur.md` + liste des modifications (≤ 5 lignes).

## Auditer un classeur Markdown existant

Entrée : un classeur rédigé hors de ce skill (Markdown).

1. Si le document est absent ou illisible : le dire précisément. Ne pas le reconstituer de mémoire.
2. Transcrire chaque semaine en `weeks/SXX.json` **sans modifier** recettes ni quantités. Aliment inconnu → `foods.local.csv` (`source=placeholder`).
3. Information manquante (état de pesée, quantité « à la pincée », poids de poisson entier) : transcrire au plus près et lister l'écart.
4. `python scripts/binder.py audit --dir <dir>` → `out/audit.md`.
5. Livrer le rapport : écarts calculés, données manquantes, corrections proposées (recette par recette). Ne pas réécrire le classeur.

## Reprendre une rotation

Le stock de `pantry.yaml` vaut pour la première rotation. Pour une nouvelle rotation : mettre à jour `pantry.yaml` (skill `meal-setup`), puis `render`.
