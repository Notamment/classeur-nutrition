"""Profils v1/v2, préréglages combinables et provenance des valeurs appliquées."""
from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from pathlib import Path

from core import DEFAULT_PROFILE, DataError, Issue, deep_merge, load_yaml, schema_issues
from schemas import CONFIGURABLE_RULES, PROFILE_V2, TEXT, obj

PRESETS_DIR = Path(__file__).resolve().parent.parent / "data" / "presets"
NEUTRAL_PROFILE = deep_merge(DEFAULT_PROFILE, {
    "version": 2, "prereglages": [], "exigences": {},
    "projet": {"semaines": 1, "usage": "Repas au choix", "organisation": "libre", "authenticite": "libre"},
    "repas": {"proteines_g_par_portion": None, "poids_servi_g_par_portion": None, "duree_totale_max_min": None,
              "duree_active_max_min": None, "difficulte_max": None},
    "repartition": None,
    "legumineuses": {"g_cuits_par_portion": None, "consecutives_autorisees": True},
    "variete": {"riz_max_par_semaine": None, "feculents_distincts_min_par_semaine": 0,
                "substituts_industriels_max": None, "especes_poisson_uniques": False,
                "alternatives_par_poisson": 0, "jour_max_fragile": None, "cuisines_distinctes": False,
                "recettes_distinctes_min_par_semaine": None, "ingredient_principal_max_par_semaine": None,
                "techniques_distinctes_min_par_semaine": None, "repetition_plat_max": None},
    "nutrition": {"mode": "desactive", "fer_vitamine_c": "non"},
    "alimentation": {"regime": "libre"},
    "aliments": {"exclus": [], "a_eviter": [], "sans_sel_ajoute_si": [], "familles_exclues": [], "familles_a_eviter": []},
    "selection": {"priorites": []},
    "labels": {"defaut": "aucun label exigé", "exceptions_bio": []},
    "materiel": None, "plaques": None, "bureau": [],
})


@dataclass
class ResolvedProfile:
    profile: dict
    origins: dict


def _leaves(value, prefix=""):
    if isinstance(value, dict):
        for key, val in value.items():
            yield from _leaves(val, f"{prefix}.{key}" if prefix else key)
    else:
        yield prefix, value


def _partial(schema):
    schema = copy.deepcopy(schema)
    if schema["kind"] == "object":
        schema["required"] = ()
        schema["properties"] = {k: _partial(v) for k, v in schema["properties"].items()}
    return schema


def list_presets():
    catalog = {}
    partial = _partial(PROFILE_V2)
    for path in sorted(PRESETS_DIR.glob("*.yaml")):
        data = load_yaml(path)
        errors = schema_issues(data, obj({"nom": TEXT, "description": TEXT, "profil": partial},
                                        ("nom", "description", "profil")), path.name, "schema_prereglage")
        if isinstance(data.get("profil"), dict) and {"version", "prereglages"} & data["profil"].keys():
            errors.append(Issue("erreur", "schema_prereglage", path.name, "version et préréglages imbriqués interdits"))
        if errors:
            raise DataError(errors)
        catalog[path.stem] = data
    return catalog


def resolve_profile(raw: dict) -> ResolvedProfile:
    version = raw.get("version", 1)
    if type(version) is not int or version not in (1, 2):
        raise DataError([Issue("erreur", "schema_profil", "profil", "version attendue : 1 ou 2")])
    base = DEFAULT_PROFILE if version == 1 else NEUTRAL_PROFILE
    profile = copy.deepcopy(base)
    origins = {path: f"defaut:v{version}" for path, _ in _leaves(profile)}

    def merge(patch, source):
        nonlocal profile
        for path, _ in _leaves(patch):
            # Une valeur remplaçant un objet invalide également ses anciennes origines.
            for old in list(origins):
                if old == path or old.startswith(path + ".") or path.startswith(old + "."):
                    del origins[old]
            origins[path] = source
        profile = deep_merge(profile, patch)

    if version == 2:
        names = raw.get("prereglages", [])
        errors = schema_issues(names, PROFILE_V2["properties"]["prereglages"], "profil", "schema_profil")
        if errors:
            raise DataError(errors)
        if len(names) != len(set(names)):
            raise DataError([Issue("erreur", "prereglage_doublon", "profil", "chaque préréglage doit apparaître une fois")])
        catalog = list_presets()
        explicit = dict(_leaves(raw))
        seen = {}
        for name in names:
            if name not in catalog:
                raise DataError([Issue("erreur", "prereglage_inconnu", "profil", f"préréglage inconnu : {name}")])
            patch = catalog[name]["profil"]
            for path, value in _leaves(patch):
                for previous, (source, old_value) in seen.items():
                    overlap = path == previous or path.startswith(previous + ".") or previous.startswith(path + ".")
                    if overlap and (path != previous or old_value != value):
                        conflict = path if len(path) < len(previous) else previous
                        covered = any(conflict == key or conflict.startswith(key + ".") for key in explicit)
                        if not covered:
                            raise DataError([Issue("erreur", "prereglages_conflit", "profil",
                                                  f"{conflict} : conflit entre {source} et {name} ; définir explicitement ce choix dans le profil")])
                seen[path] = (name, value)
            merge(patch, f"prereglage:{name}")
    merge(raw, "profil")
    return ResolvedProfile(profile, origins)


def load_resolved(workdir):
    return resolve_profile(load_yaml(Path(workdir) / "profile.yaml"))


def nutrition_mode(profile):
    return profile["nutrition"].get("mode", "cibles")


def categories(profile):
    return ("vegetarien", "poisson", "viande", "mixte") if profile.get("version") == 2 else ("vegetarien", "poisson", "viande")


def requirement(profile, code):
    return profile.get("exigences", {}).get(code, "imperative")


def apply_requirements(issues, profile):
    """Ne déclasse jamais une erreur structurelle ni une interdiction alimentaire."""
    out = []
    for issue in issues:
        if (issue.level == "erreur" and issue.where != "profil" and issue.code in CONFIGURABLE_RULES
                and requirement(profile, issue.code) == "preference"):
            issue = replace(issue, level="alerte", requirement="preference",
                            msg="Préférence non satisfaite : " + issue.msg)
        out.append(issue)
    return out


def nutrition_targets(profile):
    return nutrition_mode(profile) == "cibles"


def week_title(week):
    return week.get("theme") or week.get("cuisine") or "Repas de la semaine"


def forbidden_natures(profile):
    return {"libre": set(), "vegetarien": {"viande", "poisson"},
            "vegetalien": {"viande", "poisson", "laitier", "oeuf"},
            "pescetarien": {"viande"}}[profile.get("alimentation", {}).get("regime", "libre")]
