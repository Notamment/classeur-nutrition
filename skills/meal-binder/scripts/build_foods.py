#!/usr/bin/env python3
"""Remplace les valeurs provisoires de foods.csv par celles de la table Ciqual (Anses).

1. Télécharger la table Ciqual (format XLS/XLSX ou export CSV) depuis le site de l'Anses.
2. Renseigner data/ciqual_map.csv : une ligne par aliment, colonne `ciqual_code`.
   Choisir l'entrée Ciqual qui correspond à l'état de pesée (`etat_ref`) : cru, sec, égoutté…
3. python scripts/build_foods.py --ciqual chemin/table_ciqual.xls [--dry-run]

Seuls les aliments avec un code sont mis à jour (source=ciqual:<code>).
Valeurs « traces » → 0 ; « < x » → x, signalé. Dépendances : openpyxl (xlsx) ou xlrd (xls) selon le format.
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
            if pat.search(h.strip()):
                return i
    raise SystemExit(f"colonne introuvable : {[p.pattern for p in patterns]}")


def parse(v: str) -> tuple[float | None, bool]:
    v = (v or "").strip().replace(",", ".")
    if v in ("", "-"):
        return None, False
    if v.lower() == "traces":
        return 0.0, True
    bound = v.startswith("<")
    try:
        return float(v.lstrip("< ")), bound
    except ValueError:
        return None, False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ciqual", required=True, type=Path)
    ap.add_argument("--map", type=Path, default=DATA / "ciqual_map.csv")
    ap.add_argument("--foods", type=Path, default=DATA / "foods.csv")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    rows = read_table(a.ciqual)
    header = rows[0]
    ic, ip = find_col(header, CODE_RE), find_col(header, PROT_RE, PROT_FALLBACK_RE)
    ik = find_col(header, KCAL_RE)
    table = {r[ic].strip().split(".")[0]: r for r in rows[1:] if len(r) > max(ic, ip, ik)}

    with a.map.open(encoding="utf-8", newline="") as f:
        mapping = {r["id"]: r["ciqual_code"].strip() for r in csv.DictReader(f) if r.get("ciqual_code", "").strip()}
    with a.foods.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields, foods = reader.fieldnames, list(reader)

    updated, flagged = 0, []
    for food in foods:
        code = mapping.get(food["id"])
        if not code:
            continue
        row = table.get(code)
        if row is None:
            flagged.append(f"{food['id']}: code {code} absent de la table")
            continue
        prot, b1 = parse(row[ip])
        kcal, b2 = parse(row[ik])
        if prot is None or kcal is None:
            flagged.append(f"{food['id']}: valeur manquante dans Ciqual ({code})")
            continue
        food["prot_g_100g"], food["kcal_100g"] = f"{prot:g}", f"{kcal:g}"
        food["source"] = f"ciqual:{code}" + (":borne" if (b1 or b2) else "")
        updated += 1
        if b1 or b2:
            flagged.append(f"{food['id']}: valeur « traces » ou « < x » ({code})")

    print(f"{updated} aliment(s) mis à jour ; {len(foods) - updated} encore provisoire(s).")
    for line in flagged:
        print("ALERTE", line)
    if not a.dry_run:
        with a.foods.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(foods)
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # Windows : sortie redirigée en UTF-8, pas en cp1252
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
