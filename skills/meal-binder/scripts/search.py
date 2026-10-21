"""Recherche déterministe bornée dans une bibliothèque structurée privée."""
from __future__ import annotations

import argparse
import copy
import itertools
import math
import os
import shutil
import tempfile
from pathlib import Path

from checks import analyse, preference_counts, required_budget_unverified
from core import BinderError, DataError, Issue, load_json, load_yaml, schema_issues
from editing import _name, locks
from manifest import digest, encode, hashes, input_files
from planning import scaled
from schemas import FOOD_ID, RECIPE_ID, arr, obj
from selection import LABELS, _measurements, _ranking
from storage import safe_destination
from workflow import locked

FORMAT = obj({"version": {"kind": "integer", "minimum": 1, "values": [1]},
              "emplacements": arr(obj({"id": RECIPE_ID, "choix": arr(FOOD_ID, 1, 20)}, ("id", "choix")), 1, 8)},
             ("version", "emplacements"))


def metrics(row):
    values = row["mesures"]
    return (row["preferences_non_satisfaites"] + row["preferences_non_verifiables"],
            *(math.inf if values[k] is None else -values[k] if k == "variete" else values[k] for k in LABELS))


def dominates(a, b):
    av, bv = metrics(a), metrics(b)
    return all(x <= y for x, y in zip(av, bv)) and any(x < y for x, y in zip(av, bv))


def search(directory, *, max_candidates=100, keep=3, output=None):
    if type(max_candidates) is not int or not 1 <= max_candidates <= 200 or type(keep) is not int or not 1 <= keep <= 10:
        raise BinderError("bornes requises : 1 à 200 essais, 1 à 10 résultats")
    directory = safe_destination(directory)
    target = safe_destination(output or directory / "out/recherche")
    if target.exists() or target == directory or target in directory.parents:
        raise BinderError("destination de recherche nouvelle requise")
    from core import SKILL_DIR
    repository = SKILL_DIR.parent.parent
    if (repository / ".git").exists() and repository in target.parents and (directory / "out") not in target.parents:
        raise BinderError("dans le dépôt, les propositions privées doivent rester sous out/ du dossier")
    with locked(directory):
        baseline = analyse(directory, complete=True)
        if baseline.profile["version"] != 2:
            raise BinderError("recherche disponible avec les profils v2 uniquement")
        initial = hashes(input_files(directory), directory)
        config = safe_destination(directory / "search.yaml")
        config_hash = digest(config.read_bytes())
        data = load_yaml(config)
        errors = schema_issues(data, FORMAT, "search", "schema_recherche")
        if errors:
            raise DataError(errors)
        protected, variables, library_hashes = locks(directory), [], {}
        seen = set()
        for slot in data["emplacements"]:
            rid = slot["id"]
            if rid not in baseline.declared or rid in seen:
                raise BinderError("emplacement introuvable ou répété")
            if rid in protected:
                raise BinderError("emplacement verrouillé : recherche refusée")
            seen.add(rid)
            choices = []
            if len(slot["choix"]) != len(set(slot["choix"])):
                raise BinderError("choix de bibliothèque dupliqué")
            for name in slot["choix"]:
                path = safe_destination(directory / "bibliotheque" / (_name(name) + ".json"))
                library_hashes[name] = digest(path.read_bytes())
                entry = load_json(path)
                if entry.get("version") != 1 or type(entry.get("portions")) is not int or entry["portions"] <= 0 or not isinstance(entry.get("recette"), dict):
                    raise BinderError("entrée de bibliothèque invalide")
                choices.append((name, entry))
            variables.append((rid, choices))
        total = math.prod(len(options) for _, options in variables)
        rows, candidates = [], {}
        for index, combination in enumerate(itertools.islice(itertools.product(*(v[1] for v in variables)), max_candidates), start=1):
            cid = f"essai_{index:04d}"
            weeks = copy.deepcopy(baseline.weeks)
            selected = {rid: entry for (rid, _), (_, entry) in zip(variables, combination)}
            row = {"id": cid, "choix": {rid: name for (rid, _), (name, _) in zip(variables, combination)},
                   "admissible": False, "preferences_non_satisfaites": 0, "preferences_non_verifiables": 0,
                   "mesures": {key: None for key in LABELS}, "ecarts": [], "motifs_rejet": []}
            try:
                for week in weeks:
                    for i, recipe in enumerate(week["recettes"]):
                        rid = recipe["id"]
                        if rid in selected:
                            entry = selected[rid]
                            # Valider les nombres avant de les multiplier.
                            from core import compute_recipe
                            _, invalid = compute_recipe(entry["recette"], baseline.foods, entry["portions"], version=2)
                            if any(issue.level == "erreur" for issue in invalid):
                                raise DataError(invalid)
                            replacement = scaled(entry["recette"], baseline.profile["projet"]["portions_par_recette"] / entry["portions"])
                            replacement["id"] = rid
                            replacement["adaptation"] = "Recette réutilisée : durées, gestes, matériel et conservation à relire sous ce profil."
                            week["recettes"][i] = replacement
                ctx = analyse(directory, complete=True, weeks=weeks)
                row["ecarts"] = [issue.__dict__ for issue in ctx.issues]
                row["motifs_rejet"] = [issue.line() for issue in ctx.issues if issue.level == "erreur"]
                if required_budget_unverified(ctx):
                    row["motifs_rejet"].append("budget impératif invérifiable")
                row["mesures"] = _measurements(ctx)
                row["preferences_non_satisfaites"], row["preferences_non_verifiables"] = preference_counts(ctx)
                row["admissible"] = not row["motifs_rejet"]
                if row["admissible"]:
                    candidates[cid] = weeks
            except DataError as exc:
                row["ecarts"] = [issue.__dict__ for issue in exc.issues]
                row["motifs_rejet"] = [issue.line() for issue in exc.issues]
            rows.append(row)
        admissible = [row for row in rows if row["admissible"]]
        frontier = [row for row in admissible if not any(dominates(other, row) for other in admissible)]
        priorities = baseline.profile["selection"]["priorites"]
        frontier.sort(key=lambda row: _ranking(row, priorities))
        retained = frontier[:keep]
        result = {"version": 1, "type": "recherche_bornee", "combinaisons_possibles": total, "evaluees": len(rows),
                  "tronquee": total > len(rows), "admissibles": len(admissible), "priorites": priorities,
                  "frontiere": [row["id"] for row in frontier], "retenues": [row["id"] for row in retained], "essais": rows,
                  "entrees": initial, "bibliotheque_sha256": library_hashes, "configuration_sha256": config_hash,
                  "methode": ["Énumération déterministe dans l'ordre déclaré, arrêt à la borne d'essais.",
                              "Mêmes contrôles que les propositions de l'agent ; impératifs non compensables.",
                              "Frontière non dominée sur écarts préférentiels, budget, temps actif, difficulté et variété.",
                              "Inconnu classé après connu ; départage par les priorités du profil puis l'identifiant.",
                              "Compromis limités aux combinaisons évaluées ; aucun optimum universel revendiqué.",
                              "Aucune recette inventée ou consigne réécrite ; rendu et nouvelle revue humaine nécessaires."]}
        if hashes(input_files(directory), directory) != initial:
            raise BinderError("entrées modifiées pendant la recherche ; publication refusée")
        if digest(config.read_bytes()) != config_hash:
            raise BinderError("configuration modifiée pendant la recherche ; publication refusée")
        if any(digest((directory / "bibliotheque" / (name + ".json")).read_bytes()) != value for name, value in library_hashes.items()):
            raise BinderError("bibliothèque modifiée pendant la recherche ; publication refusée")
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".recherche-", dir=target.parent))
        try:
            (stage / "rapport.json").write_text(encode(result), encoding="utf-8")
            # Dossier autonome utilisable avec select ; aucune revue transférée.
            for path in input_files(directory):
                destination = stage / path.relative_to(directory)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
            if hashes(input_files(stage), stage) != initial:
                raise BinderError("entrées modifiées pendant la copie ; publication refusée")
            for row in retained:
                for week in candidates[row["id"]]:
                    destination = stage / "propositions" / row["id"] / "weeks" / (week["semaine"] + ".json")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(encode(week), encoding="utf-8")
            os.replace(stage, target)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return result


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["search"])
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-candidates", type=int, default=100)
    parser.add_argument("--keep", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = search(args.dir, max_candidates=args.max_candidates, keep=args.keep, output=args.output)
        print(encode(result), end="")
        return 0 if result["retenues"] else 1
    except DataError as exc:
        print(encode({"version": 1, "ecarts": [i.__dict__ for i in exc.issues]}), end="")
        return 1
    except (BinderError, OSError, ValueError, OverflowError) as exc:
        print(encode({"version": 1, "erreur": str(exc)}), end="")
        return 2
