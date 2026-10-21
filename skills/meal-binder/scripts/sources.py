"""Provenance nutritionnelle optionnelle ; bornes et absences restent distinctes."""
from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

from core import DataError, Issue, SKILL_DIR, load_yaml, schema_issues
from schemas import BOOL, FOOD_ID, STATES, TEXT, arr, enum, nullable, num, obj

UNITS = {"proteines_g": "g", "energie_kcal": "kcal", "lipides_g": "g", "glucides_g": "g",
         "fibres_g": "g", "sodium_mg": "mg"}
MEASURE = obj({"statut": enum(("exact", "borne", "traces", "absent")), "unite": enum(("g", "mg", "ug", "kcal")),
               "minimum": nullable(num()), "maximum": nullable(num())}, ("statut", "unite", "minimum", "maximum"))
SOURCE = obj({"source": TEXT, "edition": TEXT, "date": {"kind": "date"}, "licence": TEXT,
              "etat_ref": enum(STATES), "nutriments": obj({}, extra=MEASURE),
              "code": TEXT, "nom_source": TEXT, "hypothese": TEXT},
             ("source", "edition", "date", "licence", "etat_ref", "nutriments"))
REGISTRY = obj({"version": {"kind": "integer", "minimum": 1, "values": [1]},
                "exiger_sources": BOOL, "aliments": obj({}, extra=SOURCE)}, ("version", "aliments"))


def parse_measure(text, unit):
    value = ("" if text is None else str(text)).strip().replace(",", ".")
    if value in ("", "-", "—"):
        return {"statut": "absent", "unite": unit, "minimum": None, "maximum": None}
    if value.lower() == "traces":
        return {"statut": "traces", "unite": unit, "minimum": 0, "maximum": None}
    bounded = value.startswith("<")
    try:
        number = float(value.lstrip("< "))
    except ValueError as exc:
        raise ValueError(f"valeur nutritionnelle invalide : {text}") from exc
    if not math.isfinite(number) or number < 0 or (bounded and number == 0):
        raise ValueError("valeur nutritionnelle finie positive ou nulle requise")
    return {"statut": "borne" if bounded else "exact", "unite": unit,
            "minimum": 0 if bounded else number, "maximum": number}


def load_sources(workdir=None):
    result = {}
    paths = [SKILL_DIR / "data/provenance.yaml"]
    if workdir:
        paths.append(Path(workdir) / "provenance.yaml")
    for path in paths:
        if not path.exists():
            continue
        data = load_yaml(path)
        errors = schema_issues(data, REGISTRY, path.name, "schema_provenance")
        if errors:
            raise DataError(errors)
        for fid, source in data["aliments"].items():
            errors += schema_issues(fid, FOOD_ID, path.name, "schema_provenance")
            for nutrient, measure in source["nutriments"].items():
                errors += schema_issues(nutrient, FOOD_ID, path.name, "schema_provenance")
                low, high, status = measure["minimum"], measure["maximum"], measure["statut"]
                if ((status == "exact" and (low is None or low != high))
                    or (status == "borne" and (low is None or high is None or low > high))
                    or (status == "traces" and (low != 0 or high is not None))
                    or (status == "absent" and (low is not None or high is not None))
                    or (nutrient in UNITS and measure["unite"] != UNITS[nutrient])):
                    errors.append(Issue("erreur", "schema_provenance", fid, f"mesure incohérente : {nutrient}"))
            result[fid] = source
        if errors:
            raise DataError(errors)
    units = {}
    for fid, source in result.items():
        for nutrient, measure in source["nutriments"].items():
            if units.setdefault(nutrient, measure["unite"]) != measure["unite"]:
                raise DataError([Issue("erreur", "schema_provenance", fid, f"unités incohérentes : {nutrient}")])
    return result


def apply_sources(foods, workdir=None):
    sources = load_sources(workdir)
    if workdir and (Path(workdir) / "provenance.yaml").exists():
        registry = load_yaml(Path(workdir) / "provenance.yaml")
        if registry.get("exiger_sources"):
            foods = {fid: replace(food, prot=None, kcal=None) if fid not in sources else food
                     for fid, food in foods.items()}
    for fid, source in sources.items():
        if fid not in foods or foods[fid].etat_ref != source["etat_ref"]:
            raise DataError([Issue("erreur", "provenance_etat", fid, "aliment absent ou état de pesée incompatible")])
        values = {}
        for key, field in (("proteines_g", "prot"), ("energie_kcal", "kcal")):
            if key in source["nutriments"]:
                measure = source["nutriments"][key]
                values[field] = measure["minimum"] if measure["statut"] == "exact" else None
        # Une source ne peut pas certifier les anciennes colonnes qu'elle ne renseigne pas.
        for field in ("prot", "kcal"):
            values.setdefault(field, None)
        foods[fid] = replace(foods[fid], **values, source=f"{source['source']}:{source['edition']}")
    return foods


def nutrient_report(ctx):
    sources = load_sources(ctx.workdir)
    metrics = set(UNITS) | {n for s in sources.values() for n in s["nutriments"]}
    recipes = {}
    portions = ctx.profile["projet"]["portions_par_recette"]
    for rid, calc in ctx.calcs.items():
        result = {}
        for nutrient in sorted(metrics):
            bounds, missing, provenance = [], [], []
            for line in calc.lines:
                if line.negligible:
                    continue
                source = sources.get(line.food.id)
                measure = source and source["nutriments"].get(nutrient)
                if not measure or measure["statut"] == "absent":
                    missing.append(line.food.id)
                    continue
                factor = line.grams / 100 / portions
                bounds.append((measure["minimum"] * factor,
                               None if measure["maximum"] is None else measure["maximum"] * factor))
                provenance.append({"food": line.food.id, "source": source["source"], "edition": source["edition"],
                                   "statut": measure["statut"]})
            low = math.fsum(b[0] for b in bounds) if bounds and not missing else None
            high = math.fsum(b[1] for b in bounds) if bounds and not missing and all(b[1] is not None for b in bounds) else None
            if any(v is not None and not math.isfinite(v) for v in (low, high)):
                raise DataError([Issue("erreur", "nutrition_total", rid, f"total hors capacité : {nutrient}")])
            result[nutrient] = {"unite": UNITS.get(nutrient, next((s["nutriments"][nutrient]["unite"] for s in sources.values() if nutrient in s["nutriments"]), None)),
                                "minimum_par_portion": low, "maximum_par_portion": high,
                                "statut": "absent" if missing or not bounds else "exact" if low == high else "borne",
                                "aliments_non_renseignes": sorted(set(missing)), "sources": provenance}
        recipes[rid] = result
    return {"version": 1, "recettes": recipes, "portions": portions,
            "portee": "apports des seules préparations renseignées, selon les données déclarées"}
