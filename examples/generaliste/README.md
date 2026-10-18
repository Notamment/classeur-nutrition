# Exemples généralistes

Trois dossiers autonomes, sans données personnelles ni prix inventés. Chaque dossier contient un profil v2, un plan, deux recettes pour une semaine et le rendu correspondant. Les recettes illustrent le fonctionnement du produit ; ce ne sont pas des menus validés par un professionnel.

| Dossier | Portions | Nutrition | Configuration |
|---|---:|---|---|
| `quotidien_famille` | 4 | Désactivée | Organisation libre, sans quotas, temps ni budget imposés. |
| `vegetarien_rapide_budget` | 2 | Information | Végétarien + rapide + petit budget ; plafond personnalisé à 35 EUR, préférentiel ; organisation par thème. |
| `proteines_gamelles` | 2 | Cibles | Recomposition + gamelles ; cibles personnelles historiques, temps maximal 35 min. |

Depuis la racine du dépôt :

```bash
python skills/meal-binder/scripts/binder.py show-profile --dir examples/generaliste/vegetarien_rapide_budget
python skills/meal-binder/scripts/binder.py check-plan --dir examples/generaliste/vegetarien_rapide_budget
python skills/meal-binder/scripts/binder.py render --dir examples/generaliste/vegetarien_rapide_budget
```

Résultat : `out/classeur.md`. Les trois exemples doivent sortir sans erreur bloquante. Les budgets restent **non vérifiés** faute de prix ; les modes nutritionnels affichés restent **estimés** avec la base provisoire. La suite de tests exécute contrôle du profil, résolution, plan, semaine, classeur, rendu et audit sur une copie de chacun des dossiers.
