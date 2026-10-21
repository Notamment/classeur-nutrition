# Jeu optionnel Ciqual 2025

Source : [table Anses Ciqual 2025, dépôt Zenodo](https://zenodo.org/records/17550133).
Licence du dépôt consulté : CC BY 4.0. Attribution : **Anses. 2025. Table de
composition nutritionnelle des aliments Ciqual.** Édition du 3 novembre 2025,
récupérée le 20 octobre 2026. Empreintes des fichiers d'origine dans `dataset.json`.

`correspondances.csv` documente 16 correspondances génériques et leurs noms
français officiels. `provenance.yaml` conserve protéines, énergie, lipides,
glucides, fibres et sodium pour 100 g comestibles dans l'état renseigné.
Les noms de source « cru » peuvent désigner l'état sec des céréales non cuites ;
le profil conserve son état de pesée historique `sec`. Vérifier les produits
réels, variétés, traitements et égouttages avant utilisation professionnelle.

Les valeurs ne remplacent pas les 77 lignes historiques. Activer explicitement :

```bash
python skills/meal-binder/scripts/binder.py use-data --edition ciqual2025 --dir mon-classeur
python skills/meal-binder/scripts/binder.py nutrients --dir mon-classeur
```

Le fichier local porte `exiger_sources: true` : les 61 aliments non couverts
ne réutilisent pas silencieusement les valeurs provisoires. Leurs apports
deviennent inconnus. Ajouter leurs correspondances ou des données d'étiquetage
sourcées dans le registre local. Les traces et bornes ne sont pas des valeurs
exactes. Le registre est déclaratif, sans validation diététique ni garantie
de correspondance avec un produit vendu.
