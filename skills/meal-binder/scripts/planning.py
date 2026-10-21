"""Planning opérationnel versionné, indépendant des semaines historiques."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import math
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from checks import analyse, check_recipe
from core import BinderError, DataError, Issue, compute_alternatives, compute_recipe, load_yaml, schema_issues, to_base
from manifest import digest, encode, hashes, input_files
from profiles import apply_requirements, nutrition_mode, requirement
from schemas import TEXT, FOOD_ID, POS_COUNT, POSITIVE, STATES, arr, enum, nullable, num, obj
from shopping import WeekShop, build_shopping, check_budget

DATE = {"kind": "date"}
ENTRY = obj({"recette": TEXT, "composant": FOOD_ID, "portions": POS_COUNT, "preparation": FOOD_ID}, ("portions",))
SERVICE = obj({"id": FOOD_ID, "debut": TEXT, "plats": arr(ENTRY, 1)}, ("id", "debut", "plats"))
PREP = obj({"id": FOOD_ID, "debut": TEXT, "duree_min": POSITIVE, "equipements": arr(FOOD_ID),
            "utilisable_jusqua": TEXT}, ("id", "debut", "duree_min", "equipements", "utilisable_jusqua"))
LOT = obj({"id": FOOD_ID, "food": FOOD_ID, "quantite": nullable(num()), "unite": enum(("g", "ml", "piece")),
           "etat": enum(STATES), "disponible_le": DATE, "limite": DATE, "type_limite": enum(("DLC", "DDM")), "source": TEXT},
          ("id", "food", "quantite", "unite", "etat", "disponible_le", "limite", "type_limite", "source"))
FORMAT = obj({"version": {"kind": "integer", "minimum": 1, "values": [1]}, "stock_mode": enum(("lots_exclusifs",)),
              "services": arr(SERVICE, 1), "preparations": arr(PREP), "equipements": obj({}, extra=POS_COUNT),
              "lots": arr(LOT), "composants": obj({}, extra=obj({"portions": POS_COUNT, "recette": obj({}, extra=True)}, ("portions", "recette")))},
             ("version", "stock_mode", "services", "preparations", "equipements", "lots"))


def instant(value):
    try:
        result = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise BinderError("instant ISO 8601 avec décalage UTC requis") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise BinderError("les horaires doivent préciser le décalage UTC, par exemple 2026-01-02T12:00+01:00")
    return result


def scaled(recipe, ratio):
    recipe = copy.deepcopy(recipe)
    for line in [*recipe.get("ingredients", []), *recipe.get("alternatives_poisson", [])]:
        line["qte"] *= ratio
        if line.get("achat"):
            line["achat"]["qte"] *= ratio
    if "eau_retenue_g" in recipe:
        recipe["eau_retenue_g"] *= ratio
    return recipe


def report(directory, *, ctx=None):
    directory = Path(directory)
    if ctx is None:
        ctx = analyse(directory, complete=True)
        if ctx.schedule is not None:
            return ctx.schedule
    data = load_yaml(directory / "schedule.yaml")
    errors = schema_issues(data, FORMAT, "schedule", "schema_planning")
    if errors:
        raise DataError(errors)
    if ctx.pantry:
        raise BinderError("planning en lots_exclusifs : convertir explicitement pantry.yaml en lots datés pour éviter tout double comptage")
    issues = []
    def issue(code, where, message, *, unknown=False, error=True):
        issues.append(Issue("erreur" if error else "alerte", code, where, message, kind="unknown" if unknown else "violation"))
    preparations, intervals = {}, {}
    for prep in data["preparations"]:
        pid = prep["id"]
        if pid in preparations:
            raise BinderError("identifiant de préparation dupliqué")
        start, until = instant(prep["debut"]), instant(prep["utilisable_jusqua"])
        end = start + dt.timedelta(minutes=prep["duree_min"])
        if until < end:
            issue("planning_conservation", pid, "limite déclarée antérieure à la fin de préparation")
        preparations[pid] = (start, end, until, prep)
        if len(set(prep["equipements"])) != len(prep["equipements"]):
            raise BinderError("équipement répété dans une préparation")
        for equipment in prep["equipements"]:
            if equipment not in data["equipements"]:
                issue("planning_equipement", pid, "équipement sans capacité déclarée : " + equipment)
            intervals.setdefault(equipment, []).extend([(start, 1), (end, -1)])
    for equipment, events in intervals.items():
        used = 0
        for _, change in sorted(events):  # Les fins libèrent la capacité avant un début à la même heure.
            used += change
            if used > data["equipements"].get(equipment, 0):
                issue("planning_capacite", equipment, "préparations simultanées au-delà de la capacité déclarée")
                break
    ledger, lot_ids = [], set()
    for item in data["lots"]:
        item = copy.deepcopy(item)
        fid = item["food"]
        if item["id"] in lot_ids:
            raise BinderError("identifiant de lot dupliqué")
        lot_ids.add(item["id"])
        if fid not in ctx.foods or item["etat"] != ctx.foods[fid].etat_ref:
            raise BinderError("lot : aliment inconnu ou état incompatible")
        start, limit = dt.date.fromisoformat(str(item["disponible_le"])), dt.date.fromisoformat(str(item["limite"]))
        if limit < start:
            raise BinderError("limite de lot antérieure à sa disponibilité")
        item.update(disponible_le=start.isoformat(), limite=limit.isoformat())
        item["reste"] = None if item["quantite"] is None else to_base(ctx.foods[fid], item["quantite"], item["unite"])
        ledger.append(item)
    jobs, service_ids, used_preps = [], set(), set()
    components = data.get("composants", {})
    for service in data["services"]:
        sid = service["id"]
        if sid in service_ids:
            raise BinderError("identifiant de service dupliqué")
        service_ids.add(sid)
        serving = instant(service["debut"])
        for index, entry in enumerate(service["plats"]):
            where = f"{sid}/{index + 1}"
            if ("recette" in entry) == ("composant" in entry):
                raise BinderError("chaque plat référence une recette OU un composant")
            if "composant" in entry:
                component = components.get(entry["composant"])
                if component is None:
                    raise BinderError("composant introuvable")
                original, portions = component["recette"], component["portions"]
            else:
                if entry["recette"] not in ctx.recipes:
                    raise BinderError("recette de service introuvable ou non calculable")
                original, portions = ctx.recipes[entry["recette"]], ctx.profile["projet"]["portions_par_recette"]
            cooking = serving
            if entry.get("preparation"):
                pid = entry["preparation"]
                if pid not in preparations:
                    raise BinderError("préparation référencée introuvable")
                used_preps.add(pid)
                cooking, end, until, prep = preparations[pid]
                if end > serving or until < serving:
                    issue("planning_conservation", where, "service hors intervalle de disponibilité et conservation déclaré")
                if prep["duree_min"] < original.get("temps_total_min", 0):
                    issue("planning_duree", where, "créneau de préparation inférieur à la durée déclarée de la recette")
                if set(original.get("appareils", [])) - set(prep["equipements"]) - {"aucun"}:
                    issue("planning_equipement", where, "équipements de la recette non couverts par la préparation")
            else:
                issue("planning_preparation", where, "préparation, durée et conservation non planifiées", unknown=True)
            # Contrôle préalable avant toute multiplication de valeurs non validées.
            original_calc, invalid = compute_recipe(original, ctx.foods, portions, version=ctx.profile["version"], nutrition_mode=nutrition_mode(ctx.profile))
            issues += invalid
            if original_calc is None:
                continue
            recipe = scaled(original, entry["portions"] / portions)
            rc, invalid = compute_recipe(recipe, ctx.foods, entry["portions"], version=ctx.profile["version"], nutrition_mode=nutrition_mode(ctx.profile))
            issues += invalid
            if rc is None:
                continue
            alts = compute_alternatives(recipe, rc, ctx.foods, version=ctx.profile["version"], nutrition_mode=nutrition_mode(ctx.profile))
            local = check_recipe(rc, recipe, ctx.profile, 1, alts)
            if ctx.catalogs:
                from adaptation import check_recipe_adaptation, check_food_families
                local += check_recipe_adaptation(recipe, ctx.profile, ctx.catalogs)[1]
                local += check_food_families(recipe, rc, ctx.foods, ctx.profile, ctx.catalogs, products=ctx.products)
            issues += [replace(i, where=where + ":" + i.where) for i in local]
            jobs.append((cooking, where, serving, recipe, rc))
    for pid in preparations.keys() - used_preps:
        issue("planning_preparation_inutilisee", pid, "préparation sans service associé", error=False)
    outputs, weekly = [], {}
    for cooking, where, serving, recipe, rc in sorted(jobs, key=lambda j: (j[0], j[1])):
        day = cooking.date().isoformat()
        active = [lot for lot in ledger if lot["disponible_le"] <= day <= lot["limite"]]
        pantry = []
        for fid in {line.food.id for line in rc.lines}:
            lots = [lot for lot in active if lot["food"] == fid]
            quantity = None if any(lot["reste"] is None for lot in lots) else math.fsum(lot["reste"] for lot in lots)
            pantry.append({"id": fid, "quantite": quantity, "unite": ctx.foods[fid].unite_achat})
        foods = dict(ctx.foods)
        if ctx.products:
            for fid, product in ctx.products["produits"].items():
                age = (cooking.date() - dt.date.fromisoformat(str(product["observe_le"]))).days
                if age < 0 or age > ctx.products["validite_jours"]:
                    foods[fid] = replace(foods[fid], prix_eur=None)
        # Réutiliser les conversions et conditionnements, avec une occurrence par calcul.
        rc = copy.deepcopy(rc)
        for line in rc.lines:
            line.food = foods[line.food.id]
        p = copy.deepcopy(ctx.profile)
        p["budget"]["plafond_eur_semaine"] = None
        job = SimpleNamespace(weeks=[{"semaine": where, "recettes": [{"id": rc.rid}]}], foods=foods,
                              calcs={rc.rid: rc}, pantry=pantry, profile=p)
        shops, _, shopping_issues = build_shopping(job)
        issues += shopping_issues
        shop = shops[0]
        allocations = []
        for line in shop.lines:
            remaining = line.mobilise
            for lot in sorted((v for v in active if v["food"] == line.food.id), key=lambda v: (v["limite"], v["id"])):
                if lot["reste"] is None:
                    continue
                amount = min(remaining, lot["reste"])
                if amount:
                    lot["reste"] -= amount
                    remaining -= amount
                    allocations.append({"lot": lot["id"], "food": lot["food"], "quantite": amount, "unite": line.food.unite_achat})
        iso = cooking.date().isocalendar()
        week_id = f"{iso.year}-W{iso.week:02d}"
        group = weekly.setdefault(week_id, WeekShop(week_id, []))
        group.montant_caisse += shop.montant_caisse
        group.prix_manquants += shop.prix_manquants
        group.stocks_inconnus += shop.stocks_inconnus
        group.incomplet |= shop.incomplet
        outputs.append({"id": where, "preparation": cooking.isoformat(), "service": serving.isoformat(),
            "recette_id": recipe["id"], "plat": recipe["nom"],
            "portions": rc.portions, "proteines_par_portion": rc.prot_pp, "kcal_par_portion": rc.kcal_pp,
            "lots_mobilises": allocations, "caisse_connue": shop.montant_caisse, "budget_verifiable": shop.budget_verifiable,
            "achats": [{"food": line.food.id, "besoin": line.besoin, "achat": line.achat, "unite": line.food.unite_achat,
                        "reste_non_reporte": line.reste, "conditionnements": line.packs} for line in shop.lines]})
    for shop in weekly.values():
        issues += check_budget(shop, ctx.profile)
    issues = apply_requirements(issues, ctx.profile)
    hard_unknown = ctx.profile["budget"]["plafond_eur_semaine"] is not None and requirement(ctx.profile, "budget_depasse") == "imperative" and any(not s.budget_verifiable for s in weekly.values())
    return {"version": 1, "type": "planning_operationnel", "admissible": not any(i.level == "erreur" for i in issues) and not hard_unknown,
            "budget_imperatif_inverifiable": hard_unknown, "services": outputs, "lots_restants": ledger,
            "semaines_achat": {wid: {"caisse_connue": s.montant_caisse, "verifiable": s.budget_verifiable} for wid, s in weekly.items()},
            "ecarts": [i.__dict__ for i in issues], "entrees_sha256": digest(encode(hashes(input_files(directory), directory)).encode("utf-8")),
            "limites": ["Durées, capacités et limites de conservation déclaratives : relecture humaine requise.",
                        "DLC et DDM dépassées exclues par précaution ; lots mobilisés par limite croissante.",
                        "Restes d'achats non reportés sans ajout explicite d'un lot daté.",
                        "Composants servis comme lignes explicites ; aucune substitution implicite d'ingrédients.",
                        "Quotas et variété historiques contrôlés sur les semaines sources, pas comme objectifs implicites du calendrier."]}


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["schedule"])
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = report(args.dir)
        print(encode(result), end="")
        return 0 if result["admissible"] else 1
    except DataError as exc:
        print(encode({"version": 1, "ecarts": [i.__dict__ for i in exc.issues]}), end="")
        return 1
    except (BinderError, OSError, ValueError, OverflowError) as exc:
        print(encode({"version": 1, "erreur": str(exc)}), end="")
        return 2
