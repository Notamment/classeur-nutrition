#!/usr/bin/env python3
"""Vérifie la démo attendue sans assimiler une exception à une non-conformité."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = {("S01-R01", "poids_servi"), ("S01-R01", "duree"), ("S01-R02", "poids_servi"),
            ("S01-R04", "poids_servi"), ("S01-R05", "fer_vitc")}


def verify_result(result):
    if result.returncode != 1:
        raise ValueError(f"code attendu 1, reçu {result.returncode} : {result.stderr}")
    issues = json.loads(result.stdout)
    errors = {(i["where"], i["code"]) for i in issues if i["level"] == "erreur"}
    if errors != EXPECTED:
        raise ValueError(f"écarts inattendus : {errors}")
    if "Traceback" in result.stderr:
        raise ValueError("exception Python dans la démo")


def main():
    result = subprocess.run([sys.executable, str(ROOT / "skills/meal-binder/scripts/binder.py"),
                             "render", "--dir", str(ROOT / "examples/demo"), "--json"],
                            capture_output=True, text=True, encoding="utf-8")
    verify_result(result)
    output = ROOT / "examples/demo/out/classeur.md"
    if not output.is_file() or "## Audit final" not in output.read_text(encoding="utf-8"):
        raise ValueError("rendu absent ou incomplet")
    print("Démo vérifiée : rendu complet et écarts attendus.")


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # Windows : sortie redirigée en UTF-8, pas en cp1252
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    main()
