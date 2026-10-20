# Adaptation du classeur — étape 2 — 20 octobre 2026

## Fonctionnalités

- Options v2 facultatives pour difficulté, temps actif, plats distincts, répétitions, ingrédients principaux récurrents et techniques variées.
- Difficulté estimée depuis un catalogue de techniques et les tâches simultanées, avec raisons visibles ; données absentes distinguées des limites dépassées.
- Familles d'ingrédients exclues ou à éviter, héritage des familles parentes et tags explicites pour les produits composites ; contrôle des alternatives poisson inclus.
- Commandes `list-options` et `select`. Comparaison de 1 à 30 classeurs complets : impératifs, nombre d'écarts préférentiels, puis priorités ordonnées budget/temps/difficulté/variété.
- Budget fondé sur le montant caisse calculé avec stock, emballages et reports ; plafond conservé par semaine. Un budget impératif invérifiable interdit la sélection.
- Rapports Markdown et JSON expliquant rejets et premier critère décisif ; copie du classeur retenu et de ses données, sans modification des sources.
- Remplacement atomique des sorties générées ; absence de gagnant explicite et protection des dossiers non reconnus.
- Décompte partagé sélection/évaluation : `preferences_non_satisfaites` compte les violations connues par règle et portée ; nouveau champ `preferences_non_verifiables`. Les données inconnues ne sont plus incluses dans le premier compteur.
- Documentation, modèles, skills et prompt monolithique alignés ; catalogues embarqués depuis leur source. Exemple de trois propositions à prix fictifs.

## Vérification et compatibilité

142 tests passent sous Python 3.12 : 95 conservés, 42 issus de l'étape 2 et 5 régressions d'intégration (défauts neutres, achats bruts après stock, reports, stock inconnu et confidentialité des propositions). Profils v1 et v2 antérieurs, exemples généralistes et écarts intentionnels de la démo conservés. Base d'aliments, moteur de conversion, calcul des achats et quantités historiques inchangés.

Les adaptations UTF-8 Windows, la CI Ubuntu/Windows sur Python 3.10/3.13 et les fins de ligne LF sont préservées. Les propositions privées sont ignorées par Git à tous les niveaux, avec une exception pour les exemples publics fictifs.

La sélection compare l'ensemble fourni ; elle ne génère pas les recettes et ne garantit pas un optimum global. Les métadonnées sont déclaratives, les familles ne certifient ni allergènes ni traces et les prix de démonstration n'ont pas de valeur commerciale.

---

# Généralisation du produit — étape 1 — 18 octobre 2026

## Fonctionnalités

- Profil v2 aux défauts neutres, profils v1 et sans version compatibles.
- Six préréglages combinables en YAML ; priorité aux valeurs explicites, conflits détectés, provenance par champ.
- Commandes `list-presets` et `show-profile`, sorties structurées documentées.
- Nutrition désactivée, informative ou avec cibles ; métriques absentes inconnues, jamais zéro. Poids, conversions et achats indépendants du mode.
- Contraintes impératives et préférences visibles dans les contrôles, le rendu, l'audit et les évaluations. Intégrité des données, exclusions et régime toujours stricts.
- Régimes libre, végétarien, végétalien et pescetarien ; ingrédients exclus ou à éviter distincts.
- Organisation libre, par cuisine ou par thème ; authenticité facultative ; catégorie mixte viande + poisson en v2.
- Documentation, consignes des deux skills et prompt monolithique alignés. Le prompt embarque les défauts et les préréglages générés depuis leur source.
- Trois exemples complets : famille sans nutrition, végétarien rapide à budget préférentiel, objectifs protéiques avec gamelles.

## Vérification

94 tests passent : 58 tests existants et 36 nouveaux. Les trois exemples v2 passent profil, résolution, plan, semaine, classeur, rendu et audit. La démo historique conserve exactement ses cinq écarts attendus. Quantités de ses recettes, base d'aliments et profils d'évaluation historiques inchangés.

## Limites de cette étape

Aucun optimiseur pondéré, interface web, réglage de difficulté ou planification avancée du temps actif ajouté. Les recettes sont toujours rédigées par l'agent ; la CLI contrôle et rend les données. Les régimes s'appuient sur les natures déclarées des ingrédients, sans moteur d'allergènes. Prix absents et nutrition provisoire restent signalés.

---

# Consolidation — 18 octobre 2026

## Corrections

- Schémas partagés avant calcul : types, champs obligatoires, nombres finis, quantités, portions, rendements, plages et structures imbriquées. Clés YAML/JSON dupliquées refusées.
- Base d'aliments : en-tête, lignes, identifiants, états, rayons, conditionnements et bornes numériques contrôlés ; remplacement local toujours possible.
- Un même rendement détermine le poids servi et les légumineuses cuites. Les quantités nulles ne peuvent plus satisfaire les contrôles de présence.
- Les achats bruts sont calculés après mobilisation du stock comestible. Prix et emballages du produit brut sont distincts. Les formes incompatibles sont signalées au lieu d'être agrégées silencieusement.
- Les quantités fractionnaires restent visibles. Un stock partiellement inconnu reste inconnu quel que soit l'ordre des lignes. Le stock initial non reportable expire entre semaines.
- Les alternatives poisson utilisent le calculateur de recette ; nature, état et exclusions sont contrôlés. Les écarts nutritionnels sont signalés comme alternatives à ajuster.
- Budget commun à `check-week`, `check-all`, `render`, `audit` et au score. Dépassements bloquants, données manquantes explicitement non vérifiées.
- Sortie `--json` exploitable sur stdout ; codes distincts pour non-conformité, entrée illisible et panne interne. La CI vérifie les écarts attendus de la démo et rejette les exceptions.
- Rendu sans mutation de la liste d'écarts ; ordre invalide signalé avec repli sur l'ordre des recettes pour conserver tous les besoins.
- Démo : retrait des mentions de poivre absentes des ingrédients de R02 et R04. Aucune quantité d'ingrédient modifiée ou inventée.

## Compatibilité

Les entrées précédemment tolérées mais ambiguës sont maintenant rejetées : nombres entre guillemets, quantités d'ingrédients nulles, champs inconnus, emballages fractionnaires, blocs `achat` incomplets. Le stock `0` reste valide et se distingue de `null`.

Le champ `taux` des évaluations intègre maintenant les erreurs globales ; le taux local reste disponible dans `taux_recettes`. Les sorties Markdown distinguent clairement quantités comestibles et achats bruts.

## Limites

La base nutritionnelle reste en `placeholder`, sans prix réel ajouté. Le texte libre des étapes, l'authenticité, les rendements physiques et la saisonnalité ne sont pas automatiquement certifiés. Le test du poivre protège la démo connue ; il ne constitue pas un analyseur général du langage des recettes.
