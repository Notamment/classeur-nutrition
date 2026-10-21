"""Adaptations explicites : aperçu par défaut, contrôles avant transaction."""
from __future__ import annotations

import argparse
import copy
import math
import shutil
import tempfile
from pathlib import Path

import yaml

from checks import analyse, required_budget_unverified
from core import BinderError, DataError, load_json, load_yaml
from manifest import encode, hashes, input_files
from storage import atomic_batch, safe_destination
from workflow import journal, locked, review_status

COMMANDS = {"scale", "replace", "lock-recipe", "unlock-recipe", "save-recipe", "library", "favorite"}


def locks(directory):
    path = safe_destination(Path(directory) / "locks.yaml")
    data = load_yaml(path) if path.exists() else {"version": 1, "recettes": []}
    if data.get("version") != 1 or not isinstance(data.get("recettes"), list) or any(not isinstance(r, str) for r in data["recettes"]):
        raise BinderError("locks.yaml invalide")
    return set(data["recettes"])


def _name(name):
    import re
    if not name or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
        raise BinderError("nom simple requis : lettre minuscule puis lettres, chiffres, _ ou -")
    return name


def _summary(ctx):
    from checks import preference_counts
    known = bool(ctx.shops) and all(s.budget_verifiable for s in ctx.shops)
    return {"budget_caisse": math.fsum(s.montant_caisse for s in ctx.shops) if known else None,
            "preferences": preference_counts(ctx), "ecarts": [i.__dict__ for i in ctx.issues], "planning": ctx.schedule,
            "recettes": {rid: {"proteines_par_portion": c.prot_pp, "kcal_par_portion": c.kcal_pp,
                               "poids_par_portion": c.poids_pp} for rid, c in ctx.calcs.items()}}


def adapt(directory, *, portions=None, recipe_id=None, replacement=None, source_portions=None, apply=False):
    directory = safe_destination(directory)
    with locked(directory):
        before = analyse(directory, complete=True)
        initial = hashes(input_files(directory), directory)
        protected = locks(directory)
        if portions is not None:
            if type(portions) is not int or portions <= 0:
                raise BinderError("nombre entier de portions strictement positif requis")
            if protected:
                raise BinderError("redimensionnement refusé : recettes verrouillées ; déverrouiller explicitement avant modification")
        elif recipe_id is None or replacement is None:
            raise BinderError("remplacement : identifiant et recette source requis")
        elif recipe_id in protected:
            raise BinderError("recette verrouillée : remplacement refusé")
        if portions is None and recipe_id not in before.declared:
            raise BinderError("recette cible introuvable")
        changes = {}
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp)
            for path in input_files(directory):
                target = stage / path.relative_to(directory)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            old_portions = before.profile["projet"]["portions_par_recette"]
            if portions is not None:
                profile = load_yaml(stage / "profile.yaml")
                profile.setdefault("projet", {})["portions_par_recette"] = portions
                changes["profile.yaml"] = yaml.safe_dump(profile, allow_unicode=True, sort_keys=False).encode("utf-8")
                (stage / "profile.yaml").write_bytes(changes["profile.yaml"])
            for path in sorted((stage / "weeks").glob("*.json")):
                week = load_json(path)
                changed = False
                for index, recipe in enumerate(week["recettes"]):
                    if portions is None and recipe["id"] != recipe_id:
                        continue
                    if portions is not None:
                        ratio = portions / old_portions
                        target = copy.deepcopy(recipe)
                    else:
                        if type(source_portions) is not int or source_portions <= 0:
                            raise BinderError("portions de la recette source requises")
                        target = copy.deepcopy(replacement)
                        target["id"] = recipe_id
                        ratio = old_portions / source_portions
                    for line in target.get("ingredients", []):
                        if type(line.get("qte")) not in (int, float):
                            raise BinderError("quantité source invalide")
                        line["qte"] *= ratio
                        if line.get("achat"):
                            line["achat"]["qte"] *= ratio
                    for alternative in target.get("alternatives_poisson", []):
                        alternative["qte"] *= ratio
                        if alternative.get("achat"):
                            alternative["achat"]["qte"] *= ratio
                    if "eau_retenue_g" in target:
                        target["eau_retenue_g"] *= ratio
                    target["adaptation"] = "Adaptation explicite : quantités recalculées ; durées, gestes et matériel à relire."
                    week["recettes"][index] = target
                    changed = True
                if changed:
                    relative = path.relative_to(stage).as_posix()
                    changes[relative] = encode(week).encode("utf-8")
                    path.write_bytes(changes[relative])
            after = analyse(stage, complete=True)
            # Le plan déclaré serait obsolète après remplacement. Le synchroniser depuis les données recalculées.
            plan_path = stage / "plan.yaml"
            if plan_path.exists():
                plan = load_yaml(plan_path)
                for week in plan.get("semaines", []):
                    for entry in week.get("recettes", []):
                        rid = entry["id"]
                        if rid not in after.calcs:
                            continue
                        r, c = after.recipes[rid], after.calcs[rid]
                        entry.update(plat=r["nom"], categorie=c.categorie, legumineuses=bool(c.has_legumes),
                                     feculent=c.starch, soja=bool(c.soja), substitut_industriel=bool(c.industriels))
                        if c.especes_poisson:
                            entry["espece_poisson"] = c.especes_poisson[0]
                        else:
                            entry.pop("espece_poisson", None)
                        for key in ("plat_id", "ingredients_principaux", "execution", "temps_actif_min", "temps_total_min"):
                            if key in r and before.profile["version"] == 2:
                                entry[key] = r[key]
                            else:
                                entry.pop(key, None)
                changes["plan.yaml"] = yaml.safe_dump(plan, allow_unicode=True, sort_keys=False).encode("utf-8")
                from checks import check_plan
                after.issues += check_plan(plan, after.profile)
            blocked = any(i.level == "erreur" for i in after.issues) or required_budget_unverified(after)
            result = {"version": 1, "type": "adaptation", "applique": False, "applicable": not blocked,
                      "avant": _summary(before), "apres": _summary(after), "fichiers": sorted(changes),
                      "relecture_requise": ["durées", "gestes", "matériel", "conservation"],
                      "revue_precedente": "sera invalidée par la modification"}
            if apply:
                if blocked:
                    if any(i.level == "erreur" for i in after.issues):
                        raise DataError(after.issues)
                    raise BinderError("budget impératif invérifiable : appliquer refusé")
                if hashes(input_files(directory), directory) != initial:
                    raise BinderError("entrées modifiées pendant l'aperçu ; modification refusée")
                result["applique"] = True
                path, event = journal(directory, "redimensionnement" if portions is not None else "remplacement", {"fichiers": sorted(changes)})
                atomic_batch({**{directory / name: data for name, data in changes.items()}, path: event})
            return result


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--recipe")
    parser.add_argument("--portions", type=int)
    parser.add_argument("--from-file", type=Path)
    parser.add_argument("--source-portions", type=int)
    parser.add_argument("--name")
    parser.add_argument("--value", choices=("oui", "non"), default="oui")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        args.dir = safe_destination(args.dir)
        if args.command == "scale":
            if args.portions is None: raise BinderError("scale nécessite --portions")
            result = adapt(args.dir, portions=args.portions, apply=args.apply)
        elif args.command == "replace":
            if args.from_file is None: raise BinderError("replace nécessite --from-file")
            source = load_json(args.from_file)
            replacement = source.get("recette", source)
            result = adapt(args.dir, recipe_id=args.recipe, replacement=replacement,
                           source_portions=args.source_portions or source.get("portions"), apply=args.apply)
        elif args.command == "library":
            folder = safe_destination(args.dir / "bibliotheque")
            result = {"version": 1, "recettes": [load_json(safe_destination(p)) for p in sorted(folder.glob("*.json"))]}
        else:
            with locked(args.dir):
                ctx = analyse(args.dir, complete=True)
                if args.command in ("lock-recipe", "unlock-recipe"):
                    if args.recipe not in ctx.declared: raise BinderError("recette introuvable")
                    current = locks(args.dir)
                    current.add(args.recipe) if args.command == "lock-recipe" else current.discard(args.recipe)
                    result = {"version": 1, "recettes": sorted(current)}
                    target = args.dir / "locks.yaml"
                    data = yaml.safe_dump(result).encode("utf-8")
                else:
                    name = _name(args.name)
                    target = safe_destination(args.dir / "bibliotheque" / (name + ".json"))
                    if args.command == "favorite":
                        result = load_json(target); result["favori"] = args.value == "oui"
                    else:
                        status = review_status(args.dir)
                        if not status["revue_actuelle"] or status.get("decision") != "revu":
                            raise BinderError("revue humaine actuelle requise avant ajout à la bibliothèque")
                        if target.exists(): raise BinderError("entrée de bibliothèque existante protégée")
                        if args.recipe not in ctx.recipes: raise BinderError("recette introuvable")
                        result = {"version": 1, "nom": name, "favori": False, "recette": ctx.recipes[args.recipe],
                                  "portions": ctx.profile["projet"]["portions_par_recette"],
                                  "origine": "recette d'un dossier revu ; à recontrôler sous un autre profil"}
                    data = encode(result).encode("utf-8")
                path, event = journal(args.dir, args.command, {"recette": args.recipe, "nom": args.name})
                atomic_batch({target: data, path: event})
        print(encode(result), end="")
        return 0 if result.get("applicable", True) else 1
    except DataError as exc:
        print(encode({"version": 1, "ecarts": [i.__dict__ for i in exc.issues]}), end="")
        return 1
    except (BinderError, OSError, ValueError, KeyError, TypeError) as exc:
        print(encode({"version": 1, "erreur": str(exc)}), end="")
        return 2
