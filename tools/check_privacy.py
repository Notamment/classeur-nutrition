#!/usr/bin/env python3
"""Cherche des données personnelles dans les fichiers suivis avant un commit.

Les motifs sont personnels : ils vivent dans `.privacy-patterns` (ignoré par git), une expression
régulière par ligne, insensible à la casse. Exemples : votre ville, votre rue, vos magasins,
votre nom, un problème de santé, votre employeur.

  python tools/check_privacy.py                    # motifs de .privacy-patterns
  python tools/check_privacy.py --patterns FICHIER

Code de sortie 1 si une correspondance est trouvée, 2 si le fichier de motifs manque. Utilisable en hook pre-commit.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".xls", ".xlsx"}


def tracked_files() -> list:
    try:
        # Fichiers suivis + fichiers non suivis non ignorés : ce que `git add -A` publierait.
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                             cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout
        return [ROOT / f for f in out.split("\0") if f]
    except (subprocess.CalledProcessError, FileNotFoundError):
        ignored = {".git", "__pycache__", "runs"}
        return [p for p in ROOT.rglob("*") if p.is_file() and not ignored & set(p.parts)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patterns", type=Path, default=ROOT / ".privacy-patterns")
    a = ap.parse_args()
    if not a.patterns.exists():
        print(f"Aucun fichier de motifs ({a.patterns}). Créez-le : une expression régulière par ligne.")
        return 2
    pats = [re.compile(l.strip(), re.I) for l in a.patterns.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]
    hits = 0
    for path in tracked_files():
        if path.suffix.lower() in SKIP_SUFFIXES or path.resolve() == a.patterns.resolve():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(lines, start=1):
            for p in pats:
                if p.search(line):
                    hits += 1
                    print(f"{path.relative_to(ROOT)}:{n}: « {p.pattern} »")
    print(f"{hits} correspondance(s).")
    return 1 if hits else 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # Windows : sortie redirigée en UTF-8, pas en cp1252
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
