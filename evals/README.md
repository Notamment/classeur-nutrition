# Évaluations

Mesurer, modèle par modèle, la conformité aux contrôles implémentés de `meal-binder`. Le même pipeline calcule les recettes, les courses et le budget pour la CLI et pour l'évaluation.

## Métriques

- `taux_recettes` : recettes calculables sans erreur locale / recettes attendues, plafonné à 100 %. Une recette invalide ne compte pas comme propre.
- `taux` (score principal) : taux local, ramené à zéro en présence d'une erreur globale (semaine, quotas, base d'aliments, budget…) ou d'un plafond budgétaire impératif impossible à vérifier.
- `conforme` : toutes les recettes attendues calculées, aucune erreur locale/globale et aucun plafond budgétaire impératif invérifiable.
- `budget` : non conforme, préférence non satisfaite, non vérifié ou estimation. Des prix fictifs ne doivent jamais être utilisés pour noter une génération réelle.
- `preferences_non_satisfaites` : nombre de règles préférentielles connues comme violées, comptées une fois par règle et portée (recette, semaine ou classeur), séparé de la conformité aux impératifs.
- `preferences_non_verifiables` : préférences actives sans données suffisantes, dont un budget préférentiel incomplet. Une règle déjà connue comme violée à cette portée n'est pas comptée une seconde fois. Même décompte que la sélection ; les détails restent dans l'audit.

Un classeur qui dépasse un budget impératif ne reçoit pas un score de 100 %. Sans prix, le profil historique `budget-omnivore` ne peut pas obtenir de score positif. Les profils sans plafond impératif gardent leur taux, avec budget explicitement non vérifié. Les profils historiques restent en v1 ; les trois dossiers de `examples/generaliste/` démontrent les parcours v2.

## Protocole

1. Pour chaque profil de `profiles/` et chaque modèle testé, créer un dossier de travail :
   ```
   evals/runs/<modèle>/<profil>/
     profile.yaml   ← copie de profiles/<profil>.yaml
     pantry.yaml    ← copie de pantry.yaml
   ```
2. Lancer l'agent (Claude Code, Codex, Gemini CLI, modèle ouvert…) avec les skills installés et la consigne de `TASK.md`, en lui donnant ce dossier.
3. Ne pas corriger les sorties à la main.
4. `python evals/score.py` → tableau dans le terminal et `evals/results.md`.

Pour mesurer la variance : répéter une exécution dans `<profil>-2`, `<profil>-3`…

## Profils

| Profil | Ce qu'il teste |
|---|---|
| `recomposition` | Contraintes complètes : 32–40 g, dominante végétarienne, crucifères, ALA, épices associées aux légumineuses. |
| `vegetarien` | Aucun poisson ni viande ; tofu compté dans l'alternance ; fer végétal + vitamine C. |
| `budget-omnivore` | Plus de viande, légumineuses consécutives autorisées, plafond de budget, labels allégés. |

## Ce que le score ne mesure pas

Goût, authenticité culinaire, réalisme des durées, qualité des étapes et fiabilité externe des données nutritionnelles ou des rendements. `conforme` signifie conforme aux contrôles implémentés, pas validation nutritionnelle. Les relire sur un échantillon, ou ajouter une grille de notation humaine dans `results.md`.

`runs/` est ignoré par git : publier seulement `results.md` et la version du dépôt utilisée.
