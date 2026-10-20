"""Données, unités et calculs par recette. Seule dépendance externe : PyYAML."""
from __future__ import annotations

import copy
import csv
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

MIN_PYTHON = (3, 10)
if sys.version_info < MIN_PYTHON:
    sys.stderr.write(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} ou plus récent requis "
                     f"(version détectée : {sys.version.split()[0]}).\n")
    raise SystemExit(3)

import yaml  # noqa: E402
from schemas import (CATEGORIES, NATURES, RAYONS, STATES, UNITS, RECIPE, RECIPE_V2, POS_COUNT,
                     number, validate)


def utf8_stdio() -> None:
    """Force UTF-8 sur stdout/stderr : sous Windows, une sortie redirigée (agent, pipe) est en cp1252."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


SKILL_DIR = Path(__file__).resolve().parent.parent
FOODS_CSV = SKILL_DIR / "data" / "foods.csv"

MASS = {"g": 1.0, "kg": 1000.0}
VOLUME = {"ml": 1.0, "cl": 10.0, "l": 1000.0, "cac": 5.0, "cas": 15.0}
G_PER_CAC_DRY = 2.5          # cuillère à café d'un produit sec sans densité

DEFAULT_PROFILE = {
    "version": 1,
    "projet": {"titre": "CLASSEUR", "semaines": 6, "recettes_par_semaine": 5,
               "portions_par_recette": 2, "usage": "Dîner + gamelle du lendemain",
               "mois": [], "zone_saison": "France métropolitaine"},
    "repas": {"proteines_g_par_portion": [32, 40], "poids_servi_g_par_portion": [450, 580],
              "duree_totale_max_min": 45, "kcal_par_portion": None, "conservation_gamelle_h": 24},
    "repartition": {"vegetarien": 22, "poisson": 5, "viande": 3},
    "legumineuses": {"g_cuits_par_portion": [80, 120], "consecutives_autorisees": False,
                     "soja_compte": False, "epices_associees": []},
    "variete": {"riz_max_par_semaine": 2, "feculents_distincts_min_par_semaine": 3,
                "substituts_industriels_max": 1, "especes_poisson_uniques": True,
                "alternatives_par_poisson": 2, "cruciferes_min_par_semaine": None,
                "ala_min_par_semaine": None, "especes_vegetales_min_par_semaine": None,
                "jour_max_fragile": 2, "cuisines_exclues": []},
    "nutrition": {"fer_vitamine_c": "chaque_repas", "note_tanins": False},
    "aliments": {"exclus": [], "sans_sel_ajoute_si": ["fromage_sale"]},
    "labels": {"defaut": "bio", "exceptions_bio": []},
    "materiel": ["plaque"],
    "plaques": 2,
    "bureau": [],
    "budget": {"plafond_eur_semaine": None, "devise": "EUR"},
}


@dataclass
class Issue:
    level: str          # "erreur" (non conforme) | "alerte" (à vérifier)
    code: str
    where: str
    msg: str
    kind: str | None = None
    requirement: str | None = None

    def __post_init__(self):
        if self.kind is None:
            self.kind = "internal" if self.code == "erreur_interne" else "violation" if self.level == "erreur" or self.requirement == "preference" else "information"
        if self.requirement is None and self.level == "erreur" and self.kind != "internal":
            self.requirement = "imperative"

    @property
    def preference_failed(self):
        return self.requirement == "preference" and self.kind == "violation"

    @property
    def preference_unknown(self):
        return self.requirement == "preference" and self.kind == "unknown"

    def line(self) -> str:
        return f"{self.level.upper():7} {self.where:<9} {self.code}: {self.msg}"


class BinderError(Exception):
    """Erreur bloquante : fichier manquant ou illisible."""


class DataError(BinderError):
    """Entrée lisible mais invalide ; aucun calcul ne doit continuer."""

    def __init__(self, issues):
        self.issues = issues
        super().__init__(" ; ".join(i.line() for i in issues))


def schema_issues(value, schema, where, code):
    return [Issue("erreur", code, where, f"{path}: {msg}")
            for path, msg in validate(value, schema, where)]


def _unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"clé dupliquée : {key}")
        out[key] = value
    return out


class _YamlLoader(yaml.SafeLoader):
    pass


def _yaml_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    return _unique_pairs((loader.construct_object(k, deep=deep), loader.construct_object(v, deep=deep))
                         for k, v in node.value)


_YamlLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _yaml_mapping)


# ---------------------------------------------------------------- chargement

def load_yaml(path: Path):
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.load(f, Loader=_YamlLoader)
        if not isinstance(data, dict):
            raise ValueError("la racine doit être un objet non vide")
        return data
    except (OSError, UnicodeError, yaml.YAMLError, ValueError, TypeError) as e:
        raise BinderError(f"YAML illisible dans {path.name} : {e}") from e


def load_json(path: Path):
    def invalid_constant(value):
        raise ValueError(f"nombre non fini : {value}")
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f, parse_constant=invalid_constant, object_pairs_hook=_unique_pairs)
    except (OSError, UnicodeError, ValueError) as e:
        raise BinderError(f"JSON illisible dans {path.name} : {e}") from e


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_profile(workdir: Path) -> dict:
    from profiles import load_resolved
    return load_resolved(workdir).profile


def _num(v):
    v = (v or "").strip()
    n = float(v) if v else None
    if n is not None and not number(n):
        raise ValueError("nombre non fini")
    return n


@dataclass
class Food:
    id: str
    nom: str
    rayon: str
    nature: str
    categorie: str
    tags: set
    prot: float | None
    kcal: float | None
    etat_ref: str
    g_par_piece: float | None
    densite: float | None
    rendement: float
    unite_achat: str
    conditionnements: list
    report_ok: bool
    prix_eur: float | None
    source: str

    def tag_values(self, prefix: str) -> list:
        return [t.split(":", 1)[1] for t in self.tags if t.startswith(prefix + ":")]

    def has(self, tag: str) -> bool:
        return tag in self.tags

    @property
    def placeholder(self) -> bool:
        return self.source.startswith("placeholder")


def _read_foods(path: Path, issues: list) -> dict:
    foods = {}
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        expected = {"id", "nom", "rayon", "nature", "categorie", "tags", "prot_g_100g", "kcal_100g",
                    "etat_ref", "g_par_piece", "densite_g_ml", "rendement", "unite_achat",
                    "conditionnements", "report_ok", "prix_eur", "source"}
        headers = reader.fieldnames or []
        if set(headers) != expected or len(headers) != len(set(headers)):
            issues.append(Issue("erreur", "foods_colonnes", path.name,
                                "en-tête invalide : reprendre les colonnes de foods.csv, sans doublon"))
            return foods
        for n, row in enumerate(reader, start=2):
            where = f"{path.name}:{n}"
            if None in row or any(v is None for v in row.values()):
                issues.append(Issue("erreur", "foods_ligne", where, "nombre de colonnes incohérent"))
                continue
            try:
                food = Food(
                    id=row["id"].strip(), nom=row["nom"].strip(), rayon=row["rayon"].strip(),
                    nature=row["nature"].strip(), categorie=(row.get("categorie") or "").strip(),
                    tags={t.strip() for t in (row.get("tags") or "").split("|") if t.strip()},
                    prot=_num(row.get("prot_g_100g")), kcal=_num(row.get("kcal_100g")),
                    etat_ref=row["etat_ref"].strip(), g_par_piece=_num(row.get("g_par_piece")),
                    densite=_num(row.get("densite_g_ml")),
                    rendement=_num(row["rendement"]) if row.get("rendement", "").strip() else 1.0,
                    unite_achat=(row.get("unite_achat") or "g").strip(),
                    conditionnements=[float(x) for x in (row.get("conditionnements") or "").split("|") if x.strip()],
                    report_ok=(row.get("report_ok") or "0").strip() == "1",
                    prix_eur=_num(row.get("prix_eur")), source=(row.get("source") or "placeholder").strip(),
                )
            except (KeyError, ValueError, AttributeError, TypeError) as e:
                issues.append(Issue("erreur", "foods_ligne", where, f"ligne illisible ({e})"))
                continue
            start = len(issues)
            if not re.fullmatch(r"[a-z][a-z0-9_]*", food.id) or not food.nom:
                issues.append(Issue("erreur", "foods_identite", where, "id ou nom invalide"))
            if food.id in foods:
                issues.append(Issue("erreur", "foods_doublon", where, f"{food.id}: id dupliqué dans ce fichier"))
            for key, value in (("prot_g_100g", food.prot), ("kcal_100g", food.kcal), ("prix_eur", food.prix_eur)):
                if value is not None and (not number(value) or value < 0):
                    issues.append(Issue("erreur", "foods_nombre", where, f"{food.id}: {key} doit être positif ou nul"))
            for key, value in (("g_par_piece", food.g_par_piece), ("densite_g_ml", food.densite), ("rendement", food.rendement)):
                if value is not None and (not number(value) or value <= 0):
                    issues.append(Issue("erreur", "foods_nombre", where, f"{food.id}: {key} doit être strictement positif"))
            if any(not number(s) or s <= 0 or not s.is_integer() for s in food.conditionnements):
                issues.append(Issue("erreur", "foods_conditionnements", where, "tailles entières strictement positives requises"))
            if (row.get("report_ok") or "0").strip() not in ("0", "1"):
                issues.append(Issue("erreur", "foods_report", where, "report_ok doit être 0 ou 1"))
            if food.nature not in NATURES:
                issues.append(Issue("erreur", "foods_nature", where, f"{food.id}: nature « {food.nature} » inconnue"))
            if food.etat_ref not in STATES:
                issues.append(Issue("erreur", "foods_etat", where, f"{food.id}: état « {food.etat_ref} » inconnu"))
            if food.unite_achat not in ("g", "ml", "piece"):
                issues.append(Issue("erreur", "foods_unite", where, f"{food.id}: unite_achat « {food.unite_achat} »"))
            if food.rayon not in RAYONS:
                issues.append(Issue("erreur", "foods_rayon", where, f"{food.id}: rayon « {food.rayon} » hors liste"))
            if food.unite_achat == "piece" and food.g_par_piece is None:
                issues.append(Issue("erreur", "foods_piece", where, f"{food.id}: g_par_piece requis"))
            if len(issues) == start:
                foods[food.id] = food
    return foods


def load_foods(workdir: Path | None = None) -> tuple[dict, list]:
    issues: list = []
    try:
        foods = _read_foods(FOODS_CSV, issues)
        if workdir and (workdir / "foods.local.csv").exists():
            foods.update(_read_foods(workdir / "foods.local.csv", issues))
    except (OSError, UnicodeError, csv.Error) as e:
        raise BinderError(f"CSV des aliments illisible : {e}") from e
    from sources import apply_sources
    return apply_sources(foods, workdir), issues


# ---------------------------------------------------------------- unités

def to_grams(food: Food, qty: float, unit: str) -> float:
    """Masse comestible pesée, en grammes."""
    if not number(qty) or qty < 0:
        raise ValueError("quantité finie et positive ou nulle requise")
    if unit == "pincee":
        return 0.0
    if unit in MASS:
        return qty * MASS[unit]
    if unit in ("cac", "cas") and food.densite is None:
        return qty * G_PER_CAC_DRY * (3 if unit == "cas" else 1)
    if unit in VOLUME:
        return qty * VOLUME[unit] * (food.densite or 1.0)
    if unit == "piece":
        if not food.g_par_piece:
            raise ValueError(f"{food.id} : g_par_piece manquant pour l'unité « piece »")
        return qty * food.g_par_piece
    raise ValueError(f"unité inconnue « {unit} »")


def to_base(food: Food, qty: float, unit: str) -> float:
    """Quantité dans l'unité d'achat de l'aliment (g, ml ou pièce)."""
    if not number(qty) or qty < 0:
        raise ValueError("quantité finie et positive ou nulle requise")
    if unit == "pincee":
        return 0.0
    if food.unite_achat == "piece":
        if unit == "piece":
            return qty
        if not food.g_par_piece:
            raise ValueError(f"{food.id} : g_par_piece manquant pour convertir en pièces")
        return to_grams(food, qty, unit) / food.g_par_piece
    if food.unite_achat == "ml":
        if unit in VOLUME:
            return qty * VOLUME[unit]
        return to_grams(food, qty, unit) / (food.densite or 1.0)
    return to_grams(food, qty, unit)


def fmt_qty(value: float, unit: str) -> str:
    if not number(value) or value < 0:
        raise ValueError("quantité affichée invalide")
    if unit in ("g", "ml") and value >= 1000 and value % 100 == 0:
        big = {"g": "kg", "ml": "l"}[unit]
        return f"{value / 1000:.15g} {big}".replace(".", ",")
    # 15 chiffres significatifs : conserve les décimales utiles, élimine le bruit
    # des additions binaires (0.1 + 0.2), sans arrondir une petite quantité à zéro.
    return f"{value:.15g} {'pc' if unit == 'piece' else unit}".replace(".", ",")


def unit_label(food: Food) -> str:
    return "pièce(s)" if food.unite_achat == "piece" else food.unite_achat


# ---------------------------------------------------------------- recette

@dataclass
class LineCalc:
    food: Food
    qty: float
    unit: str
    etat: str
    grams: float
    served: float
    prot: float | None
    kcal: float | None
    base: float                 # besoin dans l'unité d'achat
    achat_base: float | None    # quantité à acheter si différente du besoin comestible
    achat_forme: str | None
    negligible: bool
    achat_prix: float | None = None
    achat_conditionnements: list | None = None


@dataclass
class RecipeCalc:
    rid: str
    nom: str
    portions: int
    lines: list
    prot_pp: float | None = 0.0
    kcal_pp: float | None = 0.0
    poids_pp: float = 0.0
    categorie: str | None = None
    legumes_g_pp: float = 0.0
    soja: list = field(default_factory=list)
    soja_condiment: list = field(default_factory=list)
    starch: str | None = None
    starches: set = field(default_factory=set)
    riz: bool = False
    especes_poisson: list = field(default_factory=list)
    fer: list = field(default_factory=list)
    fer_vegetal: list = field(default_factory=list)
    vitc: list = field(default_factory=list)
    ala: list = field(default_factory=list)
    cruciferes: list = field(default_factory=list)
    fragiles: list = field(default_factory=list)
    industriels: list = field(default_factory=list)
    tag_foods: dict = field(default_factory=dict)   # tag -> [noms d'aliments]
    placeholders: list = field(default_factory=list)
    vegetaux: set = field(default_factory=set)

    @property
    def has_legumes(self) -> bool:
        return self.legumes_g_pp > 0

    def contributions(self, top: int = 3) -> list:
        """Principales sources de protéines par portion : [(nom, g)], reste inclus."""
        by_food: dict = {}
        for ln in self.lines:
            if ln.prot is None:
                continue
            by_food[ln.food.nom] = by_food.get(ln.food.nom, 0.0) + ln.prot / self.portions
        ranked = sorted(by_food.items(), key=lambda kv: -kv[1])
        head = ranked[:top]
        rest = sum(v for _, v in ranked[top:])
        if rest > 0.05:
            head.append(("reste", rest))
        return head


def compute_recipe(r: dict, foods: dict, portions: int, *, version=1,
                   nutrition_mode="cibles") -> tuple[RecipeCalc | None, list]:
    rid = str(r.get("id", "?")) if isinstance(r, dict) else "?"
    issues = schema_issues(r, RECIPE_V2 if version == 2 else RECIPE, rid, "schema_recette")
    issues += schema_issues(portions, POS_COUNT, rid, "portions")
    if issues:
        return None, issues

    rc = RecipeCalc(rid=rid, nom=r.get("nom", "?"), portions=portions, lines=[])
    natures = set()
    starch_g: dict = {}
    for i, ing in enumerate(r["ingredients"], start=1):
        fid = ing.get("food")
        food = foods.get(fid)
        where = rid
        if food is None:
            issues.append(Issue("erreur", "aliment_inconnu", where, f"ingrédient {i} « {fid} » absent de foods.csv / foods.local.csv"))
            continue
        unit = ing.get("unite")
        qty = ing.get("qte")
        if unit not in UNITS:
            issues.append(Issue("erreur", "unite", where, f"{fid}: unité « {unit} » inconnue"))
            continue
        if unit == "pincee" and (food.rayon != "Épices" or food.nature not in ("vegetal", "autre")):
            issues.append(Issue("erreur", "unite", where, f"{fid}: pincée réservée aux épices et au sel"))
            continue
        etat = ing.get("etat", food.etat_ref)
        if unit != "pincee" and etat != food.etat_ref:
            issues.append(Issue("erreur", "etat", where,
                                f"{fid}: pesé « {etat} » mais valeurs de la base à l'état « {food.etat_ref} » ; utiliser un autre aliment"))
            continue
        try:
            grams = to_grams(food, qty, unit)
            base = to_base(food, qty, unit)
        except ValueError as e:
            issues.append(Issue("erreur", "conversion", where, str(e)))
            continue
        achat = ing.get("achat")
        achat_base = None
        if achat:
            try:
                permitted = {"g": set(MASS), "ml": set(VOLUME), "piece": {"piece"}}[food.unite_achat]
                if achat["unite"] not in permitted or unit == "pincee":
                    raise ValueError("unité du produit brut incompatible avec l'unité d'achat")
                achat_base = to_base(food, achat["qte"], achat["unite"])
                if achat_base < base:
                    raise ValueError("achat brut inférieur au besoin comestible")
            except (KeyError, ValueError) as e:
                issues.append(Issue("erreur", "achat", where, f"{fid}: bloc « achat » invalide ({e})"))
                continue
        rendement = ing.get("rendement", food.rendement)
        negligible = unit == "pincee"
        if nutrition_mode != "desactive" and not negligible and (food.prot is None or food.kcal is None):
            issues.append(Issue("erreur" if version == 1 else "alerte", "nutrition_absente", where,
                                f"{fid}: protéines ou kcal absents de la base ; valeur inconnue, jamais zéro", kind="unknown"))
        prot = (0.0 if negligible else None if food.prot is None else grams * food.prot / 100)
        kcal = (0.0 if negligible else None if food.kcal is None else grams * food.kcal / 100)
        if nutrition_mode == "desactive":
            prot = kcal = None
        served = grams * rendement
        if not all(number(v) for v in (grams, base, served, prot, kcal) if v is not None):
            issues.append(Issue("erreur", "conversion", where, f"{fid}: résultat non fini"))
            continue
        rc.lines.append(LineCalc(food, qty, unit, etat, grams, served, prot, kcal,
                                 base, achat_base, (achat or {}).get("forme"), negligible,
                                 (achat or {}).get("prix_eur"), (achat or {}).get("conditionnements")))
        if negligible:
            continue
        natures.add(food.nature)
        if food.placeholder and food.nom not in rc.placeholders:
            rc.placeholders.append(food.nom)
        if food.has("legumineuse"):
            rc.legumes_g_pp += served / portions
        for tag, bucket in (("soja", rc.soja), ("soja_condiment", rc.soja_condiment), ("fer", rc.fer),
                            ("fer_vegetal", rc.fer_vegetal), ("vitc", rc.vitc), ("ala", rc.ala),
                            ("crucifere", rc.cruciferes), ("fragile", rc.fragiles),
                            ("substitut_industriel", rc.industriels)):
            if food.has(tag) and food.nom not in bucket:
                bucket.append(food.nom)
        for name in food.tag_values("feculent"):
            starch_g[name] = starch_g.get(name, 0.0) + grams
        for sp in food.tag_values("espece"):
            if sp not in rc.especes_poisson:
                rc.especes_poisson.append(sp)
        if food.nature == "vegetal":
            rc.vegetaux.add(food.id)
        for t in food.tags:
            names = rc.tag_foods.setdefault(t, [])
            if food.nom not in names:
                names.append(food.nom)

    if any(i.level == "erreur" for i in issues):
        return None, issues
    rc.prot_pp = (math.fsum(ln.prot for ln in rc.lines) / portions
                  if all(ln.prot is not None for ln in rc.lines) else None)
    rc.kcal_pp = (math.fsum(ln.kcal for ln in rc.lines) / portions
                  if all(ln.kcal is not None for ln in rc.lines) else None)
    rc.poids_pp = (sum(ln.served for ln in rc.lines) + r.get("eau_retenue_g", 0)) / portions
    if not all(number(v) for v in (rc.prot_pp, rc.kcal_pp, rc.poids_pp, rc.legumes_g_pp) if v is not None):
        return None, issues + [Issue("erreur", "conversion", rid, "total non fini")]
    if "viande" in natures and "poisson" in natures:
        rc.categorie = "mixte"
        if version == 1:
            issues.append(Issue("erreur", "categorie_mixte", rid, "viande et poisson dans la même recette"))
    elif "viande" in natures:
        rc.categorie = "viande"
    elif "poisson" in natures:
        rc.categorie = "poisson"
    else:
        rc.categorie = "vegetarien"
    if starch_g:
        rc.starches = set(starch_g)
        rc.starch = max(starch_g, key=starch_g.get)
        rc.riz = "riz" in starch_g
    return rc, issues


def compute_alternatives(r: dict, rc: RecipeCalc, foods: dict, *, version=1, nutrition_mode="cibles") -> list:
    """Remplace le poisson principal par chaque alternative et recalcule."""
    fish = [ln for ln in rc.lines if ln.food.nature == "poisson"]
    if not fish:
        return []
    main = max(fish, key=lambda ln: ln.grams)
    out = []
    for alt in r.get("alternatives_poisson") or []:
        food = foods.get(alt.get("food"))
        if food is None:
            out.append({"nom": alt.get("food"), "erreur": "aliment inconnu"})
            continue
        if food.nature != "poisson":
            out.append({"nom": food.nom, "erreur": "l'alternative doit être un poisson"})
            continue
        replacement = {k: v for k, v in alt.items() if k != "note"}
        candidate = copy.deepcopy(r)
        candidate.pop("alternatives_poisson", None)
        candidate["ingredients"][rc.lines.index(main)] = replacement
        calc, issues = compute_recipe(candidate, foods, rc.portions, version=version, nutrition_mode=nutrition_mode)
        if calc is None or any(i.level == "erreur" for i in issues):
            out.append({"nom": food.nom, "erreur": "; ".join(i.msg for i in issues)})
            continue
        out.append({"nom": food.nom, "qte": fmt_qty(to_base(food, alt["qte"], alt["unite"]), food.unite_achat),
                    "prot_pp": calc.prot_pp, "kcal_pp": calc.kcal_pp, "poids_pp": calc.poids_pp,
                    "food": food.id,
                    "especes": food.tag_values("espece"), "note": alt.get("note", ""),
                    "placeholder": food.placeholder})
    return out


# ---------------------------------------------------------------- dossier de travail

def load_weeks(workdir: Path) -> list:
    wdir = workdir / "weeks"
    if not wdir.exists():
        return []
    return [load_json(p) for p in sorted(wdir.glob("S*.json"))]


def week_order(week: dict) -> list:
    ids = [r.get("id") for r in week.get("recettes", [])]
    order = week.get("ordre")
    return order if isinstance(order, list) and sorted(order) == sorted(ids) and len(set(order)) == len(order) else ids
