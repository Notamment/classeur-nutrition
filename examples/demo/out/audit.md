# Audit — CLASSEUR DÉMO — POLOGNE

Généré le 2026-10-18 par meal-binder. Classeur non réécrit.

## Index global

| Semaine | ID | Recette | Catégorie | Prot./portion | Féculent principal | Légumineuses | Soja |
|---|---|---|---|---:|---|---|---|
| S01 Pologne | S01-R02 | Kasza gryczana z sosem grzybowym i jajkiem sadzonym | végétarien | 35 g | sarrasin | non | non |
| S01 Pologne | S01-R05 | Pyry z gzikiem | végétarien | 34 g | pomme de terre | non | non |
| S01 Pologne | S01-R01 | Śledź w śmietanie z jabłkiem i ziemniakami | poisson | 37 g | pomme de terre | non | non |
| S01 Pologne | S01-R03 | Pierogi leniwe z surówką z marchewki i jabłka | végétarien | 37 g | blé | non | non |
| S01 Pologne | S01-R04 | Kotlety jajeczne z buraczkami zasmażanymi i ziemniakami | végétarien | 35 g | pomme de terre | non | non |

## Hypothèses et éléments non vérifiés

- Valeurs nutritionnelles **provisoires** (`source=placeholder`) : Aneth, Betterave cuite sous vide, Beurre doux, Carotte, Champignons de Paris, Chapelure, Chou blanc, Ciboulette, Citron (jus), Cornichons malossol, Cottage cheese, Crème fraîche 15 %, Farine de blé T65, Filets de hareng doux marinés, Huile neutre, Oignon jaune, Pomme acidulée, Pomme de terre, Radis, Sarrasin grillé (kasza gryczana), Skyr nature, Sucre, Œuf calibre M. Remplacer par Ciqual ou l'étiquette (`build_foods.py`).
- Poids servis : estimés avec les rendements de `foods.csv` ou de la recette ; non pesés.
- Labels, origine, transport et disponibilité : exigences affichées, produits réels non vérifiés.
- Stock présent, quantité inconnue : Beurre doux, Huile neutre, Poivre noir moulu.
- Prix de référence manquants (23) : budget incomplet.
- Déductions de stock valables pour la première rotation uniquement.

## Audit final

| Contrôle | Attendu | Résultat | Statut |
|---|---|---|---|
| Validité des données | schémas, unités et références valides | écarts : aucune | conforme |
| Semaines, recettes, portions | 1 × 5 × 2 | 1 sem., 5 recettes | conforme |
| Répartition végétarien / poisson / viande | 4 / 1 / 0 | 4 / 1 / 0 | conforme |
| Protéines et poids servi | [32, 40] g ; [450, 580] g | prot. 34–37 g ; poids 480–620 g ; exceptions : S01-R01, S01-R02, S01-R04 | non conforme |
| Légumineuses : quantité et alternance | [80, 120] g cuits ; non consécutives | 0 recettes ; écarts : aucune | conforme |
| Temps et équipement | ≤ 45 min ; plaque, airfryer, blender | max déclaré 50 min ; écarts : S01-R01 | non conforme |
| Riz, féculents, substituts | riz ≤ 2/sem. ; ≥ 3 féculents ; substituts ≤ 1 | écarts : aucune | conforme |
| Cuisines et authenticité | distinctes, non exclues, plats nommés | Pologne ; 5 adaptation(s) déclarée(s) | non vérifié |
| Saison et conservation | produits de saison ; fragiles en début de semaine | fragiles tardifs : S01-R01, S01-R04 | non vérifié |
| Labels, sel, fer + vitamine C, exclusions | règles du profil | écarts : S01-R05 ; labels des produits réels non vérifiés | non conforme |
| Courses et stock | besoins comestibles ; achats bruts ; stock suivi | 3 stock(s) à vérifier ; écarts : aucune | estimation |
| Budget | montant caisse ; plafond non fixé EUR | 23 prix manquant(s) ; dépassements : aucune | non vérifié |
| Sources et méthode | Ciqual / étiquettes ; contrôle automatisé | binder.py ; données provisoires : oui | estimation |

**Écarts** — 5 erreur(s), 6 alerte(s).

- erreur · S01-R01 · poids_servi — 588 g/portion hors [450, 580] (estimation)
- erreur · S01-R01 · duree — 50 min > 45 min
- erreur · S01-R02 · poids_servi — 622 g/portion hors [450, 580] (estimation)
- erreur · S01-R04 · poids_servi — 592 g/portion hors [450, 580] (estimation)
- erreur · S01-R05 · fer_vitc — source de fer absente
- alerte · S01-R01 · alternative_a_ajuster — Maquereau fumé : poids servi hors plage, ajuster avant substitution
- alerte · S01-R01 · alternative_a_ajuster — Truite (filets) : protéines hors plage, ajuster avant substitution
- alerte · S01-R01 · fragile — jour 3 : Aneth — achat différé ou recette plus tôt
- alerte · S01-R04 · fragile — jour 5 : Aneth — achat différé ou recette plus tôt
- alerte · S01 · donnees_provisoires — 23 aliment(s) aux valeurs provisoires : nutrition = estimation non vérifiée
- alerte · S01 · budget_non_verifie — 23 prix manquant(s); 2 stock(s) de quantité inconnue
