"""Contrôles du profil, du plan, des recettes, des semaines et du classeur."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from core import (BinderError, DataError, Issue, compute_alternatives, compute_recipe,
                  load_foods, load_profile, load_weeks, load_yaml, schema_issues, to_base, week_order)
from schemas import PANTRY, PANTRY_ENTRY, PLAN, PLAN_V2, STORES, WEEK, WEEK_V2, arr, profile_schema
from profiles import apply_requirements, categories, forbidden_natures, nutrition_mode, nutrition_targets

ID_RE = re.compile(r"^S\d{2}-R\d{2}$")
WEEK_RE = re.compile(r"^S\d{2}$")
SERVICES = {"chaud", "tiède", "tiede", "froid"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _range(p: dict, path: str) -> list | None:
    node = p
    for k in path.split("."):
        node = (node or {}).get(k)
    return node


# ---------------------------------------------------------------- profil

def check_profile(p: dict, foods: dict) -> list:
    out = schema_issues(p, profile_schema(p), "profil", "schema_profil")
    if out:
        return out
    pr = p["projet"]
    total = pr["semaines"] * pr["recettes_par_semaine"]
    rep = p["repartition"]
    if rep is not None and sum(rep.get(c, 0) for c in categories(p)) != total:
        out.append(Issue("erreur", "repartition", "profil",
                         f"somme des catégories = {sum(rep.get(c, 0) for c in categories(p))} ≠ {total} recettes"))
    forbidden = forbidden_natures(p)
    if rep and any(rep.get(c, 0) for c in forbidden | ({"mixte"} if forbidden & {"viande", "poisson"} else set())):
        out.append(Issue("erreur", "regime", "profil", "répartition incompatible avec le régime alimentaire"))
    if not nutrition_targets(p) and (p["repas"].get("proteines_g_par_portion") or p["repas"].get("kcal_par_portion")
                                     or p["nutrition"]["fer_vitamine_c"] != "non"):
        out.append(Issue("alerte", "cibles_inactives", "profil", "objectifs protéines, kcal et fer/vitamine C inactifs hors mode cibles"))
    for key in ("aliments.exclus", "aliments.a_eviter", "legumineuses.epices_associees"):
        for fid in _range(p, key) or []:
            if fid not in foods:
                out.append(Issue("alerte", "id_inconnu", "profil", f"{key} : « {fid} » absent de la base d'aliments"))
    if not pr.get("mois"):
        out.append(Issue("alerte", "mois", "profil", "projet.mois vide : la saisonnalité ne peut pas être appliquée"))
    return out


def check_pantry(entries: list, foods: dict) -> list:
    out = schema_issues(entries, arr(PANTRY_ENTRY), "stock", "schema_stock")
    if out:
        return out
    for e in entries:
        fid = e.get("id")
        if fid not in foods:
            out.append(Issue("alerte", "stock_inconnu", "stock", f"« {fid} » absent de la base : ajouter à foods.local.csv"))
        elif e.get("etat") and e["etat"] != foods[fid].etat_ref:
            out.append(Issue("alerte", "stock_etat", "stock",
                             f"{fid} : état « {e['etat']} » ≠ « {foods[fid].etat_ref} » ; stock non mobilisé"))
        elif e.get("quantite") is not None:
            try:
                to_base(foods[fid], e["quantite"], e.get("unite", foods[fid].unite_achat))
            except ValueError as exc:
                out.append(Issue("erreur", "stock_conversion", "stock", str(exc)))
        if e.get("quantite") == 0:
            out.append(Issue("alerte", "stock_zero", "stock", f"{fid} : stock connu vide ; null signifie une quantité inconnue"))
    return out


def load_pantry(workdir: Path, foods: dict) -> tuple[list, list]:
    path = workdir / "pantry.yaml"
    if not path.exists():
        return [], []
    data = load_yaml(path)
    issues = schema_issues(data, PANTRY, "stock", "schema_stock")
    if issues:
        raise DataError(issues)
    issues = check_pantry(data["stock"], foods)
    if any(i.level == "erreur" for i in issues):
        raise DataError(issues)
    return data["stock"], issues


# ---------------------------------------------------------------- plan

def check_plan(plan: dict, p: dict) -> list:
    out = schema_issues(p, profile_schema(p), "profil", "schema_profil")
    out += schema_issues(plan, PLAN_V2 if p.get("version") == 2 else PLAN, "plan", "schema_plan")
    if out:
        return out
    pr, var, leg = p["projet"], p["variete"], p["legumineuses"]
    weeks = plan.get("semaines") or []
    if len(weeks) > pr["semaines"]:
        out.append(Issue("erreur", "semaines", "plan", f"{len(weeks)} semaines > {pr['semaines']}"))
    elif len(weeks) < pr["semaines"]:
        out.append(Issue("alerte", "semaines", "plan", f"{len(weeks)} semaines planifiées sur {pr['semaines']}"))
    counts = {c: 0 for c in categories(p)}
    species, cuisines, seen, industrial = {}, {}, set(), 0
    excluded = {norm(c) for c in var["cuisines_exclues"]}
    seen_weeks = set()
    for w in weeks:
        wid = w.get("id", "?")
        out += check_organisation(w, p, wid)
        if wid in seen_weeks:
            out.append(Issue("erreur", "id_doublon", wid, "semaine déjà utilisée"))
        seen_weeks.add(wid)
        rs = w.get("recettes") or []
        if not WEEK_RE.match(str(wid)):
            out.append(Issue("erreur", "id_semaine", wid, "format attendu SXX"))
        if len(rs) != pr["recettes_par_semaine"]:
            out.append(Issue("erreur", "recettes", wid, f"{len(rs)} recettes ≠ {pr['recettes_par_semaine']}"))
        cz = norm(w.get("cuisine"))
        if cz in excluded:
            out.append(Issue("erreur", "cuisine_exclue", wid, f"« {w.get('cuisine')} » est exclue"))
        if cz and cz in cuisines and var.get("cuisines_distinctes", True):
            out.append(Issue("erreur", "cuisine_doublon", wid, f"« {w.get('cuisine')} » déjà en {cuisines[cz]}"))
        cuisines.setdefault(cz, wid)
        rice = 0
        starches = set()
        prev_leg = None
        for r in rs:
            rid = r.get("id", "?")
            if not ID_RE.match(str(rid)) or not str(rid).startswith(str(wid)):
                out.append(Issue("erreur", "id_recette", rid, f"format attendu {wid}-RYY"))
            if rid in seen:
                out.append(Issue("erreur", "id_doublon", rid, "identifiant déjà utilisé"))
            seen.add(rid)
            cat = r.get("categorie")
            if cat not in counts:
                out.append(Issue("erreur", "categorie", rid, f"« {cat} » : attendu vegetarien | poisson | viande"))
            else:
                counts[cat] += 1
            if cat in forbidden_natures(p) or (cat == "mixte" and forbidden_natures(p) & {"viande", "poisson"}):
                out.append(Issue("erreur", "regime", rid, f"catégorie {cat} incompatible avec le régime"))
            st = norm(r.get("feculent")).replace(" ", "_")
            if st:
                starches.add(st)
                rice += st == "riz" or st.startswith("riz_")
            is_leg = bool(r.get("legumineuses")) or (leg["soja_compte"] and bool(r.get("soja")))
            if is_leg and prev_leg and not leg["consecutives_autorisees"]:
                out.append(Issue("erreur", "legumineuses_consecutives", rid, f"suit {prev_leg} qui contient aussi des légumineuses"))
            prev_leg = rid if is_leg else None
            sp = norm(r.get("espece_poisson"))
            if cat == "poisson" and not sp:
                out.append(Issue("alerte", "espece", rid, "espece_poisson non renseignée"))
            if sp and var["especes_poisson_uniques"]:
                if sp in species:
                    out.append(Issue("erreur", "espece_doublon", rid, f"« {sp} » déjà en {species[sp]}"))
                species.setdefault(sp, rid)
            industrial += bool(r.get("substitut_industriel"))
        if var["riz_max_par_semaine"] is not None and rice > var["riz_max_par_semaine"]:
            out.append(Issue("erreur", "riz", wid, f"{rice} recettes au riz > {var['riz_max_par_semaine']}"))
        if len(starches) < var["feculents_distincts_min_par_semaine"]:
            out.append(Issue("erreur", "feculents", wid,
                             f"{len(starches)} féculents distincts < {var['feculents_distincts_min_par_semaine']}"))
    complete = len(weeks) == pr["semaines"]
    for c in categories(p) if p["repartition"] is not None else ():
        target = p["repartition"].get(c, 0)
        if counts[c] > target or (complete and counts[c] != target):
            out.append(Issue("erreur", "repartition", "plan", f"{c} : {counts[c]} recettes, cible {target}"))
    if var["substituts_industriels_max"] is not None and industrial > var["substituts_industriels_max"]:
        out.append(Issue("erreur", "substituts", "plan", f"{industrial} > {var['substituts_industriels_max']}"))
    return apply_requirements(out, p)


def check_organisation(week, profile, where):
    mode = profile["projet"].get("organisation", "cuisines")
    key = {"cuisines": "cuisine", "themes": "theme"}.get(mode)
    if key and not week.get(key):
        return [Issue("erreur", "organisation", where, f"{key} obligatoire pour l'organisation {mode}")]
    if profile["variete"].get("cuisines_distinctes") and not week.get("cuisine"):
        return [Issue("erreur", "organisation", where, "cuisine requise pour contrôler des cuisines distinctes")]
    return []


# ---------------------------------------------------------------- recette

def check_recipe(rc, r: dict, p: dict, position: int, alts: list) -> list:
    out = []
    rid = rc.rid
    rep, leg, var, nut = p["repas"], p["legumineuses"], p["variete"], p["nutrition"]
    targets = [("poids_servi", "poids_servi_g_par_portion", rc.poids_pp, "g servis")]
    if nutrition_targets(p):
        targets += [("proteines", "proteines_g_par_portion", rc.prot_pp, "g de protéines"),
                    ("kcal", "kcal_par_portion", rc.kcal_pp, "kcal")]
    for code, key, value, label in targets:
        limits = rep.get(key)
        if limits is None:
            continue
        if value is None:
            out.append(Issue("erreur", code, rid, f"{label}/portion : objectif non vérifiable, données absentes"))
        elif not limits[0] <= value <= limits[1]:
            out.append(Issue("erreur", code, rid, f"{value:.1f} {label}/portion hors {limits} (estimation)"))
    t = r.get("temps_total_min")
    if isinstance(t, (int, float)):
        if rep["duree_totale_max_min"] is not None and t > rep["duree_totale_max_min"]:
            out.append(Issue("erreur", "duree", rid, f"{t} min > {rep['duree_totale_max_min']} min"))
        ta = r.get("temps_actif_min")
        if isinstance(ta, (int, float)) and ta > t:
            out.append(Issue("erreur", "temps_incoherent" if p["version"] == 2 else "duree", rid, "temps actif > temps total"))
    if p["projet"].get("authenticite") == "documentee" and not r.get("authenticite"):
        out.append(Issue("erreur", "authenticite", rid, "note d'authenticité requise par le profil"))
    if p["version"] == 2 and r.get("alternatives_poisson") and not any(ln.food.nature == "poisson" for ln in rc.lines):
        out.append(Issue("erreur", "alternative_invalide", rid, "alternatives poisson déclarées sans poisson à remplacer"))
    allowed = set(p["materiel"] or []) | {"aucun"}
    for a in r.get("appareils") or []:
        if p["materiel"] is not None and a not in allowed:
            out.append(Issue("erreur", "materiel", rid, f"appareil « {a} » absent de profile.materiel"))
    if r.get("service") and norm(r["service"]) not in {norm(s) for s in SERVICES}:
        out.append(Issue("alerte", "service", rid, f"service « {r['service']} » : chaud | tiède | froid"))
    if rc.has_legumes:
        limits = leg["g_cuits_par_portion"]
        if limits is not None and not limits[0] <= rc.legumes_g_pp <= limits[1]:
            out.append(Issue("erreur", "legumineuses_g", rid, f"{rc.legumes_g_pp:.0f} g cuits/portion hors {limits}"))
        spices = set(leg["epices_associees"] or [])
        if spices and not spices & {ln.food.id for ln in rc.lines}:
            out.append(Issue("alerte", "legumineuses_epices", rid, f"aucune épice associée ({', '.join(sorted(spices))})"))
    triggers = [t for t in p["aliments"]["sans_sel_ajoute_si"] if t in rc.tag_foods]
    if triggers and r.get("sel_ajoute") is not False:
        names = ", ".join(n for t in triggers for n in rc.tag_foods[t])
        out.append(Issue("erreur", "sel", rid, f"sel ajouté avec {names}"))
    excluded = set(p["aliments"]["exclus"] or [])
    for ln in rc.lines:
        if ln.food.id in excluded:
            out.append(Issue("erreur", "aliment_exclu", rid, f"{ln.food.nom} est exclu par le profil"))
        if ln.food.id in p["aliments"].get("a_eviter", []):
            out.append(Issue("alerte", "aliment_a_eviter", rid, f"Préférence non satisfaite : {ln.food.nom} est à éviter"))
        if ln.food.nature in forbidden_natures(p):
            out.append(Issue("erreur", "regime", rid, f"{ln.food.nom} incompatible avec le régime alimentaire"))
    mode = nut["fer_vitamine_c"] if nutrition_targets(p) else "non"
    iron = rc.fer + rc.fer_vegetal
    if mode == "chaque_repas" and not (iron and rc.vitc):
        miss = " et ".join(x for x, ok in (("fer", iron), ("vitamine C", rc.vitc)) if not ok)
        out.append(Issue("erreur", "fer_vitc", rid, f"source de {miss} absente"))
    elif mode == "si_fer_vegetal" and rc.fer_vegetal and not rc.vitc:
        out.append(Issue("erreur", "fer_vitc", rid, f"fer végétal ({', '.join(rc.fer_vegetal)}) sans vitamine C"))
    if rc.especes_poisson or rc.categorie in ("poisson", "mixte"):
        if not rc.especes_poisson:
            out.append(Issue("alerte", "espece", rid, "espèce de poisson non taguée dans la base"))
        n = len([a for a in alts if "erreur" not in a])
        if n < var["alternatives_par_poisson"]:
            out.append(Issue("alerte", "alternatives", rid, f"{n} alternative(s) poisson < {var['alternatives_par_poisson']}"))
        for a in alts:
            if "erreur" in a:
                out.append(Issue("erreur", "alternative_invalide", rid, f"{a['nom']} : {a['erreur']}"))
                continue
            if a["food"] in excluded:
                out.append(Issue("erreur", "alternative_invalide", rid, f"{a['nom']} : aliment exclu"))
            if a["food"] in p["aliments"].get("a_eviter", []):
                out.append(Issue("alerte", "aliment_a_eviter", rid, f"Préférence non satisfaite : alternative {a['nom']} à éviter"))
            for field, key, label in (("prot_pp", "proteines_g_par_portion", "protéines"),
                                      ("poids_pp", "poids_servi_g_par_portion", "poids servi"),
                                      ("kcal_pp", "kcal_par_portion", "kcal")):
                limits = rep.get(key)
                if key != "poids_servi_g_par_portion" and not nutrition_targets(p):
                    continue
                if limits and (a[field] is None or not limits[0] <= a[field] <= limits[1]):
                    out.append(Issue("alerte", "alternative_a_ajuster", rid,
                                     f"{a['nom']} : {label} hors plage, ajuster avant substitution"))
    late = var.get("jour_max_fragile")
    if late and rc.fragiles and position > late:
        out.append(Issue("alerte", "fragile", rid,
                         f"jour {position} : {', '.join(rc.fragiles)} — achat différé ou recette plus tôt"))
    return apply_requirements(out, p)


# ---------------------------------------------------------------- analyse complète

@dataclass
class Context:
    workdir: Path
    profile: dict
    foods: dict
    weeks: list
    recipes: dict = field(default_factory=dict)     # id -> dict
    calcs: dict = field(default_factory=dict)       # id -> RecipeCalc
    alts: dict = field(default_factory=dict)        # id -> list
    week_of: dict = field(default_factory=dict)     # id -> semaine
    position: dict = field(default_factory=dict)    # id -> jour (1..n)
    issues: list = field(default_factory=list)
    pantry: list = field(default_factory=list)
    stores: dict = field(default_factory=dict)
    declared: set = field(default_factory=set)
    shops: list = field(default_factory=list)
    final_stock: dict = field(default_factory=dict)


def analyse(workdir: Path, complete: bool = False) -> Context:
    p = load_profile(workdir)
    foods, food_issues = load_foods(workdir)
    weeks = load_weeks(workdir)
    ctx = Context(workdir, p, foods, weeks, issues=list(food_issues))
    ctx.issues += check_profile(p, foods)
    if any(i.code == "schema_profil" for i in ctx.issues):
        raise DataError(ctx.issues)
    ctx.pantry, pantry_issues = load_pantry(workdir, foods)
    ctx.issues += pantry_issues
    if (workdir / "stores.yaml").exists():
        ctx.stores = load_yaml(workdir / "stores.yaml")
        invalid = schema_issues(ctx.stores, STORES, "magasins", "schema_magasins")
        if invalid:
            raise DataError(invalid)
    portions = p["projet"]["portions_par_recette"]
    seen_weeks = set()
    for w in weeks:
        invalid = schema_issues(w, WEEK_V2 if p["version"] == 2 else WEEK, "semaine", "schema_semaine")
        if invalid:
            raise DataError(invalid)
        if w["semaine"] in seen_weeks:
            raise DataError([Issue("erreur", "id_doublon", w["semaine"], "semaine déjà utilisée")])
        seen_weeks.add(w["semaine"])
        ctx.issues += _check_week(ctx, w, portions)
    ctx.issues += _check_classeur(ctx, complete)
    # Point d'entrée partagé par CLI, rendu, audit et évaluations.
    from shopping import build_shopping
    ctx.shops, ctx.final_stock, shopping_issues = build_shopping(ctx)
    ctx.issues = apply_requirements(ctx.issues + shopping_issues, p)
    return ctx


def _check_week(ctx: Context, w: dict, portions: int) -> list:
    p, var, leg = ctx.profile, ctx.profile["variete"], ctx.profile["legumineuses"]
    wid = w.get("semaine", "?")
    out = check_organisation(w, p, wid)
    if not WEEK_RE.match(str(wid)):
        out.append(Issue("erreur", "id_semaine", str(wid), "format attendu SXX"))
    rs = w.get("recettes") or []
    if len(rs) != p["projet"]["recettes_par_semaine"]:
        out.append(Issue("erreur", "recettes", wid, f"{len(rs)} recettes ≠ {p['projet']['recettes_par_semaine']}"))
    if norm(w.get("cuisine")) in {norm(c) for c in var["cuisines_exclues"]}:
        out.append(Issue("erreur", "cuisine_exclue", wid, f"« {w.get('cuisine')} » est exclue"))
    ids = [r.get("id") for r in rs]
    order = week_order(w)
    if "ordre" in w and (sorted(w["ordre"]) != sorted(ids) or len(set(w["ordre"])) != len(w["ordre"])):
        out.append(Issue("erreur", "ordre", wid, "« ordre » doit contenir chaque id de recette une fois"))
        order = ids
    for r in rs:
        rid = r.get("id", "?")
        if not ID_RE.match(str(rid)) or not str(rid).startswith(str(wid)):
            out.append(Issue("erreur", "id_recette", str(rid), f"format attendu {wid}-RYY"))
        if rid in ctx.declared:
            out.append(Issue("erreur", "id_doublon", str(rid), "identifiant déjà utilisé"))
            continue
        ctx.declared.add(rid)
        ctx.week_of[rid] = wid
        rc, iss = compute_recipe(r, ctx.foods, portions, version=p["version"], nutrition_mode=nutrition_mode(p))
        out += iss
        if rc is None:
            continue
        pos = order.index(rid) + 1 if rid in order else len(order)
        alts = compute_alternatives(r, rc, ctx.foods, version=p["version"], nutrition_mode=nutrition_mode(p))
        ctx.recipes[rid], ctx.calcs[rid], ctx.alts[rid] = r, rc, alts
        ctx.week_of[rid], ctx.position[rid] = wid, pos
        out += check_recipe(rc, r, p, pos, alts)
    calcs = [ctx.calcs[i] for i in order if i in ctx.calcs]
    prev = None
    for rc in calcs:
        is_leg = rc.has_legumes or (leg["soja_compte"] and bool(rc.soja))
        if is_leg and prev and not leg["consecutives_autorisees"]:
            out.append(Issue("erreur", "legumineuses_consecutives", rc.rid, f"suit {prev} qui contient aussi des légumineuses"))
        prev = rc.rid if is_leg else None
    ph = sorted({n for rc in calcs for n in rc.placeholders})
    if ph and nutrition_mode(p) != "desactive":
        out.append(Issue("alerte", "donnees_provisoires", wid,
                         f"{len(ph)} aliment(s) aux valeurs provisoires : nutrition = estimation non vérifiée"))
    rice = sum(rc.riz for rc in calcs)
    if var["riz_max_par_semaine"] is not None and rice > var["riz_max_par_semaine"]:
        out.append(Issue("erreur", "riz", wid, f"{rice} recettes au riz > {var['riz_max_par_semaine']}"))
    starches = {rc.starch for rc in calcs if rc.starch}
    if len(starches) < var["feculents_distincts_min_par_semaine"]:
        out.append(Issue("erreur", "feculents", wid,
                         f"{len(starches)} féculent(s) principal(aux) distinct(s) < {var['feculents_distincts_min_par_semaine']}"))
    for key, attr, label in (("cruciferes_min_par_semaine", "cruciferes", "recettes avec crucifères"),
                             ("ala_min_par_semaine", "ala", "recettes avec source d'ALA")):
        need = var.get(key)
        n = sum(bool(getattr(rc, attr)) for rc in calcs)
        if need and n < need:
            out.append(Issue("erreur", key.replace("_min_par_semaine", ""), wid, f"{n} {label} < {need}"))
    need = var.get("especes_vegetales_min_par_semaine")
    if need:
        n = len(set().union(*[rc.vegetaux for rc in calcs])) if calcs else 0
        if n < need:
            out.append(Issue("erreur", "diversite", wid, f"{n} aliments végétaux distincts < {need} (approximation)"))
    return out


def _check_classeur(ctx: Context, complete: bool) -> list:
    p, var = ctx.profile, ctx.profile["variete"]
    out = []
    n_weeks, target = len(ctx.weeks), p["projet"]["semaines"]
    if n_weeks > target:
        out.append(Issue("erreur", "semaines", "classeur", f"{n_weeks} semaines > {target}"))
    elif n_weeks < target:
        out.append(Issue("erreur" if complete else "alerte", "semaines", "classeur", f"{n_weeks} semaines sur {target}"))
    counts = {c: 0 for c in categories(p)}
    for rc in ctx.calcs.values():
        if rc.categorie in counts:
            counts[rc.categorie] += 1
    for c in categories(p) if p["repartition"] is not None else ():
        goal = p["repartition"].get(c, 0)
        if counts[c] > goal or (complete and counts[c] != goal):
            out.append(Issue("erreur", "repartition", "classeur", f"{c} : {counts[c]} recettes, cible {goal}"))
    if var["especes_poisson_uniques"]:
        seen: dict = {}
        for rid, rc in ctx.calcs.items():
            for sp in rc.especes_poisson:
                if sp in seen:
                    out.append(Issue("erreur", "espece_doublon", rid, f"« {sp} » déjà en {seen[sp]}"))
                seen.setdefault(sp, rid)
    cuisines: dict = {}
    for w in ctx.weeks:
        cz = norm(w.get("cuisine"))
        if cz and cz in cuisines and var.get("cuisines_distinctes", True):
            out.append(Issue("erreur", "cuisine_doublon", w.get("semaine", "?"), f"« {w.get('cuisine')} » déjà en {cuisines[cz]}"))
        cuisines.setdefault(cz, w.get("semaine"))
    ind = [rid for rid, rc in ctx.calcs.items() if rc.industriels]
    if var["substituts_industriels_max"] is not None and len(ind) > var["substituts_industriels_max"]:
        out.append(Issue("erreur", "substituts", "classeur", f"{len(ind)} recettes ({', '.join(ind)}) > {var['substituts_industriels_max']}"))
    return out


def load_plan(workdir: Path) -> dict:
    path = workdir / "plan.yaml"
    if not path.exists():
        raise BinderError(f"fichier manquant : {path}")
    return load_yaml(path)
