#!/usr/bin/env python3
"""Note les classeurs générés par différents modèles avec les contrôles de binder.py.

Arborescence attendue (un dossier de travail par exécution) :

  evals/runs/<modèle>/<profil>/          profile.yaml, pantry.yaml, plan.yaml, weeks/*.json
  evals/runs/<modèle>/<profil>-2/        répétitions éventuelles

Usage : python evals/score.py [evals/runs] [--out evals/results.md]

Métriques par exécution :
  - recettes produites / attendues ;
  - taux local de recettes sans erreur, séparé du score avec contraintes globales ;
  - score nul si erreur globale ou plafond de budget impératif invérifiable ;
  - erreurs de semaine et de classeur (quotas, alternance, riz, féculents, répartition) ;
  - erreurs bloquantes (JSON invalide, aliment inconnu, état incohérent) = données inexploitables.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "meal-binder" / "scripts"))

from checks import analyse, preference_counts, required_budget_unverified  # noqa: E402
from core import BinderError, utf8_stdio  # noqa: E402

BLOCKING = {"aliment_inconnu", "etat", "unite", "quantite", "conversion", "champ_manquant", "id_doublon"}


def score_run(workdir: Path) -> dict:
    try:
        ctx = analyse(workdir, complete=True)
    except BinderError as e:
        return {"run": workdir, "bloquant": str(e)}
    p = ctx.profile["projet"]
    expected = p["semaines"] * p["recettes_par_semaine"]
    errs = [i for i in ctx.issues if i.level == "erreur"]
    rids = ctx.declared
    bad = {i.where for i in errs if i.where in rids}
    clean = len(set(ctx.calcs) - bad)
    global_errors = sum(i.where not in rids for i in errs)
    budget_unknown = required_budget_unverified(ctx)
    recipe_rate = min(clean / expected, 1.0) if expected else 0.0
    missed, unknown = preference_counts(ctx)
    return {
        "run": workdir,
        "attendues": expected,
        "produites": len(rids),
        "propres": clean,
        "taux_recettes": recipe_rate,
        "taux": 0.0 if global_errors or budget_unknown else recipe_rate,
        "conforme": not errs and not budget_unknown and len(ctx.calcs) == expected,
        "budget": "non conforme" if any(i.code == "budget_depasse" for i in errs)
                  else "préférence non satisfaite" if any(i.code == "budget_depasse" for i in ctx.issues)
                  else "non vérifié" if any(i.code == "budget_non_verifie" for i in ctx.issues) else "estimation",
        "preferences_non_satisfaites": missed,
        "preferences_non_verifiables": unknown,
        "err_recettes": sum(i.where in rids for i in errs),
        "err_globales": global_errors,
        "bloquantes": sum(i.code in BLOCKING or i.code.startswith(("schema_", "foods_")) for i in errs),
        "codes": Counter(i.code for i in errs),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="?", default=str(ROOT / "evals" / "runs"))
    ap.add_argument("--out", default=str(ROOT / "evals" / "results.md"))
    a = ap.parse_args()
    runs_dir = Path(a.runs)
    runs = sorted(d for d in runs_dir.glob("*/*") if (d / "profile.yaml").exists())
    if not runs:
        print(f"Aucune exécution trouvée dans {runs_dir}")
        return 1
    lines = ["# Résultats d'évaluation", "",
             "Le score vaut zéro en cas d'erreur globale ou de plafond budgétaire impératif invérifiable. Les préférences restent distinctes du score de conformité.", "",
             "| Modèle | Profil | Recettes | Taux local | Score | Conforme aux contrôles | Budget | Err. globales | Préférences non satisfaites / invérifiables | Codes fréquents |",
             "|---|---|---:|---:|---:|---|---|---:|---:|---|"]
    by_model: dict = {}
    for d in runs:
        s = score_run(d)
        model, profile = d.parent.name, d.name
        if "bloquant" in s:
            lines.append(f"| {model} | {profile} | — | — | 0 % | non | non vérifié | — | — | {s['bloquant']} |")
            by_model.setdefault(model, []).append(0.0)
            continue
        top = ", ".join(f"{c}×{n}" for c, n in s["codes"].most_common(3)) or "—"
        lines.append(f"| {model} | {profile} | {s['produites']}/{s['attendues']} | {s['taux_recettes']:.0%} | "
                     f"{s['taux']:.0%} | {'oui' if s['conforme'] else 'non'} | {s['budget']} | {s['err_globales']} | {s['preferences_non_satisfaites']} / {s['preferences_non_verifiables']} | {top} |")
        by_model.setdefault(model, []).append(s["taux"])
    lines += ["", "| Modèle | Exécutions | Score moyen |", "|---|---:|---:|"]
    for m, rates in sorted(by_model.items()):
        lines.append(f"| {m} | {len(rates)} | {sum(rates) / len(rates):.0%} |")
    text = "\n".join(lines) + "\n"
    Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    utf8_stdio()
    sys.exit(main())
