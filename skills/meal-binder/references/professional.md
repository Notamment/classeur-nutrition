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
