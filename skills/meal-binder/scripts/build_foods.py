#!/usr/bin/env python3
"""Remplace les valeurs provisoires de foods.csv par celles de la table Ciqual (Anses).

1. Télécharger la table Ciqual (format XLS/XLSX ou export CSV) depuis le site de l'Anses.
2. Renseigner data/ciqual_map.csv : une ligne par aliment, colonne `ciqual_code`.
   Choisir l'entrée Ciqual qui correspond à l'état de pesée (`etat_ref`) : cru, sec, égoutté…
3. python scripts/build_foods.py --ciqual chemin/table_ciqual.xls [--dry-run]

Seuls les aliments avec un code sont mis à jour (source=ciqual:<code>).
Valeurs « traces » et « < x » conservées comme incertitudes dans provenance.yaml ; jamais comme valeurs exactes. Dépendances : openpyxl (xlsx) ou xlrd (xls) selon le format.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
PROT_RE = re.compile(r"prot.*jones", re.I)
PROT_FALLBACK_RE = re.compile(r"^prot", re.I)
KCAL_RE = re.compile(r"energie.*1169.*kcal|energ.*kcal", re.I)
CODE_RE = re.compile(r"^alim_code$", re.I)


def read_table(path: Path) -> list:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            sample = f.read(4096)
            f.seek(0)
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
            return [list(r) for r in csv.reader(f, dialect)]
    if suffix == ".xlsx":
        import openpyxl
        ws = openpyxl.load_workbook(path, read_only=True).active
        return [[("" if c is None else str(c)) for c in row] for row in ws.iter_rows(values_only=True)]
    if suffix == ".xls":
        import xlrd
        sh = xlrd.open_workbook(str(path)).sheet_by_index(0)
        return [[str(sh.cell_value(r, c)) for c in range(sh.ncols)] for r in range(sh.nrows)]
    raise SystemExit(f"format non pris en charge : {suffix}")


def find_col(header: list, *patterns) -> int:
    for pat in patterns:
        for i, h in enumerate(header):
            if pat.search(" ".join(h.split())):
                return i
    raise SystemExit(f"colonne introuvable : {[p.pattern for p in patterns]}")


def parse(v: str) -> tuple[float | None, bool]:
    """Ancienne interface : aucune borne ni trace transformée en valeur exacte."""
    from sources import parse_measure
    measure = parse_measure(v, "g")
    return (measure["minimum"] if measure["statut"] == "exact" else None,
            measure["statut"] in ("borne", "traces"))


def main(argv=None) -> int:
    import datetime
    import io
    import yaml
    from sources import parse_measure
    from storage import atomic_batch
    from core import BinderError, DataError, _read_foods
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ciqual", required=True, type=Path)
    ap.add_argument("--map", type=Path, default=DATA / "ciqual_map.csv")
    ap.add_argument("--foods", type=Path, default=DATA / "foods.csv")
    ap.add_argument("--metadata", type=Path)
    ap.add_argument("--source", help="URL de la source officielle")
    ap.add_argument("--source-version", help="édition précise de la table")
    ap.add_argument("--license", dest="licence", help="licence de réutilisation vérifiée")
    ap.add_argument("--retrieved-on", type=datetime.date.fromisoformat)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        if not a.dry_run and not all((a.source, a.source_version, a.licence, a.retrieved_on)):
            raise ValueError("import : source, édition, licence et date de récupération obligatoires")
        rows = read_table(a.ciqual)
        if not rows:
            raise ValueError("table vide")
        header = rows[0]
        if len(header) != len(set(header)):
            raise ValueError("colonnes dupliquées dans la table")
        ic, ip = find_col(header, CODE_RE), find_col(header, PROT_RE, PROT_FALLBACK_RE)
        ik = find_col(header, KCAL_RE)
        extra_columns = {}
        for nutrient, unit, expression in (("lipides_g", "g", r"^(?:Fat|Lipides)\b"),
                                            ("glucides_g", "g", r"^(?:Carbohydrate|Glucides)\b"),
                                            ("fibres_g", "g", r"^Fibres\b"),
                                            ("sodium_mg", "mg", r"^Sodium.*mg")):
            matches = [i for i, name in enumerate(header) if re.search(expression, " ".join(name.split()), re.I)]
            if matches:
                extra_columns[nutrient] = (matches[0], unit)
        table = {}
        for row in rows[1:]:
            if not any(str(value).strip() for value in row):
                continue
            if len(row) != len(header):
                raise ValueError("ligne tronquée dans la table")
            code = row[ic].strip().removesuffix(".0")
            if code in table:
                raise ValueError("code alimentaire dupliqué : " + code)
            table[code] = row
        with a.map.open(encoding="utf-8-sig", newline="") as f:
            mapping = {}
            for row in csv.DictReader(f):
                fid = row["id"]
                if fid in mapping:
                    raise ValueError("identifiant dupliqué dans la correspondance : " + fid)
                mapping[fid] = row.get("ciqual_code", "").strip()
        issues = []
        _read_foods(a.foods, issues)
        if issues:
            raise DataError(issues)
        with a.foods.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fields, foods = reader.fieldnames, list(reader)
        unknown = set(mapping) - {r["id"] for r in foods}
        if unknown:
            raise ValueError("aliments inconnus dans la correspondance : " + ", ".join(sorted(unknown)))
        metadata_path = a.metadata or a.foods.with_name("provenance.yaml")
        if a.foods.resolve() == metadata_path.resolve():
            raise ValueError("sorties CSV et provenance doivent être distinctes")
        registry = {"version": 1, "aliments": {}}
        if metadata_path.exists():
            from core import load_yaml, schema_issues
            from sources import REGISTRY
            registry = load_yaml(metadata_path)
            invalid = schema_issues(registry, REGISTRY, metadata_path.name, "schema_provenance")
            if invalid:
                raise DataError(invalid)
        updated = 0
        for food in foods:
            code = mapping.get(food["id"])
            if not code:
                continue
            if code not in table:
                raise ValueError(f"{food['id']} : code absent de la table : {code}")
            row = table[code]
            protein = parse_measure(row[ip], "g")
            energy = parse_measure(row[ik], "kcal")
            for field, measure in (("prot_g_100g", protein), ("kcal_100g", energy)):
                food[field] = str(measure["minimum"]) if measure["statut"] == "exact" else ""
            food["source"] = "ciqual:" + code
            registry["aliments"][food["id"]] = {
                "source": a.source or "simulation-sans-source", "edition": a.source_version or "simulation",
                "date": str(a.retrieved_on or datetime.date.today()), "licence": a.licence or "non-renseignée",
                "etat_ref": food["etat_ref"], "nutriments": {"proteines_g": protein, "energie_kcal": energy}}
            registry["aliments"][food["id"]]["code"] = code
            registry["aliments"][food["id"]]["nutriments"].update({
                nutrient: parse_measure(row[index], unit) for nutrient, (index, unit) in extra_columns.items()})
            updated += 1
        print(f"{updated} aliment(s) importable(s) ; correspondances non renseignées : {sum(not mapping.get(f['id']) for f in foods)}.")
        print("États de pesée des correspondances à valider humainement ; aucun code n'est choisi automatiquement.")
        if not a.dry_run:
            output = io.StringIO(newline="")
            writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
            writer.writeheader(); writer.writerows(foods)
            atomic_batch({a.foods: output.getvalue().encode("utf-8"),
                          metadata_path: yaml.safe_dump(registry, allow_unicode=True, sort_keys=False).encode("utf-8")})
        return 0
    except (OSError, ValueError, KeyError, csv.Error, BinderError) as exc:
        print(f"Import refusé : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # Windows : sortie redirigée en UTF-8, pas en cp1252
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
