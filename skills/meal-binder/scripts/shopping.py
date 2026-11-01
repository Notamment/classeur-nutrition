"""Courses par semaine, suivi du stock (première rotation), emballages et budget."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from core import RAYONS, DataError, Issue, fmt_qty, schema_issues, to_base, week_order
from schemas import PANTRY_ENTRY, arr, number

EPS = 1e-6


@dataclass
class ShopLine:
    food: object
    allocations: list = field(default_factory=list)   # [(id recette, qté unité d'achat, texte affiché)]
    formes: list = field(default_factory=list)
    besoin: float = 0.0
    negligeable: bool = True
    stock_statut: str = "absent"      # absent | connu | inconnu
    mobilise: float = 0.0
    net: float = 0.0
    achat: float = 0.0
    packs: list = field(default_factory=list)
    reste: float = 0.0
    reste_reporte: bool = False
    achat_si_insuffisant: float = 0.0
    stock_apres: float | None = None   # stock restant après cette semaine (unité d'achat)
    achat_ratio: float = 1.0          # unités brutes par unité comestible de référence
    achat_override: bool = False
    prix_achat: float | None = None
    formats_achat: list = field(default_factory=list)
    achat_brut: float = 0.0           # déficit comestible converti, avant emballages
    valide: bool = True

    @property
    def sans_marge(self) -> bool:
        return (self.valide and self.besoin > 0 and self.stock_statut != "inconnu" and abs(self.reste) < EPS
                and (self.stock_apres or 0) < EPS)

    def unit_price(self) -> float | None:
        price = self.prix_achat if self.achat_override else self.food.prix_eur
        if price is None:
            return None
        return price if self.food.unite_achat == "piece" else price / 1000


@dataclass
class WeekShop:
    semaine: str
    lines: list
    cout_consomme: float = 0.0
    montant_caisse: float = 0.0
    part_epicerie: float = 0.0
    prix_manquants: list = field(default_factory=list)
    stocks_inconnus: list = field(default_factory=list)
    incomplet: bool = False

    @property
    def budget_verifiable(self):
        return not (self.prix_manquants or self.stocks_inconnus or self.incomplet)


def choose_packs(net: float, sizes: list) -> tuple[float, list]:
    """Plus petit total ≥ net avec les conditionnements donnés, puis le moins de paquets."""
    if not number(net) or net < 0:
        raise ValueError("besoin fini et positif ou nul requis")
    if any(not number(s) or s <= 0 or int(s) != s for s in sizes):
        raise ValueError("conditionnements entiers strictement positifs requis")
    if net == 0:
        return 0.0, []
    sizes_i = sorted({int(s) for s in sizes})
    if not sizes_i:
        return float(math.ceil(net)), []
    # Réduction par le PGCD : même optimum, mémoire indépendante de l'unité
    # choisie pour représenter un paquet (par exemple kg exprimés en grammes).
    scale = math.gcd(*sizes_i)
    sizes_i = [s // scale for s in sizes_i]
    target = math.ceil(net / scale)
    limit = target + max(sizes_i)
    if limit > 1_000_000:
        raise ValueError("conditionnements trop complexes : réduire le besoin ou simplifier les formats")
    count = [math.inf] * (limit + 1)
    prev = [0] * (limit + 1)
    count[0] = 0
    for x in range(1, limit + 1):
        for s in sizes_i:
            if s <= x and count[x - s] + 1 < count[x]:
                count[x], prev[x] = count[x - s] + 1, s
    for x in range(target, limit + 1):
        if count[x] < math.inf:
            packs, y = [], x
            while y:
                packs.append(prev[y] * scale)
                y -= prev[y]
            return float(x * scale), sorted(packs, reverse=True)
    raise ValueError("aucune combinaison de conditionnements trouvée")


def initial_stock(entries: list, foods: dict) -> dict:
    """{id: quantité en unité d'achat, ou None si présente mais inconnue}."""
    stock = {}
    invalid = schema_issues(entries, arr(PANTRY_ENTRY), "stock", "schema_stock")
    if invalid:
        raise DataError(invalid)
    for e in entries:
        food = foods.get(e.get("id"))
        if food is None or (e.get("etat") and e["etat"] != food.etat_ref):
            continue
        q = e.get("quantite")
        if q is None:
            stock[food.id] = None
            continue
        try:
            amount = to_base(food, q, e.get("unite", food.unite_achat))
            if food.id not in stock or stock[food.id] is not None:
                stock[food.id] = stock.get(food.id, 0.0) + amount
        except ValueError:
            stock[food.id] = None
    return stock


def build_shopping(ctx) -> tuple[list, dict, list]:
    """Retourne (semaines, stock final, alertes)."""
    stock = initial_stock(ctx.pantry, ctx.foods)
    weeks_out, issues = [], []
    for week_index, w in enumerate(ctx.weeks):
        wid = w.get("semaine", "?")
        if week_index:
            for fid in list(stock):
                if not ctx.foods[fid].report_ok:
                    if stock[fid] is None or stock[fid] > 0:
                        issues.append(Issue("alerte", "stock_non_reportable", wid,
                                            f"{ctx.foods[fid].nom} : reste antérieur non mobilisé (report_ok=0)"))
                    del stock[fid]
        lines: dict = {}
        specs = {}
        for rid in dict.fromkeys(week_order(w)):
            rc = ctx.calcs.get(rid)
            if rc is None:
                continue
            for ln in rc.lines:
                sl = lines.setdefault(ln.food.id, ShopLine(food=ln.food))
                qty = ln.base
                u = ln.food.unite_achat
                shown = fmt_qty(qty, u)
                sl.allocations.append((rid, qty, shown))
                sl.besoin = math.fsum(a[1] for a in sl.allocations)
                if not ln.negligible:
                    sl.negligeable = False
                    override = ln.achat_base is not None
                    ratio = ln.achat_base / ln.base if override else 1.0
                    formats = (ln.achat_conditionnements or []) if override else ln.food.conditionnements
                    price = ln.achat_prix if override else ln.food.prix_eur
                    spec = (override, ratio, ln.achat_forme, tuple(sorted(formats)), price)
                    if ln.food.id in specs and spec != specs[ln.food.id]:
                        if sl.valide:
                            issues.append(Issue("erreur", "achat_formes", wid,
                                                f"{ln.food.nom} : formes, ratios, prix ou formats d'achat incompatibles ; utiliser des ids distincts"))
                        sl.valide = False
                    else:
                        specs[ln.food.id] = spec
                        sl.achat_ratio, sl.achat_override = ratio, override
                        sl.prix_achat, sl.formats_achat = price, list(formats)
                if ln.achat_forme and ln.achat_forme not in sl.formes:
                    sl.formes.append(ln.achat_forme)
        ws = WeekShop(semaine=wid, lines=[],
                      incomplet=any(rid not in ctx.calcs for rid in week_order(w)))
        for sl in sorted(lines.values(), key=lambda s: (RAYONS.index(s.food.rayon) if s.food.rayon in RAYONS else 99, s.food.nom)):
            fid = sl.food.id
            if not sl.valide:
                ws.incomplet = True
                ws.lines.append(sl)
                continue
            if fid in stock and stock[fid] is None:
                sl.stock_statut = "inconnu"
                if not sl.negligeable:
                    ws.stocks_inconnus.append(sl.food.nom)
            elif fid in stock:
                sl.stock_statut = "connu"
                sl.mobilise = min(stock[fid], sl.besoin)
                stock[fid] -= sl.mobilise
            sl.net = 0.0 if sl.stock_statut == "inconnu" else max(0.0, sl.besoin - sl.mobilise)
            try:
                if sl.stock_statut == "inconnu" and not sl.negligeable:
                    sl.achat_si_insuffisant = choose_packs(sl.besoin * sl.achat_ratio, sl.formats_achat)[0]
                sl.achat_brut = sl.net * sl.achat_ratio
                if sl.net > 0:
                    sl.achat, sl.packs = choose_packs(sl.achat_brut, sl.formats_achat)
                    sl.reste = max(0.0, sl.achat / sl.achat_ratio - sl.net)
                if sl.food.report_ok and sl.reste > 0:
                    stock[fid] = (stock.get(fid) or 0.0) + sl.reste
                    sl.reste_reporte = True
            except ValueError as exc:
                sl.valide, ws.incomplet = False, True
                issues.append(Issue("erreur", "achat_conversion", wid, f"{sl.food.nom} : {exc}"))
            if sl.stock_statut == "connu":
                sl.stock_apres = stock.get(fid)
            elif sl.negligeable and sl.stock_statut == "absent":
                issues.append(Issue("alerte", "petite_quantite", wid,
                                    f"{sl.food.nom} : quantité négligeable, à acheter si absent du placard"))
                ws.stocks_inconnus.append(sl.food.nom)
            price = sl.unit_price()
            if price is None:
                if not sl.negligeable:
                    ws.prix_manquants.append(sl.food.nom)
            else:
                ws.cout_consomme += sl.besoin * sl.achat_ratio * price
                ws.montant_caisse += sl.achat * price
                if sl.food.report_ok:
                    ws.part_epicerie += sl.achat * price
            ws.lines.append(sl)
        issues += check_budget(ws, ctx.profile)
        weeks_out.append(ws)
    return weeks_out, stock, issues


def check_budget(shop: WeekShop, profile: dict) -> list:
    """Contrôle du montant caisse ; un sous-total connu est une borne inférieure."""
    issues = []
    cap = profile["budget"]["plafond_eur_semaine"]
    if cap is not None and shop.montant_caisse > cap + 1e-9:
        issues.append(Issue("erreur", "budget_depasse", shop.semaine,
                            f"montant caisse connu {shop.montant_caisse:.2f} EUR > plafond {cap:g} EUR"))
    if not shop.budget_verifiable:
        why = []
        if shop.prix_manquants:
            why.append(f"{len(shop.prix_manquants)} prix manquant(s)")
        if shop.stocks_inconnus:
            why.append(f"{len(shop.stocks_inconnus)} stock(s) de quantité inconnue")
        if shop.incomplet:
            why.append("courses incomplètes ou incohérentes")
        issues.append(Issue("alerte", "budget_non_verifie", shop.semaine, "; ".join(why), kind="unknown"))
    from profiles import apply_requirements
    return apply_requirements(issues, profile)
