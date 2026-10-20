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
