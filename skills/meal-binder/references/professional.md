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
