# Exemple : budget ou temps actif

Profil public fictif : une semaine, deux préparations de deux portions, régime végétarien, difficulté facile, au plus 20 minutes actives et 40 minutes totales par recette, soja exclu, deux plats distincts. Le stock initial comprend 100 ml d'huile d'olive et deux citrons en équivalent jus.

**Les prix de `foods.local.csv` sont fictifs et servent seulement à vérifier le fonctionnement. Ils ne proviennent d'aucun magasin.** Les apports de la base restent provisoires et la nutrition est désactivée dans cet exemple. Les durées et les niveaux de difficulté sont estimés à partir des déclarations.

Depuis la racine du dépôt :

```bash
python skills/meal-binder/scripts/binder.py check-profile --dir examples/adaptation
python skills/meal-binder/scripts/binder.py select --dir examples/adaptation
python skills/meal-binder/scripts/binder.py check-all --dir examples/adaptation/out/selection
```

| Proposition | Recettes | Caisse fictive | Actif total | Décision initiale |
|---|---|---:|---:|---|
| `economique` | Lentilles aux carottes ; omelette aux pommes de terre | 6,24 EUR | 40 min | Retenue : budget prioritaire. |
| `rapide` | Boulgour aux champignons ; salade de pois chiches et œufs | 12,02 EUR | 30 min | Admissible, plus rapide mais plus chère. |
| `avec_soja` | Lentilles aux carottes et miso ; omelette aux pommes de terre | 6,48 EUR | 40 min | Rejetée : le miso appartient à la famille soja exclue. |

Les deux propositions admissibles n'ont aucun écart préférentiel ; difficulté maximale facile et deux plats distincts pour chacune. Le choix est donc expliqué par le premier critère qui les départage, le montant caisse. Les achats sont calculés avec les emballages et le stock commun, indépendamment pour chaque proposition.

Consulter [rapport.md](out/selection/rapport.md) et le [classeur retenu](out/selection/out/classeur.md). La copie sélectionnée inclut les données nécessaires à `check-all`, `render` et `audit` avec la même version du dépôt.

Pour privilégier le temps, modifier uniquement ce bloc de `profile.yaml`, puis relancer `select` :

```yaml
selection:
  priorites: [temps_actif, budget, difficulte, variete]
```

`rapide` devient le choix retenu : 30 minutes actives contre 40. Aucune quantité ni exigence n'a besoin de changer. Revenir à `[budget, temps_actif, difficulte, variete]` pour retrouver la sortie livrée.

Pour essayer une préférence, abaisser `repas.duree_active_max_min` à 15 et ajouter `exigences.duree_active: preference`. La proposition économique reste admissible mais porte deux écarts ; la rapide gagne alors avant le départage budgétaire. Avec la même limite impérative, l'économique est rejetée.

L'absence de candidat admissible produit un rapport de rejet et retire l'ancien classeur de la sortie générée, sans effacer les propositions sources. Aucun optimum n'est revendiqué au-delà de ces trois propositions.
