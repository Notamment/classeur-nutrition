"""Rendu Markdown du classeur et de l'audit, à partir des données calculées."""
from __future__ import annotations

import datetime as dt
from dataclasses import replace

from core import fmt_qty, week_order
from profiles import nutrition_mode, nutrition_targets, requirement, week_title

CAT_LABEL = {"vegetarien": "végétarien", "poisson": "poisson", "viande": "viande", "mixte": "MIXTE"}
STATUS = ("conforme", "estimation", "non vérifié", "non conforme")


STARCH_LABEL = {"ble": "blé", "legumineuse": "légumineuses", "riz": "riz"}


def starch_label(s) -> str:
    return STARCH_LABEL.get(s, str(s).replace("_", " ")) if s else "—"


def esc(s) -> str:
    return str(s if s is not None else "").replace("|", "/").replace("\n", " ")


def fr(x: float, nd: int = 0) -> str:
    if x is None:
        return "—"
    return f"{x:.{nd}f}".replace(".", ",")


def r10(x: float) -> str:
    if x is None:
        return "—"
    return f"{int(round(x / 10.0) * 10)}"


def qty_text(ln) -> str:
    u = ln.unit
    if u == "pincee":
        return f"{ln.qty:g} pincée"
    if u == "piece":
        return f"{fmt_qty(ln.qty, u)} ({fmt_qty(ln.grams, 'g')})"
    if u in ("cac", "cas"):
        return f"{ln.qty:g} c. à {'c.' if u == 'cac' else 's.'} ({fmt_qty(ln.grams, 'g')})"
    return fmt_qty(ln.qty, u)


def label_for(food, profile) -> str:
    labels = profile["labels"]
    if food.categorie and food.categorie in labels:
        return labels[food.categorie]
    if food.categorie in (labels.get("exceptions_bio") or []):
        return "conventionnel accepté"
    if food.nature == "autre":
        return ""
    label = labels.get("defaut", "")
    return "" if label == "aucun label exigé" else label


def store_for(food, stores: dict) -> str:
    shops = stores.get("magasins") or []
    for s in shops:
        if food.rayon in (s.get("rayons") or []):
            return s.get("nom") or ""
    main = [s for s in shops if s.get("role") == "principal"]
    return (main[0].get("nom") or "") if main else ""


# ---------------------------------------------------------------- blocs

def recipe_block(ctx, rid: str, issues: list) -> list:
    r, rc, p = ctx.recipes[rid], ctx.calcs[rid], ctx.profile
    nutrition = nutrition_mode(p) != "desactive"
    cat = CAT_LABEL.get(rc.categorie, rc.categorie)
    if rc.especes_poisson:
        cat += f" ({', '.join(rc.especes_poisson)})"
    head = [r.get("nom_fr") and f"*{esc(r['nom_fr'])}*", esc(r.get("origine")), cat, esc(r.get("service")),
            f"actif {r.get('temps_actif_min', '?')} min · total {r.get('temps_total_min', '?')} min",
            esc(", ".join(r.get("appareils") or []))]
    out = [f"### {rid} — {esc(r.get('nom'))}", "", " · ".join(x for x in head if x), ""]
    metadata = ctx.adaptations.get(rid, {})
    if metadata.get("difficulte"):
        out += [f"**Difficulté estimée** — {metadata['difficulte']} ; " + " ; ".join(esc(s) for s in metadata["raisons"]) + ".", ""]
    elif p["repas"].get("difficulte_max") or r.get("execution"):
        out += ["**Difficulté** — non vérifiable ; voir l'audit.", ""]
    out += ["| Ingrédient | Quantité | État |", "|---|---|---|"]
    for ln in rc.lines:
        out.append(f"| {esc(ln.food.nom)} | {qty_text(ln)} | {ln.etat} |")
    out += ["", "**Étapes**", ""]
    out += [f"{i}. {esc(s)}" for i, s in enumerate(r.get("etapes") or [], start=1)]
    out += ["", f"- **Poids estimé / portion** — {r10(rc.poids_pp)} g servis."]
    if nutrition:
        contrib = " · ".join(f"{esc(n)} {fr(g)} g" for n, g in rc.contributions())
        out.append(f"- **Estimations / portion** — {fr(rc.prot_pp)} g de protéines · {r10(rc.kcal_pp)} kcal.")
        if rc.prot_pp is not None:
            out.append(f"- **Apports protéiques** — {contrib}.")
        if rc.prot_pp is None or rc.kcal_pp is None:
            out.append("- **Données manquantes** — — signifie non calculable ; aucun total partiel présenté comme complet.")
    leg = f"oui, {fr(rc.legumes_g_pp)} g cuits/portion" if rc.has_legumes else "non"
    soja = ", ".join(rc.soja) if rc.soja else "non"
    if rc.soja_condiment:
        soja += f" ; condiment : {', '.join(rc.soja_condiment)}"
    out.append(f"- **Légumineuses** — {leg}. **Soja** — {esc(soja)}.")
    iron = rc.fer + rc.fer_vegetal
    if nutrition:
        out.append(f"- **Fer + vitamine C** — fer : {esc(', '.join(iron) or 'aucun')} ; "
                   f"vitamine C : {esc(', '.join(rc.vitc) or 'aucune')}.")
    if nutrition and p["nutrition"].get("note_tanins") and rc.fer_vegetal:
        out.append("- **Note** — thé/café à distance de ce repas (fer végétal).")
    if r.get("authenticite"):
        out.append(f"- **Authenticité** — {esc(r['authenticite'])}")
    if r.get("adaptation"):
        out.append(f"- **Adaptation** — {esc(r['adaptation'])}")
    if r.get("gamelle"):
        out.append(f"- **Gamelle** — {esc(r['gamelle'])}")
    alts = ctx.alts.get(rid) or []
    if alts:
        out += ["", "**Alternatives poisson** (achats non inclus)", "",
                "| Poisson | Quantité | " + ("Prot./portion | kcal | " if nutrition else "") + "Poids servi | Note |",
                "|---|---|" + ("---:|---:|" if nutrition else "") + "---:|---|"]
        for a in alts:
            if "erreur" in a:
                out.append(f"| {esc(a['nom'])} | — | " + ("— | — | " if nutrition else "") + f"— | {esc(a['erreur'])} |")
                continue
            limits = [("prot_pp", "proteines_g_par_portion"), ("poids_pp", "poids_servi_g_par_portion"),
                      ("kcal_pp", "kcal_par_portion")]
            bad = any(p["repas"].get(key) and (a[field] is None or not p["repas"][key][0] <= a[field] <= p["repas"][key][1])
                      for field, key in limits if key == "poids_servi_g_par_portion" or nutrition_targets(p))
            flag = " [à ajuster]" if bad else ""
            macros = f"{fr(a['prot_pp'])} g | {r10(a['kcal_pp'])} | " if nutrition else ""
            out.append(f"| {esc(a['nom'])}{flag} | {a['qte']} | {macros}{r10(a['poids_pp'])} g | {esc(a['note'])} |")
    refs = r.get("references") or {}
    nut = "foods.csv" + (f" — provisoire : {', '.join(rc.placeholders)}" if rc.placeholders else "")
    if alts:
        out.append("")
    out.append(f"- **Références** — culinaire : {esc(refs.get('culinaire') or 'non renseignée')}"
               + (f" ; nutrition : {esc(nut)}" if nutrition else "") + ".")
    errs = [i for i in issues if i.where == rid and i.level == "erreur"]
    if errs:
        out.append("- **Non conforme** — " + " ; ".join(f"{i.code} : {esc(i.msg)}" for i in errs) + ".")
    return out + [""]


def week_blocks(ctx, w, shop, issues) -> list:
    wid = w.get("semaine")
    order = week_order(w)
    nutrition = nutrition_mode(ctx.profile) != "desactive"
    out = [f"## Semaine {wid} — {esc(week_title(w))}", "", f"**Saison** — {esc(w.get('saison') or 'non renseignée')}", "",
           "**Ordre de préparation**", "", "| Jour | ID | Plat | Motif | Achat différé |", "|---:|---|---|---|---|"]
    late = {i.where: i.msg.split(" : ", 1)[-1] for i in issues if i.code == "fragile"}
    for d, rid in enumerate(order, start=1):
        r = ctx.recipes.get(rid, {})
        out.append(f"| {d} | {rid} | {esc(r.get('nom'))} | {esc(r.get('motif_ordre'))} | {esc(late.get(rid, ''))} |")
    out.append("")
    for rid in order:
        if rid in ctx.calcs:
            out += recipe_block(ctx, rid, issues)
    out += [f"### Récapitulatif {wid}", "",
            "| ID | Recette | Catégorie | " + ("Prot./portion | kcal | " if nutrition else "") + "Poids servi | Légumineuses | Soja |",
            "|---|---|---|" + ("---:|---:|" if nutrition else "") + "---:|---|---|"]
    for rid in order:
        rc = ctx.calcs.get(rid)
        if rc is None:
            continue
        leg = f"oui, {fr(rc.legumes_g_pp)} g" if rc.has_legumes else "non"
        macros = f"{fr(rc.prot_pp)} g | {r10(rc.kcal_pp)} | " if nutrition else ""
        out.append(f"| {rid} | {esc(rc.nom)} | {CAT_LABEL.get(rc.categorie)} | {macros}"
                   f"{r10(rc.poids_pp)} g | {leg} | {'oui' if rc.soja else 'non'} |")
    out += ["", *adaptation_block(ctx, w), *shopping_block(ctx, shop), ""]
    return out


def adaptation_block(ctx, week) -> list:
    if not ctx.catalogs:
        return []
    recipes = [ctx.recipes[rid] for rid in week_order(week) if rid in ctx.recipes]
    active_rules = any(ctx.profile["repas"].get(key) is not None for key in ("difficulte_max", "duree_active_max_min"))
    active_rules |= any(ctx.profile["variete"].get(key) is not None for key in (
        "recettes_distinctes_min_par_semaine", "ingredient_principal_max_par_semaine",
        "techniques_distinctes_min_par_semaine", "repetition_plat_max"))
    if not active_rules and not any(r.get("execution") or r.get("plat_id") or r.get("ingredients_principaux") for r in recipes):
        return []
    out = [f"### Adaptation {week['semaine']}", "",
           "| Recette | Temps actif (min) | Difficulté estimée | Ingrédients principaux déclarés |",
           "|---|---:|---|---|"]
    for r in recipes:
        metadata = ctx.adaptations.get(r["id"], {})
        principal = [ctx.foods[f].nom if f in ctx.foods else f for f in r.get("ingredients_principaux", [])]
        out.append(f"| {esc(r['nom'])} | {fr(r.get('temps_actif_min'), 1)} | {metadata.get('difficulte') or '—'} | "
                   f"{esc(', '.join(principal) or '—')} |")
    complete = len(recipes) == ctx.profile["projet"]["recettes_par_semaine"]
    distinct = str(len({r["plat_id"] for r in recipes})) if complete and all(r.get("plat_id") for r in recipes) else "non vérifiable"
    out += ["", f"Plats distincts : {distinct}, selon les identifiants déclarés. — signifie non renseigné ou non vérifiable.", ""]
    return out


def shopping_block(ctx, shop) -> list:
    p, stores = ctx.profile, ctx.stores
    out = [f"### Courses {shop.semaine}", ""]
    rayon = None
    for sl in shop.lines:
        if sl.food.rayon != rayon:
            if rayon is not None:
                out.append("")
            rayon = sl.food.rayon
            out += [f"**{rayon}**", "",
                    "| Article et forme | Affectation comestible | Besoin comestible | Stock mobilisé | Besoin net comestible | Achat | Reste comestible |",
                    "|---|---|---:|---|---:|---|---|"]
        u = sl.food.unite_achat
        name = sl.food.nom
        lab = label_for(sl.food, p)
        if lab:
            name += f" — {lab}"
        if sl.formes:
            name += f" (achat : {'; '.join(sl.formes)})"
        shop_name = store_for(sl.food, stores)
        if shop_name:
            name += f" · {shop_name}"
        if sl.negligeable:
            alloc = ", ".join(a[0] for a in sl.allocations)
            stock = "présent" if sl.stock_statut != "absent" else "—"
            out.append(f"| {esc(name)} | {alloc} | négligeable | {stock} | — | {'0' if stock == 'présent' else 'petite quantité'} | — |")
            continue
        alloc = " + ".join(f"{rid} {shown}" for rid, _, shown in sl.allocations)
        if not sl.valide:
            stock, net, achat, reste = "à vérifier", "à corriger", "à corriger", "—"
        elif sl.stock_statut == "inconnu":
            stock, net = "présent, à vérifier", "à vérifier"
            achat = f"à vérifier ; jusqu'à {fmt_qty(sl.achat_si_insuffisant, u)} si insuffisant"
            reste = "—"
        else:
            stock = fmt_qty(sl.mobilise, u) if sl.stock_statut == "connu" else "—"
            net = fmt_qty(sl.net, u)
            packs = f" ({' + '.join(fmt_qty(x, u) for x in sl.packs)})" if len(sl.packs) > 1 else ""
            achat = (fmt_qty(sl.achat, u) + packs) if sl.achat > 0 else "0"
            if sl.achat_override and sl.achat > 0:
                achat += f" brut (déficit converti : {fmt_qty(sl.achat_brut, u)})"
            if sl.sans_marge:
                reste = "sans marge"
            elif sl.reste > 0:
                reste = fmt_qty(sl.reste, u) + (" → stock" if sl.reste_reporte else " à écouler")
            elif sl.stock_apres:
                reste = f"{fmt_qty(sl.stock_apres, u)}" + (" en stock" if sl.food.report_ok else " à écouler")
            else:
                reste = "—"
        out.append(f"| {esc(name)} | {alloc} | {fmt_qty(sl.besoin, u)} | {stock} | {net} | {achat} | {reste} |")
    out += ["", budget_text(ctx, shop)]
    return out


def budget_text(ctx, shop) -> str:
    cur = ctx.profile["budget"].get("devise", "EUR")
    if shop.prix_manquants and len(shop.prix_manquants) == len([s for s in shop.lines if not s.negligeable]):
        return f"**Budget {shop.semaine}** — non vérifié, non chiffré : aucun prix de référence applicable (`prix_eur`)."
    txt = (f"**Budget {shop.semaine}** — coût consommé {fr(shop.cout_consomme, 2)} {cur} ; montant caisse "
           f"connu {fr(shop.montant_caisse, 2)} {cur}, dont épicerie conservable {fr(shop.part_epicerie, 2)} {cur}.")
    if shop.prix_manquants:
        txt += f" Prix manquants ({len(shop.prix_manquants)}) : {', '.join(shop.prix_manquants)} — montants incomplets."
    if not shop.budget_verifiable:
        txt += " **Budget non vérifié** ; sous-totaux connus seulement."
    if shop.stocks_inconnus:
        txt += f" Achats conditionnels selon le stock : {', '.join(shop.stocks_inconnus)}."
    for issue in ctx.issues:
        if issue.code == "budget_depasse" and issue.where == shop.semaine:
            txt += f" **Plafond dépassé : {issue.msg}.**"
    return txt


# ---------------------------------------------------------------- fin de document

def index_block(ctx) -> list:
    nutrition = nutrition_mode(ctx.profile) != "desactive"
    out = ["## Index global", "",
           "| Semaine | ID | Recette | Catégorie | " + ("Prot./portion | " if nutrition else "") + "Féculent principal | Légumineuses | Soja |",
           "|---|---|---|---|" + ("---:|" if nutrition else "") + "---|---|---|"]
    for w in ctx.weeks:
        for rid in week_order(w):
            rc = ctx.calcs.get(rid)
            if rc:
                macros = f"{fr(rc.prot_pp)} g | " if nutrition else ""
                out.append(f"| {w.get('semaine')} {esc(week_title(w))} | {rid} | {esc(rc.nom)} | "
                           f"{CAT_LABEL.get(rc.categorie)} | {macros}{esc(starch_label(rc.starch))} | "
                           f"{'oui' if rc.has_legumes else 'non'} | {'oui' if rc.soja else 'non'} |")
    return out + [""]


def shared_block(ctx, shops, final_stock) -> list:
    use: dict = {}
    for ws in shops:
        for sl in ws.lines:
            if sl.negligeable:
                continue
            u = use.setdefault(sl.food.id, {"food": sl.food, "weeks": [], "besoin": 0.0, "achats": {}})
            u["weeks"].append(ws.semaine)
            u["besoin"] += sl.besoin
            form = "; ".join(sl.formes) or "forme de référence"
            u["achats"][form] = u["achats"].get(form, 0.0) + sl.achat
    out = ["## Épicerie partagée", "",
           "| Ingrédient | Semaines | Besoin total | Stock initial | Achats prévus | Reste conservable |",
           "|---|---|---:|---|---:|---|"]
    from shopping import initial_stock
    init = initial_stock(ctx.pantry, ctx.foods)
    rows = [u for u in use.values() if len(u["weeks"]) > 1]
    for u in sorted(rows, key=lambda x: x["food"].nom):
        f, unit = u["food"], u["food"].unite_achat
        st = "inconnu" if f.id in init and init[f.id] is None else (fmt_qty(init[f.id], unit) if f.id in init else "—")
        left = final_stock.get(f.id)
        rest = "à vérifier" if left is None and f.id in final_stock else (fmt_qty(left, unit) if left else "—")
        achats = "; ".join(f"{fmt_qty(qty, unit)} ({esc(form)})" for form, qty in u["achats"].items())
        out.append(f"| {esc(f.nom)} | {', '.join(u['weeks'])} | {fmt_qty(u['besoin'], unit)} | {st} | "
                   f"{achats} | {rest if f.report_ok else 'non reportable'} |")
    if not rows:
        out.append("| — | — | — | — | — | — |")
    return out + [""]


def hypotheses_block(ctx, shops) -> list:
    out = ["## Hypothèses et éléments non vérifiés", ""]
    ph = sorted({n for rc in ctx.calcs.values() for n in rc.placeholders})
    if ph and nutrition_mode(ctx.profile) != "desactive":
        out.append(f"- Valeurs nutritionnelles **provisoires** (`source=placeholder`) : {', '.join(ph)}. "
                   "Remplacer par Ciqual ou l'étiquette (`build_foods.py`).")
    out.append("- Poids servis : estimés avec les rendements de `foods.csv` ou de la recette ; non pesés.")
    out.append("- Labels, origine, transport et disponibilité : exigences affichées, produits réels non vérifiés.")
    unknown = sorted({sl.food.nom for ws in shops for sl in ws.lines if sl.stock_statut == "inconnu"})
    if unknown:
        out.append(f"- Stock présent, quantité inconnue : {', '.join(unknown)}.")
    missing = sorted({n for ws in shops for n in ws.prix_manquants})
    if missing:
        out.append(f"- Prix de référence manquants ({len(missing)}) : budget incomplet.")
    if ctx.pantry:
        out.append("- Déductions de stock valables pour la première rotation uniquement.")
    if ctx.catalogs and any(r.get("execution") or r.get("plat_id") or r.get("ingredients_principaux") for r in ctx.recipes.values()):
        out.append("- Difficulté : maximum du niveau des techniques et de la simultanéité déclarées ; temps et variété dépendent des métadonnées renseignées, sans lecture automatique des étapes.")
    if ctx.catalogs and (ctx.profile["aliments"]["familles_exclues"] or ctx.profile["aliments"]["familles_a_eviter"]):
        out.append("- Familles culinaires : correspondances de la base et des tags renseignés, avec leurs familles parentes ; composition réelle et traces non vérifiées.")
    return out + [""]


def audit_rows(ctx, shops) -> list:
    if ctx.profile.get("version") == 2:
        return audit_rows_v2(ctx, shops)
    p, iss = ctx.profile, ctx.issues
    errs = lambda *codes: [i for i in iss if i.level == "erreur" and i.code in codes]
    alerts = lambda *codes: [i for i in iss if i.level == "alerte" and i.code in codes]
    calcs = list(ctx.calcs.values())
    placeholders = any(rc.placeholders for rc in calcs)

    def st(errors, ok="conforme"):
        return "non conforme" if errors else ok

    def ids(lst):
        return ", ".join(sorted({i.where for i in lst})) or "aucune"

    rows = []
    data_errors = [i for i in iss if i.level == "erreur" and
                   (i.code.startswith(("schema_", "foods_")) or i.code in
                    {"aliment_inconnu", "etat", "conversion", "nutrition_absente", "achat", "unite", "portions"})]
    rows.append(("Validité des données", "schémas, unités et références valides",
                 f"écarts : {ids(data_errors)}", st(data_errors)))
    pr = p["projet"]
    e = errs("semaines", "recettes", "id_semaine", "id_recette", "id_doublon", "ordre")
    rows.append(("Semaines, recettes, portions",
                 f"{pr['semaines']} × {pr['recettes_par_semaine']} × {pr['portions_par_recette']}",
                 f"{len(ctx.weeks)} sem., {len(calcs)} recettes", st(e)))
    counts = {c: sum(rc.categorie == c for rc in calcs) for c in ("vegetarien", "poisson", "viande")}
    e = errs("repartition", "categorie_mixte")
    rows.append(("Répartition végétarien / poisson / viande",
                 " / ".join(str(p["repartition"].get(c, 0)) for c in counts),
                 " / ".join(str(v) for v in counts.values()), st(e)))
    if calcs:
        prot = [rc.prot_pp for rc in calcs]
        poids = [rc.poids_pp for rc in calcs]
        e = errs("proteines", "poids_servi", "kcal")
        rows.append(("Protéines et poids servi",
                     f"{p['repas']['proteines_g_par_portion']} g ; {p['repas']['poids_servi_g_par_portion']} g",
                     f"prot. {fr(min(prot))}–{fr(max(prot))} g ; poids {r10(min(poids))}–{r10(max(poids))} g ; "
                     f"exceptions : {ids(e)}", st(e, "estimation")))
    leg = [rc for rc in calcs if rc.has_legumes]
    e = errs("legumineuses_g", "legumineuses_consecutives")
    rows.append(("Légumineuses : quantité et alternance", f"{p['legumineuses']['g_cuits_par_portion']} g cuits ; non consécutives",
                 f"{len(leg)} recettes ; écarts : {ids(e)}", st(e)))
    e = errs("duree", "materiel")
    tmax = max((r.get("temps_total_min") or 0 for r in ctx.recipes.values()), default=0)
    rows.append(("Temps et équipement", f"≤ {p['repas']['duree_totale_max_min']} min ; {', '.join(p['materiel'])}",
                 f"max déclaré {tmax} min ; écarts : {ids(e)}", st(e, "estimation")))
    e = errs("riz", "feculents", "substituts")
    rows.append(("Riz, féculents, substituts",
                 f"riz ≤ {p['variete']['riz_max_par_semaine']}/sem. ; ≥ {p['variete']['feculents_distincts_min_par_semaine']} féculents ; "
                 f"substituts ≤ {p['variete']['substituts_industriels_max']}",
                 f"écarts : {ids(e)}", st(e)))
    e = errs("cuisine_exclue", "cuisine_doublon")
    adapt = sum(bool(r.get("adaptation")) for r in ctx.recipes.values())
    rows.append(("Cuisines et authenticité", "distinctes, non exclues, plats nommés",
                 f"{', '.join(esc(w.get('cuisine')) for w in ctx.weeks)} ; {adapt} adaptation(s) déclarée(s)",
                 st(e, "non vérifié")))
    a = alerts("fragile")
    rows.append(("Saison et conservation", "produits de saison ; fragiles en début de semaine",
                 f"fragiles tardifs : {ids(a)}", "non vérifié"))
    e = errs("sel", "fer_vitc", "aliment_exclu", "espece_doublon")
    rows.append(("Labels, sel, fer + vitamine C, exclusions", "règles du profil",
                 f"écarts : {ids(e)} ; labels des produits réels non vérifiés", st(e, "non vérifié")))
    unknown = sum(sl.stock_statut == "inconnu" for ws in shops for sl in ws.lines)
    e = errs("achat_formes", "achat_conversion", "ordre", "id_doublon") + data_errors
    rows.append(("Courses et stock", "besoins comestibles ; achats bruts ; stock suivi", f"{unknown} stock(s) à vérifier ; écarts : {ids(e)}",
                 st(e, "conforme" if not unknown else "estimation")))
    missing = sum(len(ws.prix_manquants) for ws in shops)
    e = errs("budget_depasse")
    cap = p["budget"]["plafond_eur_semaine"]
    rows.append(("Budget", f"montant caisse ; plafond {cap if cap is not None else 'non fixé'} EUR",
                 f"{missing} prix manquant(s) ; dépassements : {ids(e)}",
                 st(e, "non vérifié" if data_errors or any(not ws.budget_verifiable for ws in shops) else "estimation")))
    rows.append(("Sources et méthode", "Ciqual / étiquettes ; contrôle automatisé",
                 f"binder.py ; données provisoires : {'oui' if placeholders else 'non'}",
                 "estimation"))
    if data_errors:
        rows = [(a, b, c, "non vérifié" if s in ("conforme", "estimation") else s) for a, b, c, s in rows]
    return rows


def audit_rows_v2(ctx, shops) -> list:
    """Même politique que les contrôles : une option inactive n'est pas validée."""
    from schemas import CONFIGURABLE_RULES
    p, issues = ctx.profile, ctx.issues
    rows = []
    data_incomplete = len(ctx.calcs) != len(ctx.declared) or any(
        i.level == "erreur" and (i.code.startswith(("schema_", "foods_")) or i.code in
        {"aliment_inconnu", "etat", "conversion", "achat", "unite", "portions", "id_doublon", "metadata_recette", "technique_inconnue"}) for i in issues)

    def add(label, expected, codes, active=True, fallback="conforme", policy=None):
        matching = [i for i in issues if i.code in codes]
        status = "non demandé" if not active else fallback
        if active:
            if any(i.level == "erreur" for i in matching):
                status = "non conforme"
            elif any(i.preference_failed for i in matching):
                status = "préférence non satisfaite"
            elif matching or data_incomplete:
                status = "non vérifié"
        if policy:
            expected = f"{expected} ({'préférence' if requirement(p, policy) == 'preference' else 'impératif'})"
        result = "; ".join(f"{i.where} : {i.msg}" for i in matching) or ("aucun écart détecté" if active else "—")
        rows.append((label, expected, result, status))

    structural = {i.code for i in issues if i.code not in CONFIGURABLE_RULES and i.level == "erreur"}
    add("Validité des données et structure", "schémas, unités, identifiants, semaines et recettes", structural)
    add("Régime et exclusions", f"{p['alimentation']['regime']} ; {p['aliments']['exclus']}",
        {"regime", "aliment_exclu", "alternative_invalide"}, fallback="selon la base d'aliments")
    add("Ingrédients à éviter", p["aliments"]["a_eviter"], {"aliment_a_eviter"}, bool(p["aliments"]["a_eviter"]))
    add("Familles exclues", p["aliments"]["familles_exclues"], {"famille_exclue", "famille_inconnue", "foods_famille"},
        bool(p["aliments"]["familles_exclues"]), fallback="selon la base d'aliments")
    add("Familles à éviter", p["aliments"]["familles_a_eviter"], {"famille_a_eviter", "famille_inconnue", "foods_famille"},
        bool(p["aliments"]["familles_a_eviter"]), fallback="selon la base d'aliments")
    rows.append(("Nutrition", nutrition_mode(p), "valeurs absentes affichées —" if nutrition_mode(p) != "desactive" else "aucun calcul nutritionnel",
                 "non demandé" if nutrition_mode(p) == "desactive" else
                 "non vérifié" if any(i.code == "nutrition_absente" for i in issues) else "estimation"))
    rules = {
        "repartition": ("Répartition", p["repartition"], p["repartition"] is not None),
        "poids_servi": ("Poids servi / portion", p["repas"]["poids_servi_g_par_portion"], p["repas"]["poids_servi_g_par_portion"] is not None),
        "duree": ("Temps total maximal", p["repas"]["duree_totale_max_min"], p["repas"]["duree_totale_max_min"] is not None),
        "duree_active": ("Temps actif maximal", p["repas"]["duree_active_max_min"], p["repas"]["duree_active_max_min"] is not None),
        "difficulte": ("Difficulté maximale", p["repas"]["difficulte_max"], p["repas"]["difficulte_max"] is not None),
        "legumineuses_g": ("Légumineuses / portion", p["legumineuses"]["g_cuits_par_portion"], p["legumineuses"]["g_cuits_par_portion"] is not None),
        "legumineuses_consecutives": ("Alternance des légumineuses", "non consécutives", not p["legumineuses"]["consecutives_autorisees"]),
        "sel": ("Sel ajouté", p["aliments"]["sans_sel_ajoute_si"], bool(p["aliments"]["sans_sel_ajoute_si"])),
    }
    if nutrition_targets(p):
        for code, key, label in (("proteines", "proteines_g_par_portion", "Protéines / portion"),
                                 ("kcal", "kcal_par_portion", "kcal / portion")):
            rules[code] = (label, p["repas"][key], p["repas"][key] is not None)
        rules["fer_vitc"] = ("Fer + vitamine C", p["nutrition"]["fer_vitamine_c"], p["nutrition"]["fer_vitamine_c"] != "non")
    for code, key, label in (
        ("riz", "riz_max_par_semaine", "Riz : maximum / semaine"),
        ("feculents", "feculents_distincts_min_par_semaine", "Féculents : minimum / semaine"),
        ("substituts", "substituts_industriels_max", "Substituts : maximum / classeur"),
        ("espece_doublon", "especes_poisson_uniques", "Espèces de poisson distinctes"),
        ("cuisine_doublon", "cuisines_distinctes", "Cuisines distinctes"),
        ("cruciferes", "cruciferes_min_par_semaine", "Crucifères : minimum / semaine"),
        ("ala", "ala_min_par_semaine", "Sources d'ALA : minimum / semaine"),
        ("diversite", "especes_vegetales_min_par_semaine", "Diversité végétale : minimum / semaine"),
        ("variete_plats", "recettes_distinctes_min_par_semaine", "Plats distincts : minimum / semaine"),
        ("ingredient_recurrent", "ingredient_principal_max_par_semaine", "Même ingrédient principal : maximum / semaine"),
        ("variete_techniques", "techniques_distinctes_min_par_semaine", "Techniques distinctes : minimum / semaine"),
        ("repetition_plat", "repetition_plat_max", "Même plat : maximum / classeur"),
    ):
        value = p["variete"][key]
        active = value is not None if code in ("riz", "substituts", "ingredient_recurrent", "repetition_plat") else bool(value)
        rules[code] = (label, value, active)
    for code, (label, expected, active) in rules.items():
        add(label, expected if expected is not None else "non fixé", {code}, active,
            "estimation" if code in {"proteines", "kcal", "poids_servi", "duree", "duree_active", "difficulte", "legumineuses_g"} else "conforme", code if active else None)
    add("Matériel", p["materiel"], {"materiel"}, p["materiel"] is not None)
    add("Organisation et authenticité", f"{p['projet']['organisation']} ; {p['projet']['authenticite']}",
        {"organisation", "authenticite", "cuisine_exclue"}, fallback="non vérifié")
    add("Courses et stock", "besoins, achats et stock réconciliés", {"achat_formes", "achat_conversion", "stock_etat", "stock_inconnu"},
        fallback="non vérifié" if any(s.incomplet or s.stocks_inconnus for s in shops) else "conforme")
    add("Budget", f"plafond {p['budget']['plafond_eur_semaine']} EUR" if p["budget"]["plafond_eur_semaine"] is not None else "plafond non fixé",
        {"budget_depasse", "budget_non_verifie"}, fallback="estimation", policy="budget_depasse" if p["budget"]["plafond_eur_semaine"] is not None else None)
    rows.append(("Saison, conservation et labels", "choix du profil", "vérification humaine des produits et du contenu", "non vérifié"))
    return rows


def audit_block(ctx, shops) -> list:
    out = ["## Audit final", "", "| Contrôle | Attendu | Résultat | Statut |", "|---|---|---|---|"]
    for row in audit_rows(ctx, shops):
        out.append("| " + " | ".join(esc(x) for x in row) + " |")
    errs = [i for i in ctx.issues if i.level == "erreur"]
    alerts = [i for i in ctx.issues if i.level == "alerte"]
    out += ["", f"**Écarts** — {len(errs)} erreur(s), {len(alerts)} alerte(s).", ""]
    for i in errs + alerts:
        out.append(f"- {i.level} · {i.where} · {i.code} — {esc(i.msg)}")
    return out + [""]


def stores_block(ctx) -> list:
    shops = ctx.stores.get("magasins") or []
    shops = [s for s in shops if s.get("nom")]
    if not shops:
        return []
    out = ["## Magasins", "", "| Magasin | Rôle | Adresse | Usage |", "|---|---|---|---|"]
    for s in shops:
        name = f"[{esc(s['nom'])}]({s['lien']})" if s.get("lien") else esc(s["nom"])
        out.append(f"| {name} | {esc(s.get('role'))} | {esc(s.get('adresse') or '—')} | {esc(s.get('usage') or '—')} |")
    ver = ctx.stores.get("verifie_le")
    out += ["", (f"Adresses vérifiées le {ver}." if ver else "Adresses non vérifiées.")
            + " Aucun stock, prix ni label garanti par magasin.", ""]
    return out


def render_classeur(ctx, shops, final_stock, extra_issues) -> str:
    p = ctx.profile
    issues = ctx.issues + [i for i in extra_issues if i not in ctx.issues]
    ctx = replace(ctx, issues=issues)
    errs = sum(i.level == "erreur" for i in issues)
    mois = ", ".join(p["projet"].get("mois") or []) or "mois non renseignés"
    out = [f"# {esc(p['projet']['titre'])}", "",
           f"{len(ctx.weeks)} semaine{'s' if len(ctx.weeks) > 1 else ''} · {mois} · {p['projet']['portions_par_recette']} portions par recette "
           f"({esc(p['projet']['usage'])}). Généré le {dt.date.today().isoformat()} par meal-binder.",
           "",
           ("> Poids = estimation calculée. " if nutrition_mode(p) == "desactive" else "> Protéines, kcal et poids = estimations calculées par script. ")
           + (f"**{errs} écart(s) non conforme(s)** : voir l'audit." if errs else "Aucun écart bloquant ; voir l'audit pour les points non vérifiés."),
           ""]
    if p.get("version") == 2:
        out += [f"**Configuration** — profil v2 ; préréglages : {esc(', '.join(p['prereglages']) or 'aucun')} ; "
                f"nutrition : {nutrition_mode(p)} ; régime : {p['alimentation']['regime']}.", ""]
    out += stores_block(ctx)
    shop_by_week = {ws.semaine: ws for ws in shops}
    for w in ctx.weeks:
        out += week_blocks(ctx, w, shop_by_week[w.get("semaine")], issues)
    out += index_block(ctx) + shared_block(ctx, shops, final_stock) + hypotheses_block(ctx, shops) + audit_block(ctx, shops)
    return "\n".join(out)


def render_audit(ctx, shops) -> str:
    out = [f"# Audit — {esc(ctx.profile['projet']['titre'])}", "",
           f"Généré le {dt.date.today().isoformat()} par meal-binder. Classeur non réécrit.", ""]
    out += index_block(ctx) + hypotheses_block(ctx, shops) + audit_block(ctx, shops)
    return "\n".join(out)
