# Parcours professionnels

Les profils v1, sans version et v2 gardent leurs défauts et leurs règles.

## Diagnostics structurés

Les diagnostics JSON conservent `level`, `code`, `where`, `msg` et ajoutent :

| Champ | Valeurs | Usage |
|---|---|---|
| `kind` | `violation`, `unknown`, `information`, `internal` | Nature du résultat, indépendante de la langue du message. |
| `requirement` | `imperative`, `preference`, `null` | Politique applicable ; aucune interdiction alimentaire déclassée. |

Le compteur de préférences et l'audit utilisent ces champs, pas le texte français.
Le rapport de sélection passe à `version: 2` ; son ordre de classement est inchangé.

## Protection des sorties

Le rendu et l'audit écrivent en UTF-8/LF par remplacement atomique. Un document
préexistant non reconnu comme un rendu de meal-binder est protégé. Les liens
symboliques de sortie sont refusés. Une sélection remplace seulement une sortie
portant son marqueur `GENERATED`. Si remplacement et restauration échouent,
la sauvegarde `.selection-backup-*` est conservée dans `out/` pour récupération.

Un code de sortie 0 ne signifie toujours pas que les informations non vérifiées
sont validées. Les calculs et les appréciations humaines doivent rester distincts.

## Reproductibilité et archives privées

```bash
python skills/meal-binder/scripts/binder.py diagnose --dir mon-classeur --json
python skills/meal-binder/scripts/binder.py render --dir mon-classeur --date 2026-01-02
python skills/meal-binder/scripts/binder.py snapshot --dir mon-classeur --output ../archive-classeur --date 2026-01-02
python skills/meal-binder/scripts/binder.py verify-snapshot --dir ../archive-classeur
```

`diagnose` fournit un rapport JSON `version: 2`. Le rendu et l'audit ajoutent
`out/manifest.json` : date, profil effectif, empreintes SHA-256 des entrées,
des scripts et des catalogues, empreinte des résultats. `--date` fixe la date
du rendu et du manifeste ; sans option, la date du jour est utilisée.

Une archive est créée uniquement dans un dossier nouveau extérieur aux entrées.
Elle contient les entrées déclarées, les résultats et le moteur sous `.runtime/`.
Elle est **privée** : elle peut contenir profil, stock, tarifs et magasins.
Les autres notes et les propositions non retenues ne sont pas copiées.

`verify-snapshot` contrôle les empreintes, inventaires et résultats recalculés.
Un fichier modifié, une entrée ajoutée ou un moteur différent donne le code 1,
avec les différences ; le code 0 signifie intégrité et reproduction des calculs,
pas conformité de toutes les contraintes. La commande n'exécute jamais le code
archivé. Après revue de la confiance dans une archive, on peut utiliser
explicitement son `.runtime/meal-binder/scripts/binder.py` avec le même Python
et PyYAML pour reprendre une version ancienne.

Le manifeste assure la détection de modifications par rapport à ses empreintes,
pas une signature cryptographique d'auteur ni une certification des données.

## Données nutritionnelles sourcées

Le [jeu optionnel Ciqual 2025](../data/ciqual2025/README.md) couvre 16 aliments
avec six métriques par aliment, les codes, noms, édition et licence de source.
Il s'active par `use-data --edition ciqual2025 --dir <dir>`, sans écraser un
registre existant. Les aliments non couverts restent explicitement inconnus.

`provenance.yaml` est un registre local `version: 1`, avec un objet `aliments`
indexé par identifiant. Chaque entrée renseigne `source`, `edition`, `date`,
`licence`, `etat_ref` et `nutriments`. Chaque mesure donne `statut`
(`exact`, `borne`, `traces`, `absent`), `unite`, `minimum`, `maximum`.
Une valeur exacte possède deux bornes égales. Une trace a une borne inférieure
nulle et une borne supérieure inconnue ; elle ne vaut jamais exactement zéro.

`nutrients --dir <dir>` rend les intervalles par portion et les aliments sans
données. Les cibles historiques protéines/kcal utilisent uniquement les valeurs
exactes ; une mesure bornée ou absente reste invérifiable. Les autres nutriments
sont informatifs, sans objectifs implicites. Aucun besoin journalier n'est déduit.

L'import `build_foods.py` exige une URL source, une édition, une licence et une
date via `--source`, `--source-version`, `--license`, `--retrieved-on` hors
simulation `--dry-run`. Il refuse doublons, lignes tronquées et nombres invalides,
et écrit CSV et registre en transaction. Les correspondances restent à relire :
le script ne choisit pas un code Ciqual ni un état de pesée à la place de l'utilisateur.

## Produits, tarifs et compositions

`products.yaml` est facultatif, `version: 1`. Il contient `date_reference`
(date choisie pour l'analyse), `validite_jours` et un objet `produits` indexé
par identifiant d'aliment. La date est fixée dans le fichier pour rendre une
analyse reproductible ; l'actualiser explicitement pour une nouvelle commande.

Chaque produit renseigne `reference`, `fournisseur`, `source`, `observe_le`,
`prix_eur` (nullable), `prix_pour`, `unite` (`g`, `ml`, `piece`, identique à
l'unité d'achat de l'aliment), `conditionnements` et `composition`.
Par exemple, 2 EUR pour 500 g donnent 4 EUR/kg ; les achats restent arrondis
aux emballages après déduction du stock. Les prix de formes brutes déclarées
dans les recettes restent séparés de ce prix du produit de référence.

Une date future est refusée. Un prix périmé devient inconnu, sans réutilisation
du prix CSV antérieur ; un plafond impératif invérifiable interdit la sélection.
`products --dir <dir>` expose source, prix normalisé et état de fraîcheur du tarif.
Le classeur et l'audit affichent les références des produits utilisés.

La composition indique `statut` (`documentee`, `inconnue`), `familles`,
`allergenes_presents`, `traces_declarees`. Les familles documentées complètent
les tags culinaires. Une composition explicitement inconnue ne peut pas valider
une exclusion par famille : erreur impérative ou préférence invérifiable selon
la demande. Les informations d'allergènes sont conservées séparément ; elles
ne constituent pas un moteur de certification d'allergènes ou de traces.

## Dossiers, journal et revue humaine

Les commandes suivantes rendent un objet JSON `version: 1` :

```bash
python skills/meal-binder/scripts/binder.py init --dir dossiers/client_001 --id client_001 --profession nutrition
python skills/meal-binder/scripts/binder.py clone --source dossiers/client_001 --dir dossiers/client_002 --id client_002
python skills/meal-binder/scripts/binder.py render --dir dossiers/client_001
python skills/meal-binder/scripts/binder.py review --dir dossiers/client_001 --reviewer relecteur_001 --note "Recettes et limites relues."
python skills/meal-binder/scripts/binder.py review-status --dir dossiers/client_001
python skills/meal-binder/scripts/binder.py history --dir dossiers/client_001
python skills/meal-binder/scripts/binder.py archive --dir dossiers/client_001 --output archives/client_001_v1
```

`init` crée un profil v2 neutre ; l'agent complète ensuite le profil et les semaines.
Les dossiers sont locaux et privés, identifiés par pseudonymes ; aucun fichier
de client ne doit être publié. Dans le checkout Git, la création est limitée
aux dossiers ignorés `dossiers/` et `archives/`. À l'extérieur, choisir un emplacement
privé approprié. Une cible existante n'est jamais remplacée. `clone` ne copie
ni les anciennes revues, ni le journal, ni les notes non déclarées comme entrées.

`professional.yaml` conserve seulement l'identifiant et le métier. `history.jsonl`
conserve les opérations de création et de revue. Le fichier `.dossier.lock`
empêche les opérations concurrentes de ce workflow. Ne retirer un verrou abandonné
qu'après vérification de l'absence du processus qui l'a créé.

Une revue référence les entrées, le moteur, les calculs et le document exact.
Le rendu doit être à jour ; erreurs et budget impératif invérifiable empêchent
la décision `revu`. Pour conserver un constat sans validation, utiliser
`--decision a_revoir`. Les alertes restent attachées à la revue ; elles ne sont
pas effacées. Toute modification invalide la revue précédente. Le code 0 de
`review-status` signifie que la revue porte sur la version actuelle ; consulter
sa `decision` pour distinguer `revu` et `a_revoir`.

La revue est une annotation locale déclarative, pas une signature d'identité.
L'archive protège également les empreintes du journal et de la revue présents.
Aucune donnée client ni note n'est transmise à un service par ces commandes.

## Adapter et réutiliser les recettes

```bash
classeur-nutrition scale --dir dossiers/client_001 --portions 4
classeur-nutrition scale --dir dossiers/client_001 --portions 4 --apply
classeur-nutrition lock-recipe --dir dossiers/client_001 --recipe S01-R01
classeur-nutrition unlock-recipe --dir dossiers/client_001 --recipe S01-R01
classeur-nutrition save-recipe --dir dossiers/client_001 --recipe S01-R01 --name plat_revu
classeur-nutrition favorite --dir dossiers/client_001 --name plat_revu --value oui
classeur-nutrition library --dir dossiers/client_001
classeur-nutrition replace --dir dossiers/client_001 --recipe S01-R01 --from-file dossiers/client_001/bibliotheque/plat_revu.json
```

`scale` et `replace` rendent un aperçu avant/après ; seul `--apply` écrit les
entrées et le journal en transaction, après les mêmes calculs et contrôles.
Une erreur impérative ou un budget impératif invérifiable empêche l'application.
Les préférences et données manquantes restent dans le rapport. Le stock n'est
pas multiplié : les achats sont recalculés après déduction du stock réel.

Le redimensionnement porte sur toutes les recettes et le nombre global de
portions du profil historique. Un verrou de recette bloque tout redimensionnement
global et son remplacement. Le remplacement conserve l'identifiant de destination ;
un fichier recette simple exige `--source-portions`, une entrée de bibliothèque
fournit ce nombre. Les métadonnées calculées du plan sont resynchronisées.
Les quantités, formes brutes et eau retenue sont proportionnées ; durées, gestes,
matériel et conservation nécessitent une nouvelle relecture. Le moteur n'invente
pas de nouvelle instruction de cuisson. Une ancienne revue devient obsolète :
refaire le rendu puis la revue.

L'ajout à `bibliotheque/` exige une revue humaine actuelle avec décision `revu`.
La bibliothèque et `locks.yaml` restent privés et ignorés par Git. Une recette
revue dans un dossier ne possède aucune validation transférable à un autre profil.
Les favoris servent au rangement ; ils n'annulent aucune contrainte.

## Exports client et production

```bash
classeur-nutrition export --dir dossiers/client_001 --audience client --format html --format csv
classeur-nutrition export --dir dossiers/client_001 --audience production --format html
classeur-nutrition export --dir dossiers/client_001 --audience client --format pdf
```

Les fichiers restent sous `out/exports/<public>/`. Une livraison exige une revue
humaine actuelle avec décision `revu`. `--draft` permet un aperçu explicitement
marqué « BROUILLON — NON VALIDÉ », en conservant les écarts. Le manifeste minimal
livrable contient version, date et empreintes ; il omet profil, notes et pseudonymes.
Les exports client contiennent recettes, consignes, sources et codes des limites.
Les exports production ajoutent courses, stock mobilisé, sous-totaux et diagnostics
détaillés. Relire les textes libres des recettes avant toute transmission.

Le HTML est autonome, échappe le texte libre et propose une mise en page imprimable.
Les CSV sont en UTF-8 avec BOM, avec cellules de texte protégées contre les formules
de tableur. Le PDF exige `pip install '.[exports]'` et les dépendances système de
WeasyPrint ; aucune ressource externe n'est chargée par le générateur. On peut
également imprimer le HTML en PDF depuis un navigateur. Pour remplacer un export,
garder les mêmes formats ou archiver préalablement l'ancien dossier : un ancien
fichier ne doit pas être confondu avec une version courante.

## Installation et mises à jour

`python -m pip install .` installe la commande `classeur-nutrition`, utilisable
hors du checkout. `python -m classeur_nutrition` fonctionne aussi depuis les
sources. `doctor` vérifie Python, PyYAML et la présence des données embarquées,
sans connexion réseau ni accès aux dossiers clients. `--version` affiche la
version du moteur. Les scripts historiques restent utilisables directement.

Avant mise à jour, créer une archive privée et vérifier sa reproduction. Une
nouvelle version ne modifie pas automatiquement les profils ni les recettes ;
ses empreintes différentes invalident les revues précédentes. Aucune migration
silencieuse ni publication de données n'est effectuée par l'installation.
