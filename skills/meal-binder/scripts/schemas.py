"""Schémas partagés des entrées, sans coercition implicite ni dépendance supplémentaire.

Le validateur applique uniquement les règles définies ici ; ce n'est pas un moteur
JSON Schema général. Les contraintes métier restent dans checks.py.
"""
from __future__ import annotations

import datetime
import copy
import math
import re

UNITS = {"g", "kg", "ml", "cl", "l", "cac", "cas", "piece", "pincee"}
STATES = {"cru", "sec", "cuit", "egoutte", "net"}
NATURES = {"vegetal", "laitier", "oeuf", "poisson", "viande", "autre"}
CATEGORIES = ("vegetarien", "poisson", "viande")
RAYONS = [
    "Fruits et légumes", "Herbes fraîches", "Poissonnerie", "Boucherie", "Crèmerie",
    "Œufs", "Produits végétariens", "Boulangerie", "Épicerie salée", "Conserves",
    "Huiles et condiments", "Épices", "Épicerie sucrée", "Produits du monde", "Surgelés",
]


def number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def obj(properties, required=(), extra=False):
    return {"kind": "object", "properties": properties, "required": required, "extra": extra}


def arr(items, minimum=0, maximum=None):
    return {"kind": "array", "items": items, "minimum": minimum, "maximum": maximum}


def num(minimum=0, positive=False, integer=False):
    return {"kind": "integer" if integer else "number", "minimum": minimum, "positive": positive}


def enum(values):
    return {"kind": "string", "enum": values}


def nullable(schema):
    return {**schema, "nullable": True}


TEXT = {"kind": "string"}
BOOL = {"kind": "boolean"}
STRINGS = arr(TEXT)
POSITIVE = num(positive=True)
COUNT = num(integer=True)
POS_COUNT = num(positive=True, integer=True)
RANGE = {**arr(num(), 2, 2), "ordered": True}
FOOD_ID = {**TEXT, "pattern": r"[a-z][a-z0-9_]*"}
WEEK_ID = {**TEXT, "pattern": r"S\d{2}"}
RECIPE_ID = {**TEXT, "pattern": r"S\d{2}-R\d{2}"}

PROFILE = obj({
    "version": {**COUNT, "values": [1]},
    "projet": obj({"titre": TEXT, "semaines": POS_COUNT, "recettes_par_semaine": POS_COUNT,
                   "portions_par_recette": POS_COUNT, "usage": TEXT, "mois": STRINGS,
                   "zone_saison": TEXT}),
    "repas": obj({"proteines_g_par_portion": RANGE, "poids_servi_g_par_portion": RANGE,
                  "duree_totale_max_min": POSITIVE, "kcal_par_portion": nullable(RANGE),
                  "conservation_gamelle_h": POSITIVE}),
    "repartition": obj({c: COUNT for c in CATEGORIES}),
    "legumineuses": obj({"g_cuits_par_portion": RANGE, "consecutives_autorisees": BOOL,
                         "soja_compte": BOOL, "epices_associees": arr(FOOD_ID)}),
    "variete": obj({"riz_max_par_semaine": COUNT, "feculents_distincts_min_par_semaine": COUNT,
                    "substituts_industriels_max": COUNT, "especes_poisson_uniques": BOOL,
                    "alternatives_par_poisson": COUNT, "cruciferes_min_par_semaine": nullable(COUNT),
                    "ala_min_par_semaine": nullable(COUNT), "especes_vegetales_min_par_semaine": nullable(COUNT),
                    "jour_max_fragile": nullable(POS_COUNT), "cuisines_exclues": STRINGS}),
    "nutrition": obj({"fer_vitamine_c": enum(["chaque_repas", "si_fer_vegetal", "non"]), "note_tanins": BOOL}),
    "aliments": obj({"exclus": arr(FOOD_ID), "sans_sel_ajoute_si": STRINGS}),
    "labels": obj({"defaut": TEXT, "exceptions_bio": STRINGS}, extra=TEXT),
    "materiel": STRINGS, "plaques": COUNT, "bureau": STRINGS,
    "budget": obj({"plafond_eur_semaine": nullable(num()), "devise": enum(["EUR"])}),
})
# Les profils partiels sont fusionnés avec DEFAULT_PROFILE avant cette validation.
for _section in PROFILE["properties"].values():
    if _section.get("kind") == "object":
        _section["required"] = tuple(_section["properties"])
PROFILE["required"] = tuple(PROFILE["properties"])

# Seules ces contraintes métier peuvent devenir des préférences. Schémas,
# conversions, exclusions et régime ne sont jamais déclassés.
CONFIGURABLE_RULES = (
    "proteines", "kcal", "poids_servi", "duree", "repartition", "legumineuses_g",
    "legumineuses_consecutives", "riz", "feculents", "substituts", "espece_doublon",
    "cruciferes", "ala", "diversite", "cuisine_doublon", "fer_vitc", "sel", "budget_depasse",
    "difficulte", "duree_active", "variete_plats", "repetition_plat", "ingredient_recurrent", "variete_techniques",
)
DIFFICULTIES = ("facile", "intermediaire", "avancee")
SELECTION_CRITERIA = ("budget", "temps_actif", "difficulte", "variete")
PROFILE_V2 = copy.deepcopy(PROFILE)
P2 = PROFILE_V2["properties"]
P2["version"]["values"] = [2]
P2["prereglages"] = arr(FOOD_ID)
P2["exigences"] = obj({key: enum(["imperative", "preference"]) for key in CONFIGURABLE_RULES})
P2["alimentation"] = obj({"regime": enum(["libre", "vegetarien", "vegetalien", "pescetarien"])}, ("regime",))
P2["projet"]["properties"].update({"organisation": enum(["libre", "cuisines", "themes"]),
                                    "authenticite": enum(["libre", "documentee"])})
P2["projet"]["required"] = tuple(P2["projet"]["properties"])
P2["repartition"] = nullable(obj({c: COUNT for c in (*CATEGORIES, "mixte")}, CATEGORIES))
for key in ("proteines_g_par_portion", "poids_servi_g_par_portion", "duree_totale_max_min"):
    P2["repas"]["properties"][key] = nullable(P2["repas"]["properties"][key])
P2["legumineuses"]["properties"]["g_cuits_par_portion"] = nullable(RANGE)
for key in ("riz_max_par_semaine", "substituts_industriels_max"):
    P2["variete"]["properties"][key] = nullable(COUNT)
P2["variete"]["properties"]["cuisines_distinctes"] = BOOL
P2["variete"]["required"] = tuple(P2["variete"]["properties"])
P2["nutrition"]["properties"]["mode"] = enum(["desactive", "information", "cibles"])
P2["nutrition"]["required"] = tuple(P2["nutrition"]["properties"])
P2["aliments"]["properties"]["a_eviter"] = arr(FOOD_ID)
P2["aliments"]["required"] = tuple(P2["aliments"]["properties"])
P2["materiel"] = nullable(STRINGS)
P2["plaques"] = nullable(COUNT)
P2["repas"]["properties"].update({"duree_active_max_min": nullable(num()),
                                   "difficulte_max": nullable(enum(DIFFICULTIES))})
P2["repas"]["required"] = tuple(P2["repas"]["properties"])
for key in ("recettes_distinctes_min_par_semaine", "ingredient_principal_max_par_semaine",
            "techniques_distinctes_min_par_semaine", "repetition_plat_max"):
    P2["variete"]["properties"][key] = nullable(COUNT)
P2["variete"]["required"] = tuple(P2["variete"]["properties"])
for key in ("familles_exclues", "familles_a_eviter"):
    P2["aliments"]["properties"][key] = arr(FOOD_ID)
P2["aliments"]["required"] = tuple(P2["aliments"]["properties"])
P2["selection"] = obj({"priorites": arr(enum(SELECTION_CRITERIA))}, ("priorites",))
PROFILE_V2["required"] = tuple(P2)


def profile_schema(profile):
    return PROFILE_V2 if isinstance(profile, dict) and profile.get("version") == 2 else PROFILE

PURCHASE = obj({"qte": POSITIVE, "unite": enum(UNITS - {"pincee"}), "forme": TEXT,
                "prix_eur": nullable(num()), "conditionnements": arr(POS_COUNT)},
               ("qte", "unite", "forme"))
INGREDIENT = obj({"food": FOOD_ID, "qte": POSITIVE, "unite": enum(UNITS), "etat": enum(STATES),
                  "rendement": POSITIVE, "achat": PURCHASE}, ("food", "qte", "unite"))
ALTERNATIVE = obj({**INGREDIENT["properties"], "note": TEXT}, ("food", "qte", "unite"))
RECIPE = obj({
    "id": RECIPE_ID, "nom": TEXT, "nom_fr": TEXT, "origine": TEXT, "service": TEXT,
    "temps_actif_min": num(), "temps_total_min": POSITIVE, "appareils": STRINGS,
    "motif_ordre": TEXT, "ingredients": arr(INGREDIENT, 1), "eau_retenue_g": num(),
    "sel_ajoute": BOOL, "etapes": arr(TEXT, 1), "authenticite": TEXT,
    "adaptation": nullable(TEXT), "gamelle": TEXT, "alternatives_poisson": arr(ALTERNATIVE),
    "references": obj({}, extra=TEXT),
}, ("id", "nom", "ingredients", "etapes", "temps_total_min", "gamelle", "authenticite", "sel_ajoute"))
RECIPE_V2 = copy.deepcopy(RECIPE)
RECIPE_V2["required"] = tuple(k for k in RECIPE["required"] if k not in ("gamelle", "authenticite"))
EXECUTION = obj({"techniques": arr(FOOD_ID, 1), "taches_simultanees": POS_COUNT},
                ("techniques", "taches_simultanees"))
ADAPTATION_FIELDS = {"plat_id": FOOD_ID, "ingredients_principaux": arr(FOOD_ID, 1, 3), "execution": EXECUTION}
RECIPE_V2["properties"].update(ADAPTATION_FIELDS)
WEEK = obj({"semaine": WEEK_ID, "cuisine": TEXT, "saison": TEXT, "ordre": arr(RECIPE_ID),
            "recettes": arr(obj({"id": RECIPE_ID}, ("id",), extra=True))},
           ("semaine", "cuisine", "recettes"))
PLAN_RECIPE = obj({"id": RECIPE_ID, "plat": TEXT, "categorie": enum(CATEGORIES),
                   "feculent": nullable(TEXT), "legumineuses": BOOL, "soja": BOOL,
                   "espece_poisson": TEXT, "substitut_industriel": BOOL},
                  ("id", "plat", "categorie", "legumineuses"))
PLAN = obj({"semaines": arr(obj({"id": WEEK_ID, "cuisine": TEXT, "recettes": arr(PLAN_RECIPE)},
                                ("id", "cuisine", "recettes")))}, ("semaines",))
WEEK_V2 = copy.deepcopy(WEEK)
WEEK_V2["required"] = ("semaine", "recettes")
WEEK_V2["properties"]["theme"] = TEXT
PLAN_V2 = copy.deepcopy(PLAN)
_plan_week = PLAN_V2["properties"]["semaines"]["items"]
_plan_week["required"] = ("id", "recettes")
_plan_week["properties"]["theme"] = TEXT
_plan_week["properties"]["recettes"]["items"]["properties"]["categorie"] = enum((*CATEGORIES, "mixte"))
_plan_week["properties"]["recettes"]["items"]["properties"].update({
    **ADAPTATION_FIELDS, "temps_actif_min": num(), "temps_total_min": POSITIVE})
PANTRY_ENTRY = obj({"id": FOOD_ID, "quantite": nullable(num()),
                    "unite": enum(UNITS - {"pincee"}), "etat": enum(STATES), "note": TEXT}, ("id", "quantite"))
PANTRY = obj({"stock": arr(PANTRY_ENTRY)}, ("stock",))
STORES = obj({"verifie_le": nullable({"kind": "date"}), "zone": nullable(TEXT),
              "magasins": arr(obj({"nom": nullable(TEXT), "role": enum(["principal", "specialise", "depannage"]),
                                   "adresse": nullable(TEXT), "lien": nullable(TEXT),
                                   "rayons": arr(enum(RAYONS)), "usage": nullable(TEXT)}, ("nom", "role"))),
              "notes": STRINGS})


def validate(value, schema, path=""):
    """Retourne [(chemin, explication)] sans modifier les valeurs d'entrée."""
    if value is None and schema.get("nullable"):
        return []
    kind = schema["kind"]
    valid = {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str) and bool(value.strip()),
        "boolean": lambda: type(value) is bool,
        "number": lambda: number(value),
        "integer": lambda: type(value) is int and number(value),
        "date": lambda: isinstance(value, (str, datetime.date)) and not isinstance(value, datetime.datetime),
    }[kind]()
    if not valid:
        return [(path, f"type attendu : {kind}, valeur non vide et finie")]
    errors = []
    if kind == "object":
        props, extra = schema["properties"], schema.get("extra", False)
        for key in schema.get("required", ()):
            if key not in value:
                errors.append((f"{path}.{key}", "champ obligatoire absent"))
        for key, val in value.items():
            child = f"{path}.{key}"
            if key in props:
                errors.extend(validate(val, props[key], child))
            elif extra is False:
                errors.append((child, "champ inconnu"))
            elif isinstance(extra, dict):
                errors.extend(validate(val, extra, child))
    elif kind == "array":
        if len(value) < schema["minimum"] or (schema["maximum"] is not None and len(value) > schema["maximum"]):
            errors.append((path, "longueur de liste invalide"))
        for i, item in enumerate(value):
            errors.extend(validate(item, schema["items"], f"{path}[{i}]"))
        if schema.get("ordered") and not errors and value[0] > value[1]:
            errors.append((path, "plage attendue : [minimum, maximum]"))
    elif kind in ("number", "integer"):
        if value < schema["minimum"] or (schema.get("positive") and value <= 0):
            errors.append((path, "valeur strictement positive attendue" if schema.get("positive") else "valeur négative interdite"))
    elif kind == "date":
        try:
            datetime.date.fromisoformat(str(value))
        except ValueError:
            errors.append((path, "date attendue : AAAA-MM-JJ"))
    if "enum" in schema and value not in schema["enum"]:
        errors.append((path, "valeur hors des choix autorisés"))
    if "values" in schema and value not in schema["values"]:
        errors.append((path, "version non prise en charge"))
    if schema.get("pattern") and not re.fullmatch(schema["pattern"], value):
        errors.append((path, "format d'identifiant invalide"))
    return errors
