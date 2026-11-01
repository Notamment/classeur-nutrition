# Quantités liées aux ingrédients

Exemple technique fictif, sans validation culinaire ni nutritionnelle. Deux
lignes du même aliment ont des identifiants distincts : `sauce` et `garniture`.
Les valeurs nutritionnelles et prix de la base ne sont pas validés par cet exemple.

```bash
python skills/meal-binder/scripts/binder.py render --dir examples/etapes_liees
```

Le document `out/classeur.md` affiche 50 g pour la sauce, 150 g pour la garniture
et 10 ml d'huile. Les étapes JSON gardent leurs références.

Pour tester sans modifier l'exemple public, le dupliquer dans un dossier privé :

```bash
classeur-nutrition clone --source examples/etapes_liees --dir dossiers/essai_etapes
classeur-nutrition scale --dir dossiers/essai_etapes --portions 4 --apply
classeur-nutrition render --dir dossiers/essai_etapes
```

Les étapes affichent alors 100 g, 300 g et 20 ml ; la durée reste 12 minutes.
Un rendu n'est pas une revue humaine et ne permet pas une livraison sans revue.
Cet exemple ne répartit pas une même ligne en fractions entre plusieurs étapes :
déclarer des lignes séparées pour représenter des quantités distinctes.
