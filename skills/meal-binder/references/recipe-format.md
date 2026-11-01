# Formats de données

Une seule source de vérité : `plan.yaml` puis `weeks/SXX.json`. Tableaux, courses, budget et audit en sont dérivés par `binder.py`.

La version des formats est déterminée par `profile.yaml.version`. Voir [profils et préréglages](profiles.md). En v2, `cuisine` n'est requis que pour l'organisation `cuisines` ; `theme` est requis pour `themes` ; les deux sont facultatifs en mode `libre`. Dans les recettes v2, `gamelle` est facultatif et `authenticite` n'est exigé qu'en mode `documentee`. Les autres champs obligatoires restent inchangés. Les exemples ci-dessous restent compatibles v1.

## Plan — `<dir>/plan.yaml`

Recettes listées dans l'ordre de consommation de la semaine.

```yaml
semaines:
  - id: S01
    cuisine: Pologne
    recettes:
      - {id: S01-R02, plat: "Kasza gryczana z sosem grzybowym", categorie: vegetarien, feculent: sarrasin, legumineuses: false}
      - {id: S01-R01, plat: "Śledź w śmietanie", categorie: poisson, feculent: pomme_de_terre, legumineuses: false, espece_poisson: hareng}
```

Champs : `id`, `plat`, `categorie` (`vegetarien` | `poisson` | `viande`, et `mixte` en v2), `feculent` (identifiant libre, `riz` compté pour le quota riz), `legumineuses` (bool), optionnels `soja` (bool), `espece_poisson`, `substitut_industriel` (bool).

Le plan sert à valider quotas et alternance avant rédaction. À la rédaction, le script recalcule tout depuis les ingrédients. En v2, le plan et les recettes acceptent aussi `plat_id`, `ingredients_principaux`, `execution`, `temps_actif_min` et `temps_total_min` : voir [adaptation et sélection](adaptation.md). Ces métadonnées sont nécessaires aux limites d'adaptation actives ; elles restent facultatives sinon. La difficulté est calculée, jamais un champ libre à inventer.

## Semaine — `<dir>/weeks/SXX.json`

```json
{
  "semaine": "S01",
  "cuisine": "Pologne",
  "saison": "1–2 lignes : pourquoi cette cuisine en ce mois.",
  "ordre": ["S01-R02", "S01-R05", "S01-R01", "S01-R03", "S01-R04"],
  "recettes": [
    {
      "id": "S01-R01",
      "nom": "Śledź w śmietanie z jabłkiem i ziemniakami",
      "nom_fr": "Hareng à la crème, pomme et pommes de terre",
      "origine": "Pologne",
      "service": "froid",
      "temps_actif_min": 20,
      "temps_total_min": 50,
      "appareils": ["plaque"],
      "motif_ordre": "Hareng ouvert : à consommer tôt",
      "ingredients": [
        {"food": "hareng_marine", "qte": 260, "unite": "g", "etat": "egoutte"},
        {"food": "oignon", "qte": 100, "unite": "g", "etat": "cru"},
        {"food": "champignon_paris", "qte": 350, "unite": "g", "etat": "cru", "rendement": 0.55},
        {"food": "sardine", "qte": 270, "unite": "g", "etat": "cru",
         "achat": {"qte": 550, "unite": "g", "forme": "entières, à lever en filets"}},
        {"food": "poivre", "qte": 1, "unite": "pincee"}
      ],
      "eau_retenue_g": 0,
      "sel_ajoute": true,
      "etapes": ["Étape 1 : action, feu/température, durée, critère de fin.", "…"],
      "authenticite": "1–2 gestes ou ingrédients caractéristiques.",
      "adaptation": null,
      "gamelle": "1 ligne : froid, transport, réchauffage ou service froid, éléments séparés.",
      "alternatives_poisson": [
        {"food": "maquereau_fume", "qte": 260, "unite": "g", "etat": "net", "note": "émietté, sans cuisson"}
      ],
      "references": {"culinaire": "source consultée ou « non consultée »"}
    }
  ]
}
```

### Champs

| Champ | Règle |
|---|---|
| `id` | `SXX-RYY`, stable : ne change pas si la recette change de jour. |
| `ordre` | Tous les `id` une fois. Absent = ordre de `recettes`. |
| `service` | `chaud` · `tiède` · `froid`. |
| `temps_total_min` | Durée réaliste, tout compris. Trempage préalable : le citer dans `etapes`, préfixé « La veille : ». |
| `temps_actif_min` | Durée d'attention par préparation, finie, ≥ 0 et ≤ temps total. Facultative sauf limite active demandée. |
| `plat_id`, `ingredients_principaux`, `execution` | Métadonnées v2 de difficulté et variété ; [formats détaillés](adaptation.md). |
| `appareils` | Sous-ensemble de `profile.yaml › materiel` si renseigné ; `null` en v2 désactive ce contrôle. |
| `ingredients[].food` | Identifiant de `foods.csv` ou `foods.local.csv`. |
| `qte`, `unite` | Pour **toutes** les portions. Nombre fini strictement positif, sans chaîne ni booléen. Unités : `g` `kg` `ml` `cl` `l` `cac` `cas` `piece` `pincee`. Pincées réservées aux épices et au sel, exclues des apports et des marqueurs nutritionnels. |
| `etat` | Doit être égal à `etat_ref` de l'aliment : `cru` `sec` `cuit` `egoutte` `net`. Sinon créer un autre identifiant (ex. `lentille_verte_seche` ≠ `lentille_cuite`). |
| `rendement` | Optionnel, fini et strictement positif. Poids mangé / poids pesé. Remplace la valeur de `foods.csv` pour le poids servi **et les légumineuses cuites**. |
| `achat` | Optionnel. Équivalent brut du besoin comestible, avant déduction du stock ; voir ci-dessous. |
| `eau_retenue_g` | Eau non énergétique retenue après cuisson : nombre fini ≥ 0. Les ingrédients nutritifs d'une sauce ou d'un bouillon doivent aussi figurer dans `ingredients`. |
| `sel_ajoute` | Booléen obligatoire. |
| `adaptation` | Écart à la version canonique, 1 ligne, ou `null`. |
| `alternatives_poisson` | Recettes poisson. Même schéma que les ingrédients, plus `note` facultative. Le script exige un poisson, vérifie son état et recalcule avec la même fonction. Les écarts de protéines, poids ou kcal signalent une alternative à ajuster. |

Ne pas écrire : catégorie, protéines, kcal, poids, légumineuses, fer/vitamine C, féculent. Ils sont calculés.

### Schémas et erreurs d'entrée

`scripts/schemas.py` définit les schémas de profil, plan, semaine, recette, ingrédient, alternative, stock et magasins. Son validateur est spécifique à ces schémas, sans conversion implicite de types. Ce n'est pas un moteur JSON Schema général.

Champs inconnus refusés, sauf catégories personnalisées de `labels` et clés de `references` à valeur textuelle. Les profils partiels sont fusionnés avec les valeurs par défaut avant validation. La racine des fichiers YAML doit être un objet. Les clés dupliquées dans YAML/JSON sont refusées ; les nombres non finis, rendements nuls/négatifs, portions non entières ou nulles et plages inversées sont des erreurs.

Une recette dont les ingrédients ne peuvent pas être calculés n'entre pas partiellement dans les totaux. Les courses et l'audit indiquent alors des données incomplètes. Les durées et les valeurs numériques doivent être des nombres, jamais des chaînes telles que `"45"`.

### Besoin comestible, achat brut et stock

Exemple : `sardine`, 270 g de filets, avec `achat: {qte: 550, unite: g, forme: "entières"}`.

| Stock de filets | Manque comestible | Achat brut avant emballages |
|---:|---:|---:|
| 270 g | 0 g | 0 g |
| 135 g | 135 g | 275 g |
| 0 g | 270 g | 550 g |

Les allocations aux recettes, le besoin et le stock restent en quantité comestible de référence. Le déficit est ensuite multiplié par `achat.qte / quantité comestible` après conversion d'unités. Le brut doit être au moins égal au besoin comestible. Un surplus d'achat est reconverti en quantité comestible avant report éventuel.

Le bloc `achat` exige `qte`, `unite` et `forme`. Il accepte aussi :

- `conditionnements` : liste de tailles entières positives du produit brut, dans l'unité d'achat de l'aliment. Absent ou `[]` = au poids, arrondi à l'unité supérieure.
- `prix_eur` : prix du produit brut par kg, litre ou pièce. Absent ou `null` = non chiffré.

Les prix et emballages de l'aliment de référence ne sont jamais appliqués automatiquement à une autre forme. Pour un même aliment dans une semaine, forme, ratio, prix et conditionnements doivent être cohérents ; sinon le calcul d'achat est bloqué pour cet article. Utiliser des identifiants distincts lorsque les formes diffèrent réellement.

`pantry.yaml` contient la forme et l'état de référence comestibles, pas le poids brut non préparé. `quantite: 0` = stock connu vide ; `null` = stock présent de quantité inconnue. Des lignes de stock connues s'additionnent ; si l'une est inconnue, le total reste inconnu, indépendamment de l'ordre des lignes.

`report_ok=0` exclut tout reste des semaines suivantes, y compris un reste de stock initial. `report_ok=1` permet le report. Ce paramètre est une hypothèse de conservation à renseigner pour le produit réel.

Les besoins affichés conservent les décimales (par exemple 0,5 g), avec 15 chiffres significatifs au maximum pour éviter les artefacts de calcul flottant. Seuls les achats sont arrondis aux conditionnements ou à l'unité supérieure. Pièces et cuillères reposent sur des masses estimées ; une cuillère à café sèche sans densité vaut conventionnellement 2,5 g, une cuillère à soupe 7,5 g.

### Budget et statut de contrôle

Le plafond porte sur le **montant caisse de chaque semaine**, après déduction du stock. Le coût consommé est une valorisation au prix de référence, pas le prix historique du stock.

- Sous-total connu supérieur au plafond : erreur `budget_depasse`, même si d'autres prix manquent ; alerte si `exigences.budget_depasse: preference` en v2.
- Prix manquant, stock non quantifié, petit achat non chiffrable ou courses incomplètes : alerte `budget_non_verifie` ; le montant connu ne constitue pas un total validé.
- Plafond exactement atteint : accepté. Un plafond nul est autorisé et signifie zéro dépense.

Ces écarts sont communs aux contrôles, au rendu, à l'audit et à l'évaluation. Les alternatives poisson ne sont pas ajoutées aux achats du menu principal.

## Base d'aliments — `foods.csv` / `<dir>/foods.local.csv`

`foods.local.csv` complète ou remplace `foods.csv` (même `id` = remplacement). Mêmes colonnes :

| Colonne | Contenu |
|---|---|
| `id` | snake_case ASCII, unique. |
| `nom` | Nom affiché. |
| `rayon` | Voir la liste en fin de section. |
| `nature` | `vegetal` · `laitier` · `oeuf` · `poisson` · `viande` · `autre`. Détermine la catégorie de la recette. |
| `categorie` | Clé de `profile.yaml › labels` (ex. `oeuf`, `poisson_sauvage`, `racine`, `tofu`, `cacao`). Vide = `defaut`. |
| `tags` | Séparés par `|` : `legumineuse`, `soja`, `soja_condiment`, `feculent:<nom>`, `fer`, `fer_vegetal`, `vitc`, `crucifere`, `ala`, `fragile`, `fromage_sale`, `substitut_industriel`, `espece:<nom>`, `famille:<identifiant>` (v2, catalogue requis). |
| `prot_g_100g`, `kcal_100g` | Pour 100 g à l'état `etat_ref`. Vides autorisés dans le CSV. En v2 désactivé : ignorés ; information : total inconnu pour la métrique manquante ; cibles : objectif correspondant invérifiable. En v1, une valeur manquante bloque le calcul de recette. |
| `etat_ref` | État de pesée des valeurs. |
| `g_par_piece` | Masse comestible d'une pièce (œuf, citron…). |
| `densite_g_ml` | Pour les liquides. Vide = 1. |
| `rendement` | Poids mangé / poids pesé par défaut. Vide = 1. |
| `unite_achat` | `g` · `ml` · `piece`. |
| `conditionnements` | Tailles entières strictement positives dans `unite_achat`, séparées par `|` (ex. `6|12`). Vide = vrac / au poids, arrondi à l'unité supérieure. Une taille fractionnaire est refusée, jamais arrondie silencieusement. |
| `report_ok` | Exactement `1` si un reste se garde jusqu'à la semaine suivante, sinon `0`. S'applique aussi au stock initial. |
| `prix_eur` | Prix de référence par kg, litre ou pièce selon `unite_achat`. Vide = non chiffré. |
| `source` | `ciqual:<code>`, `etiquette:<produit>` ou `placeholder`. Tout `placeholder` passe la nutrition en « estimation non vérifiée ». |

Rayons : `Fruits et légumes` · `Herbes fraîches` · `Poissonnerie` · `Boucherie` · `Crèmerie` · `Œufs` · `Produits végétariens` · `Boulangerie` · `Épicerie salée` · `Conserves` · `Huiles et condiments` · `Épices` · `Épicerie sucrée` · `Produits du monde` · `Surgelés`.

Conserver exactement les colonnes du fichier de référence. Un identifiant dupliqué dans un même CSV, une ligne tronquée, un rayon inconnu ou une valeur numérique invalide produit une erreur. Un remplacement entre `foods.csv` et `foods.local.csv` reste autorisé.
