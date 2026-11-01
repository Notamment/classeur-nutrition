"""Difficulté explicable, temps actif, variété et exclusions par familles."""
from __future__ import annotations

from collections import Counter

from core import Issue
from catalogs import LEVELS
from profiles import apply_requirements
from schemas import DIFFICULTIES


def recipe_metadata(recipe, catalogs):
    """Heuristique publiée : technique la plus exigeante, puis simultanéité."""
    execution = recipe.get("execution")
    result = {"difficulte": None, "niveau": None, "raisons": [],
              "temps_actif_min": recipe.get("temps_actif_min"),
              "plat_id": recipe.get("plat_id"), "ingredients_principaux": recipe.get("ingredients_principaux")}
    issues = []
    where = recipe.get("id", "?")
    if execution:
        names = execution["techniques"]
        if len(names) != len(set(names)):
            issues.append(Issue("erreur", "metadata_recette", where, "techniques dupliquées"))
        unknown = set(names) - catalogs.techniques.keys()
        if unknown:
            issues.append(Issue("erreur", "technique_inconnue", where, ", ".join(sorted(unknown))))
        else:
            levels = [(name, LEVELS[catalogs.techniques[name]["niveau"]]) for name in names]
            simultaneous = execution["taches_simultanees"]
            coordination = 3 if simultaneous >= 4 else 2 if simultaneous == 3 else 1
            level = max(coordination, *(n for _, n in levels))
            result.update(niveau=level, difficulte=DIFFICULTIES[level - 1],
                          raisons=[f"{catalogs.techniques[name]['nom']} : {DIFFICULTIES[n - 1]}" for name, n in levels]
                                  + [f"{simultaneous} tâche(s) simultanée(s) : {DIFFICULTIES[coordination - 1]}"])
    principal = recipe.get("ingredients_principaux")
    if principal and len(principal) != len(set(principal)):
        issues.append(Issue("erreur", "metadata_recette", where, "ingrédients principaux dupliqués"))
    if principal and "ingredients" in recipe:
        present = {line["food"] for line in recipe["ingredients"]}
        missing = set(principal) - present
        if missing:
            issues.append(Issue("erreur", "metadata_recette", where,
                                "ingrédients principaux absents de la recette : " + ", ".join(sorted(missing))))
    return result, issues


def check_recipe_adaptation(recipe, profile, catalogs, *, plan=False):
    metadata, issues = recipe_metadata(recipe, catalogs)
    where = recipe.get("id", "?")
    target = profile["repas"].get("difficulte_max")
    if target:
        if metadata["niveau"] is None:
            issues.append(Issue("erreur", "difficulte", where, "non vérifiable : renseigner execution.techniques et taches_simultanees", kind="unknown"))
        elif metadata["niveau"] > LEVELS[target]:
            issues.append(Issue("erreur", "difficulte", where,
                                f"{metadata['difficulte']} > {target} ; " + "; ".join(metadata["raisons"])))
    cap = profile["repas"].get("duree_active_max_min")
    active, total = recipe.get("temps_actif_min"), recipe.get("temps_total_min")
    if cap is not None:
        if active is None:
            issues.append(Issue("erreur", "duree_active", where, "non vérifiable : temps_actif_min absent", kind="unknown"))
        elif active > cap:
            issues.append(Issue("erreur", "duree_active", where, f"{active:g} min actives > {cap:g} min"))
    if plan and active is not None and total is not None and active > total:
        issues.append(Issue("erreur", "temps_incoherent", where, "temps actif > temps total"))
    if plan and profile["repas"]["duree_totale_max_min"] is not None and total is not None:
        if total > profile["repas"]["duree_totale_max_min"]:
            issues.append(Issue("erreur", "duree", where, f"{total:g} min > {profile['repas']['duree_totale_max_min']:g} min"))
    return metadata, apply_requirements(issues, profile)


def check_food_families(recipe, calc, foods, profile, catalogs, *, products=None):
    issues, present = [], {}
    for line in calc.lines:
        for family in catalogs.families_for(line.food):
            present.setdefault(family, set()).add(line.food.nom)
    for alternative in recipe.get("alternatives_poisson", []):
        food = foods.get(alternative["food"])
        if food:
            for family in catalogs.families_for(food):
                present.setdefault(family, set()).add(f"alternative {food.nom}")
    for key, code, level in (("familles_exclues", "famille_exclue", "erreur"),
                              ("familles_a_eviter", "famille_a_eviter", "alerte")):
        for family in sorted(set(profile["aliments"].get(key, [])) & present.keys()):
            prefix = "Préférence non satisfaite : " if level == "alerte" else ""
            issues.append(Issue(level, code, calc.rid,
                                f"{prefix}{family} : {', '.join(sorted(present[family]))}",
                                requirement="preference" if level == "alerte" else "imperative"))
    used = {line.food.id for line in calc.lines} | {a["food"] for a in recipe.get("alternatives_poisson", [])}
    unknown = sorted(fid for fid, item in (products or {}).get("produits", {}).items()
                     if fid in used and item["composition"]["statut"] == "inconnue")
    if unknown:
        for key, code, level in (("familles_exclues", "famille_non_verifiable", "erreur"),
                                 ("familles_a_eviter", "famille_a_eviter", "alerte")):
            if profile["aliments"].get(key):
                issues.append(Issue(level, code, calc.rid, "composition non vérifiable : " + ", ".join(unknown),
                                    kind="unknown", requirement="imperative" if level == "erreur" else "preference"))
    return issues


def _missing(recipes, field):
    return [r["id"] for r in recipes if not r.get(field)]


def check_week_variety(recipes, profile, where, catalogs):
    var, issues = profile["variete"], []
    distinct = var.get("recettes_distinctes_min_par_semaine")
    if distinct:
        missing = _missing(recipes, "plat_id")
        count = len({r["plat_id"] for r in recipes if r.get("plat_id")})
        if missing:
            issues.append(Issue("erreur", "variete_plats", where, "non vérifiable : plat_id absent pour " + ", ".join(missing), kind="unknown"))
        elif count < distinct:
            issues.append(Issue("erreur", "variete_plats", where, f"{count} plats distincts < {distinct}"))
    cap = var.get("ingredient_principal_max_par_semaine")
    if cap is not None:
        missing = _missing(recipes, "ingredients_principaux")
        if missing:
            issues.append(Issue("erreur", "ingredient_recurrent", where,
                                "non vérifiable : ingredients_principaux absents pour " + ", ".join(missing), kind="unknown"))
        counts = Counter(food for r in recipes for food in set(r.get("ingredients_principaux", [])))
        for food, count in sorted(counts.items()):
            if count > cap:
                issues.append(Issue("erreur", "ingredient_recurrent", where, f"{food} principal dans {count} recettes > {cap}"))
    minimum = var.get("techniques_distinctes_min_par_semaine")
    if minimum:
        missing = _missing(recipes, "execution")
        techniques = {t for r in recipes for t in r.get("execution", {}).get("techniques", [])}
        if missing or techniques - catalogs.techniques.keys():
            issues.append(Issue("erreur", "variete_techniques", where, "non vérifiable : techniques manquantes ou inconnues", kind="unknown"))
        elif len(techniques) < minimum:
            issues.append(Issue("erreur", "variete_techniques", where, f"{len(techniques)} techniques distinctes < {minimum}"))
    return apply_requirements(issues, profile)


def check_repeated_dishes(recipes, profile, where):
    cap = profile["variete"].get("repetition_plat_max")
    if cap is None:
        return []
    issues = []
    missing = _missing(recipes, "plat_id")
    if missing:
        issues.append(Issue("erreur", "repetition_plat", where, "non vérifiable : plat_id absent pour " + ", ".join(missing), kind="unknown"))
    counts = Counter(r["plat_id"] for r in recipes if r.get("plat_id"))
    for dish, count in sorted(counts.items()):
        if count > cap:
            issues.append(Issue("erreur", "repetition_plat", where, f"{dish} présent {count} fois > {cap}"))
    return apply_requirements(issues, profile)
