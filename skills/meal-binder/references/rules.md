# Règles du classeur

## 1. Configuration effective

Appliquer uniquement les options actives du profil résolu. Un nouveau profil v2 est généraliste ; un profil v1 conserve ses valeurs historiques. Aucune cible protéique, répartition, exigence bio, alternance de légumineuses ou cuisine distincte ne doit être inventée.

| Dimension | Paramètre |
|---|---|
| Nombre de semaines, recettes et portions | `projet.*` |
| Organisation libre, cuisines ou thèmes | `projet.organisation` |
| Authenticité documentée ou libre | `projet.authenticite` |
| Nutrition désactivée, information ou cibles | `nutrition.mode` |
| Protéines, kcal et poids servi par portion | `repas.*_par_portion` |
| Durée totale, préparation et repos inclus | `repas.duree_totale_max_min` |
| Temps actif et difficulté estimée, en v2 | `repas.duree_active_max_min` / `repas.difficulte_max` |
| Régime | `alimentation.regime` |
| Quotas par catégorie, facultatifs | `repartition` |
| Quantité et alternance des légumineuses | `legumineuses.*` |
| Riz, féculents, substituts, diversité | `variete.*` |
| Fer + vitamine C en mode cibles | `nutrition.fer_vitamine_c` |
| Interdiction d'ajouter du sel en présence de certains tags | `aliments.sans_sel_ajoute_si` |
| Interdictions strictes / préférences d'ingrédients | `aliments.exclus` / `aliments.a_eviter` |
| Familles strictement exclues / à éviter, en v2 | `aliments.familles_exclues` / `aliments.familles_a_eviter` |
| Appareils disponibles, si renseignés | `materiel` |
| Labels demandés par l'utilisateur | `labels` |
| Plafond de caisse par semaine, facultatif | `budget.plafond_eur_semaine` |
| Niveau de chaque règle configurable | `exigences.<code>` : `imperative` ou `preference` |
| Ordre de départage des propositions, en v2 | `selection.priorites` |

Le script classe tout seul les catégories, légumineuses, soja, féculents, poissons et marqueurs nutritionnels depuis les ingrédients. Ne pas déclarer ces calculs dans les données des recettes.

## 2. Interprétations

- Végétarien : ni viande ni poisson, y compris dérivés renseignés comme tels dans la base. Végétalien : exclure aussi œufs et laitages ; vérifier la composition des produits composites. Pescetarien : exclure la viande. Ne pas déduire une certification ou une absence d'allergènes de cette classification.
- Catégories de répartition exclusives. Une recette viande + poisson est `mixte` en v2 ; elle reste une erreur en v1.
- Légumineuses : masse cuite équivalente par portion. L'alternance porte sur les recettes successives, pas sur dîner et gamelle de la même préparation. Tofu/tempeh n'y participent que si `soja_compte` est vrai. Les tags de la base font référence.
- Légumineuses sèches : expliciter un éventuel trempage la veille, hors durée de la recette ; sinon choisir une forme déjà cuite. Les purées et farines ne dispensent pas du contrôle de quantité équivalente.
- Poids servi : partie mangée après cuisson. Rendements explicites ; eau retenue comptée une seule fois.
- Courses : besoin et stock comestibles, déduction du stock puis conversion en achat brut, puis emballages. Conserver les décimales. Ne jamais remplacer une quantité inconnue par zéro.
- Budget : montant caisse après stock, pour les seules recettes prévues. Prix et stocks inconnus empêchent de le valider ; afficher les sous-totaux comme incomplets. Un dépassement est bloquant seulement si la règle est impérative.
- Nutrition désactivée : ne pas afficher de protéines/kcal ni imposer fer/C. Information : afficher les seules estimations calculables. Cibles : appliquer les limites configurées ; une valeur manquante ne satisfait pas une cible impérative.
- Difficulté v2 : maximum du niveau des techniques du catalogue et de la coordination déclarée (1–2 tâches simultanées : facile ; 3 : intermédiaire ; 4 ou plus : avancée). Donner les raisons du niveau retenu ; ne pas déduire automatiquement le niveau du seul temps total.
- Temps actif : attention nécessaire à une préparation, toutes les portions ensemble, sans compter deux fois les périodes simultanées. Temps total : durée écoulée. Ne pas classer une durée absente comme zéro.
- Variété v2 : identifier les plats avec un `plat_id` stable ; changer le titre ne crée pas un plat distinct. Déclarer un à trois `ingredients_principaux` présents dans la recette et les techniques réellement nécessaires. Appliquer les limites de plats distincts, répétitions, récurrence d'ingrédients principaux et variété de techniques si actives. Les métadonnées absentes rendent ces contrôles invérifiables.
- Familles v2 : utiliser le catalogue et les appartenances renseignées, parents compris. Le soja comprend les condiments identifiés comme tels ; ses familles parentes sont héritées. Ne pas confondre famille culinaire, quota de légumineuses et détection d'allergènes.

## 3. Arbitrages

1. Vérifier le profil et, si renseignée, la somme des quotas avant le plan.
2. Construire l'ordre et le choix des recettes pour satisfaire les impératifs, puis les préférences. En cas d'échec, ajuster quantités, recette, thème/cuisine puis ordre, sans contourner l'authenticité demandée.
3. Ne jamais requalifier silencieusement une règle impérative. Les préférences peuvent rester insatisfaites, avec un écart explicite et sa raison.
4. Ne pas modifier les exigences pour faire passer les tests. Conflit insoluble : livrer le diagnostic et l'ajustement minimal nécessaire.
5. Statuts : conforme, estimation, non vérifié, non conforme, préférence non satisfaite, non demandé. « Aucune erreur » ne valide pas les points non vérifiés.
6. Sans moteur de calcul disponible, signaler que l'audit est manuel, sans prétendre à un contrôle automatisé.
7. Si plusieurs propositions sont comparées : même profil, stock et prix pour toutes. Écarter violations impératives et budgets impératifs invérifiables ; minimiser les écarts préférentiels (un par règle et portée, incertitudes comprises), puis suivre `selection.priorites` : minimiser caisse totale, temps actif total et difficulté maximale, maximiser les plats distincts. Pour chaque critère, l'inconnu suit le connu ; égalité finale départagée par identifiant. Le plafond de budget reste hebdomadaire. Expliquer le critère décisif et limiter toute affirmation d'optimalité aux propositions examinées.

## 4. Achats et ingrédients

Appliquer seulement les labels et origines du profil. Aucun achat bio, œuf labellisé, label poisson ou commerce équitable n'est imposé par défaut en v2. Ne jamais attribuer à un magasin un stock, prix ou label non vérifié. Réutiliser les magasins déjà vérifiés ; ne pas les rechercher à chaque génération sans changement signalé.

Ne pas transformer une préférence d'achat en affirmation sanitaire. Ne pas déduire des interdictions ou bénéfices d'un antécédent médical. Les choix personnels du profil initial peuvent être conservés dans un profil v1 ou explicitement configurés en v2.

## 5. Saison, conservation et gamelles

- Utiliser les mois et la zone renseignés ; sinon indiquer que la saison n'est pas définie. Conserves, surgelés et épicerie restent autorisés, avec leur forme exacte.
- Prévoir les ingrédients fragiles tôt ou en achat différé. Le script signale les jours dépassant `variete.jour_max_fragile` si cette option est active.
- Ne pas exclure les épinards ou les herbes par défaut ; appliquer les exclusions demandées.
- Gamelle seulement si utile à l'usage : service froid ou réchauffage, éléments à séparer, conservation adaptée aux ingrédients et aux conditions réellement disponibles. Ne pas présenter une durée utilisateur comme garantie sanitaire.
- Ne pas supposer un congélateur ou un appareil manquant. Les étapes doivent rester compatibles avec l'équipement et le temps déclarés.

## 6. Portée des contrôles

Les scripts contrôlent les données et règles déclarées, pas le goût, l'authenticité réelle, la saison effective, l'étiquette d'un produit ou la sécurité d'une conservation réelle. Les textes d'étapes demandent une relecture : chaque quantité utilisée doit avoir sa ligne d'ingrédient. Les valeurs nutritionnelles provisoires restent des estimations ; ne jamais conclure à la couverture des besoins journaliers à partir des seuls repas générés.
