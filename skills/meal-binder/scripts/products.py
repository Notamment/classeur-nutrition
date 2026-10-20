"""Produits et tarifs datés, distincts des aliments génériques."""
from __future__ import annotations

import datetime as dt
from dataclasses import replace
from pathlib import Path

from core import DataError, Issue, load_yaml, schema_issues
from schemas import BOOL, FOOD_ID, TEXT, POSITIVE, POS_COUNT, COUNT, arr, enum, nullable, num, obj

COMPOSITION = obj({"statut": enum(("documentee", "inconnue")), "familles": arr(FOOD_ID),
                   "allergenes_presents": arr(TEXT), "traces_declarees": arr(TEXT)},
                  ("statut", "familles", "allergenes_presents", "traces_declarees"))
PRODUCT = obj({"reference": TEXT, "fournisseur": TEXT, "source": TEXT,
               "observe_le": {"kind": "date"}, "prix_eur": nullable(num()),
               "prix_pour": POSITIVE, "unite": enum(("g", "ml", "piece")),
               "conditionnements": arr(POS_COUNT), "composition": COMPOSITION},
              ("reference", "fournisseur", "source", "observe_le", "prix_eur", "prix_pour", "unite", "conditionnements", "composition"))
CATALOG = obj({"version": {"kind": "integer", "minimum": 1, "values": [1]},
               "date_reference": {"kind": "date"}, "validite_jours": COUNT,
               "produits": obj({}, extra=PRODUCT)}, ("version", "date_reference", "validite_jours", "produits"))


def load_products(workdir):
    path = Path(workdir) / "products.yaml"
    if not path.exists():
        return None
    data = load_yaml(path)
    issues = schema_issues(data, CATALOG, path.name, "schema_produits")
    if issues:
        raise DataError(issues)
    for fid, item in data["produits"].items():
        issues += schema_issues(fid, FOOD_ID, path.name, "schema_produits")
        if item["composition"]["statut"] == "inconnue" and any(item["composition"][key] for key in (
                "familles", "allergenes_presents", "traces_declarees")):
            issues.append(Issue("erreur", "produit_composition", fid, "composition inconnue incompatible avec une liste déclarée certaine"))
    if issues:
        raise DataError(issues)
    return data


def apply_products(foods, workdir):
    data = load_products(workdir) if workdir else None
    if data is None:
        return foods, []
    issues = []
    reference = dt.date.fromisoformat(str(data["date_reference"]))
    for fid, product in data["produits"].items():
        if fid not in foods or product["unite"] != foods[fid].unite_achat:
            raise DataError([Issue("erreur", "produit_unite", fid, "aliment absent ou unité incompatible avec l'aliment générique")])
        observed = dt.date.fromisoformat(str(product["observe_le"]))
        if observed > reference:
            raise DataError([Issue("erreur", "produit_date", fid, "tarif daté après la date de référence")])
        expired = (reference - observed).days > data["validite_jours"]
        price = product["prix_eur"]
        if expired:
            price = None
            issues.append(Issue("alerte", "prix_perime", fid,
                                f"tarif du {observed} périmé à la date de référence {reference}", kind="unknown"))
        if price is not None:
            price = price / product["prix_pour"] * (1 if product["unite"] == "piece" else 1000)
        tags = set(foods[fid].tags)
        composition = product["composition"]
        if composition["statut"] == "documentee":
            tags.update("famille:" + family for family in composition["familles"])
        else:
            issues.append(Issue("alerte", "composition_inconnue", fid,
                                "composition et dérivés non vérifiés ; consulter le produit réel", kind="unknown"))
        foods[fid] = replace(foods[fid], prix_eur=price, conditionnements=product["conditionnements"], tags=tags)
    return foods, issues


def product_report(workdir, foods):
    data = load_products(workdir)
    if data is None:
        return {"version": 1, "date_reference": None, "produits": {}, "statut": "non renseigné"}
    reference = dt.date.fromisoformat(str(data["date_reference"]))
    rows = {}
    for fid, item in data["produits"].items():
        age = (reference - dt.date.fromisoformat(str(item["observe_le"]))).days
        rows[fid] = {**item, "observe_le": str(item["observe_le"]), "perime": age > data["validite_jours"],
                     "prix_effectif": foods[fid].prix_eur,
                     "unite_prix_effectif": "piece" if item["unite"] == "piece" else "kg" if item["unite"] == "g" else "l"}
    return {"version": 1, "date_reference": str(data["date_reference"]), "produits": rows,
            "statut": "selon les données déclarées ; absence de mention ne garantit pas absence d'allergène"}
