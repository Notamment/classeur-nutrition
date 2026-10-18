# Authenticité

Appliquer cette référence lorsque `projet.authenticite: documentee` (v2), ou pour un profil v1 historique. En v2 `libre`, les créations et adaptations sont autorisées ; ne pas les présenter comme des traditions attestées. L'organisation par cuisines et l'exigence d'authenticité sont deux choix distincts.

## Règle

Chaque recette est un plat **réel et nommé** de la cuisine traitée :
- nom vernaculaire, translittéré si besoin, + traduction dans `nom_fr` ;
- techniques et assaisonnements du plat traditionnel ;
- régions différentes du pays quand c'est pertinent.

Interdits : fusion inventée, plat « d'inspiration X », assemblage générique rebaptisé, recette occidentalisée présentée comme locale, recette d'une cuisine exclue sous un autre nom.

Un repas peut associer un plat et un accompagnement attestés dans la même cuisine. Tout compte : ingrédients, temps, poids, apports.

## Adaptations

Autorisées si une contrainte l'impose (protéines, sourcing, légumineuses, matériel, gamelle). Les déclarer dans `adaptation`, une ligne :

> Canonique : bœuf haché + tofu soyeux. Ici : champignons + tofu ferme (végétarien, tenue en gamelle).

Ordre de préférence face à une contrainte :
1. Quantités dans les proportions du plat.
2. Accompagnement attesté plus protéiné.
3. Autre plat de la même cuisine.
4. Autre cuisine.

Ajouter un ingrédient étranger au plat (skyr, tofu, poudre) pour le quota protéique : interdit.

## Champs à remplir

- `authenticite` : 1–2 gestes ou ingrédients signature, et le piège technique s'il existe (« paprika hors du feu, sinon amer »).
- `references.culinaire` : source réellement consultée (livre, site d'auteur reconnu, institution) ou « non consultée ». Ne jamais inventer une source.

## Choix des cuisines

- Nationales ou régionales. Exiger des cuisines distinctes seulement si `variete.cuisines_distinctes` est vrai (toujours en v1).
- Adaptées aux mois de `projet` : produits frais disponibles, service chaud/froid cohérent avec la saison.
