"""Catalogues déclaratifs de techniques et de familles culinaires."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core import DataError, Issue, load_yaml, schema_issues
from schemas import DIFFICULTIES, FOOD_ID, NATURES, TEXT, arr, enum, obj

DATA = Path(__file__).resolve().parent.parent / "data"
LEVELS = {name: n for n, name in enumerate(DIFFICULTIES, 1)}
FAMILY = obj({"nom": TEXT, "parents": arr(FOOD_ID), "natures": arr(enum(NATURES)),
              "tags": arr(TEXT), "aliments": arr(FOOD_ID)}, ("nom", "parents", "natures", "tags", "aliments"))
TECHNIQUE = obj({"nom": TEXT, "niveau": enum(DIFFICULTIES)}, ("nom", "niveau"))


@dataclass
class Catalogs:
    techniques: dict
    families: dict
    ancestors: dict

    def families_for(self, food):
        explicit = set(food.tag_values("famille"))
        found = explicit | {key for key, rule in self.families.items()
                            if food.nature in rule["natures"] or food.tags.intersection(rule["tags"])
                            or food.id in rule["aliments"]}
        return found | {parent for key in found for parent in self.ancestors.get(key, ())}

    def as_dict(self):
        return {"techniques": self.techniques, "familles": self.families}


def load_catalogs(directory=DATA):
    result = {}
    issues = []
    for filename, key, schema in (("techniques.yaml", "techniques", TECHNIQUE), ("families.yaml", "familles", FAMILY)):
        data = load_yaml(Path(directory) / filename)
        issues += schema_issues(data, obj({key: obj({}, extra=schema)}, (key,)), filename, "schema_catalogue")
        result[key] = data.get(key, {}) if isinstance(data, dict) else {}
        if isinstance(result[key], dict):
            for name in result[key]:
                if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name):
                    issues.append(Issue("erreur", "schema_catalogue", filename, f"identifiant invalide : {name}"))
    if issues:
        raise DataError(issues)
    families = result["familles"]
    ancestors = {}

    def visit(name, path):
        if name not in families or name in path:
            why = "cycle" if name in path else "parent inconnu"
            raise DataError([Issue("erreur", "schema_catalogue", "familles", f"{why} : {' > '.join((*path, name))}")])
        if name not in ancestors:
            parents = set(families[name]["parents"])
            ancestors[name] = parents | {ancestor for parent in parents for ancestor in visit(parent, (*path, name))}
        return ancestors[name]

    for name in families:
        visit(name, ())
    return Catalogs(result["techniques"], families, ancestors)


def check_family_references(profile, foods, catalogs):
    issues = []
    for key in ("familles_exclues", "familles_a_eviter"):
        for name in profile["aliments"].get(key, []):
            if name not in catalogs.families:
                issues.append(Issue("erreur", "famille_inconnue", "profil", f"aliments.{key} : {name}"))
    for food in foods.values():
        for name in food.tag_values("famille"):
            if name not in catalogs.families:
                issues.append(Issue("erreur", "foods_famille", "aliments", f"{food.id} : famille inconnue {name}"))
    return issues
