#!/usr/bin/env python3
"""CLI du classeur : contrôles, courses, rendu et audit.

  python binder.py check-profile --dir DIR
  python binder.py check-plan    --dir DIR
  python binder.py check-week S01 --dir DIR
  python binder.py check-all     --dir DIR
  python binder.py render        --dir DIR     → DIR/out/classeur.md
  python binder.py audit         --dir DIR     → DIR/out/audit.md
  python binder.py list-presets                 → catalogue des préréglages
  python binder.py list-options                 → techniques, familles, critères
  python binder.py show-profile  --dir DIR     → profil résolu et origines
  python binder.py select        --dir DIR     → comparaison et copie du classeur retenu
  python binder.py diagnose      --dir DIR     → analyse JSON versionnée
  python binder.py snapshot      --dir DIR --output ARCHIVE [--date YYYY-MM-DD]
  python binder.py verify-snapshot --dir ARCHIVE

Codes : 0 sans erreur, 1 données non conformes, 2 entrée illisible/manquante,
3 panne interne ou Python < 3.10. Avec --json, les contrôles renvoient une liste d'écarts ;
list-presets et list-options renvoient leurs catalogues, show-profile un objet
profil/origines/ecarts, select un rapport (code 1 si aucune proposition admissible).
Sortie volontairement compacte : elle est lue par un agent.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
import datetime as dt
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from checks import analyse, check_plan, check_profile, load_pantry, load_plan  # noqa: E402
from core import BinderError, DataError, Issue, load_foods, load_profile, utf8_stdio, week_order  # noqa: E402
from render import render_audit, render_classeur  # noqa: E402
from profiles import list_presets, load_resolved, nutrition_mode, week_title  # noqa: E402
from storage import write_render  # noqa: E402
from storage import atomic_text  # noqa: E402
from manifest import analysis_payload, encode, make_manifest, snapshot, verify_snapshot  # noqa: E402


def report(issues: list, as_json: bool = False) -> int:
    errs = [i for i in issues if i.level == "erreur"]
    if as_json:
        print(json.dumps([i.__dict__ for i in issues], ensure_ascii=False, indent=1, allow_nan=False))
    else:
        for i in errs + [i for i in issues if i.level != "erreur"]:
            print(i.line())
        print(f"Bilan : {len(errs)} erreur(s), {len(issues) - len(errs)} alerte(s).")
    return 1 if errs else 0


def recipe_table(ctx, wid: str) -> None:
    w = next((w for w in ctx.weeks if w.get("semaine") == wid), None)
    if w is None:
        raise BinderError(f"semaine {wid} introuvable dans weeks/")
    nutrition = nutrition_mode(ctx.profile) != "desactive"
    print(f"{wid} {week_title(w)} — valeurs par portion (estimations)")
    print("jour | id | catégorie | " + ("protéines | kcal | " if nutrition else "") + "poids servi | min")
    for d, rid in enumerate(week_order(w), start=1):
        rc, r = ctx.calcs.get(rid), ctx.recipes.get(rid, {})
        if rc is None:
            print(f"{d:<5}{rid:<9} non calculée")
            continue
        values = " | ".join("—" if n is None else f"{n:.1f}" for n in (rc.prot_pp, rc.kcal_pp)) + " | " if nutrition else ""
        print(f"{d} | {rid} | {rc.categorie} | {values}{rc.poids_pp:.0f} g | {r['temps_total_min']}")


def main(argv=None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if values and values[0] == "doctor":
        from version import ENGINE_VERSION
        from core import SKILL_DIR
        print(encode({"version": 1, "moteur": ENGINE_VERSION, "python": sys.version.split()[0],
                      "pyyaml": yaml.__version__, "python_compatible": sys.version_info >= (3, 10),
                      "donnees_presentes": (SKILL_DIR / "data/foods.csv").is_file(),
                      "ciqual_optionnel_present": (SKILL_DIR / "data/ciqual2025/provenance.yaml").is_file(),
                      "reseau_requis": False}), end="")
        return 0
    from workflow import COMMANDS
    if values and values[0] in COMMANDS:
        from workflow import main as workflow_main
        return workflow_main(values)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    from version import ENGINE_VERSION
    ap.add_argument("--version", action="version", version=ENGINE_VERSION)
    ap.add_argument("command", choices=["list-presets", "list-options", "show-profile", "check-profile", "check-plan", "check-week", "check-all", "render", "audit", "select", "diagnose", "snapshot", "verify-snapshot", "nutrients", "use-data", "products"])
    ap.add_argument("week", nargs="?", help="identifiant de semaine pour check-week (ex. S01)")
    ap.add_argument("--dir", default=".", help="dossier de travail (profile.yaml, plan.yaml, weeks/)")
    ap.add_argument("--json", action="store_true", help="écarts au format JSON")
    ap.add_argument("--date", type=lambda s: dt.date.fromisoformat(s).isoformat(), help="date de génération YYYY-MM-DD")
    ap.add_argument("--output", type=Path, help="destination nouvelle d'une archive autonome")
    ap.add_argument("--edition", choices=["ciqual2025"], help="jeu de données optionnel à activer explicitement")
    a = ap.parse_args(argv)
    wd = Path(a.dir).resolve()
    try:
        if a.command == "use-data":
            from core import SKILL_DIR
            if a.edition is None:
                raise BinderError("use-data nécessite --edition ciqual2025")
            destination = wd / "provenance.yaml"
            if destination.exists():
                raise BinderError("provenance.yaml existe : fusion manuelle requise pour préserver les sources locales")
            atomic_text(destination, (SKILL_DIR / "data" / a.edition / "provenance.yaml").read_text(encoding="utf-8"))
            print(encode({"version": 1, "edition": a.edition, "sources_exigees": True}), end="")
            return 0
        if a.command == "verify-snapshot":
            result = verify_snapshot(wd)
            print(encode(result), end="")
            return 0 if result["integre"] else 1
        if a.command == "list-options":
            from catalogs import load_catalogs
            from schemas import SELECTION_CRITERIA
            options = load_catalogs().as_dict() | {"criteres_selection": list(SELECTION_CRITERIA)}
            print(json.dumps(options, ensure_ascii=False, indent=2, allow_nan=False) if a.json
                  else yaml.safe_dump(options, allow_unicode=True, sort_keys=False), end="\n" if a.json else "")
            return 0
        if a.command == "select":
            from selection import select_proposals, save_selection
            selected = select_proposals(wd)
            path = save_selection(selected, wd, generated_on=a.date)
            if a.json:
                print(json.dumps(selected.report, ensure_ascii=False, indent=2, allow_nan=False))
            else:
                print(selected.report["explication"])
                print(f"Rapport : {path / 'rapport.md'}")
                if selected.chosen:
                    print(f"Classeur : {path / 'out/classeur.md'}")
            return 0 if selected.chosen else 1
        if a.command == "list-presets":
            presets = list_presets()
            if a.json:
                print(json.dumps(presets, ensure_ascii=False, indent=2, allow_nan=False))
            else:
                for name, preset in presets.items():
                    print(f"{name} — {preset['nom']} : {preset['description']}")
            return 0
        if a.command == "products":
            from products import product_report
            foods, issues = load_foods(wd)
            print(encode(product_report(wd, foods)), end="")
            return int(any(i.level == "erreur" for i in issues))
        if a.command == "show-profile":
            resolved = load_resolved(wd)
            foods, issues = load_foods(wd)
            issues += check_profile(resolved.profile, foods)
            result = {"profil": resolved.profile, "origines": resolved.origins,
                      "ecarts": [i.__dict__ for i in issues]}
            if a.json:
                print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
            else:
                print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), end="")
            return int(any(i.level == "erreur" for i in issues))
        if a.command == "check-profile":
            foods, issues = load_foods(wd)
            issues += check_profile(load_profile(wd), foods)
            _, pantry_issues = load_pantry(wd, foods)
            issues += pantry_issues
            return report(issues, a.json)
        if a.command == "check-plan":
            foods, issues = load_foods(wd)
            profile = load_profile(wd)
            issues += check_profile(profile, foods)
            if not any(i.code == "schema_profil" for i in issues):
                issues += check_plan(load_plan(wd), profile)
            return report(issues, a.json)
        if a.command == "check-week":
            if not a.week:
                raise BinderError("préciser la semaine : check-week S01")
            ctx = analyse(wd)
            if not any(w["semaine"] == a.week for w in ctx.weeks):
                raise BinderError(f"semaine {a.week} introuvable dans weeks/")
            if not a.json:
                recipe_table(ctx, a.week)
            other = {rid for rid, w in ctx.week_of.items() if w != a.week}
            other |= {w["semaine"] for w in ctx.weeks if w["semaine"] != a.week}
            scoped = [i for i in ctx.issues if i.where not in other]
            return report(scoped, a.json)
        ctx = analyse(wd, complete=a.command in ("check-all", "render", "audit", "diagnose", "snapshot", "nutrients"))
        if a.command == "nutrients":
            from sources import nutrient_report
            print(encode(nutrient_report(ctx)), end="")
            return int(any(i.level == "erreur" for i in ctx.issues))
        if a.command == "diagnose":
            print(encode({"version": 2, **analysis_payload(ctx)}), end="")
            return int(any(i.level == "erreur" for i in ctx.issues))
        if a.command == "snapshot":
            if a.output is None:
                raise BinderError("snapshot nécessite --output vers un dossier nouveau")
            print(encode(snapshot(ctx, a.output, a.date)), end="")
            return int(any(i.level == "erreur" for i in ctx.issues))
        if a.command == "check-all":
            if not a.json:
                for w in ctx.weeks:
                    recipe_table(ctx, w.get("semaine"))
            return report(ctx.issues, a.json)
        shops, final_stock = ctx.shops, ctx.final_stock
        out_dir = wd / "out"
        out_dir.mkdir(exist_ok=True)
        if a.command == "render":
            path = out_dir / "classeur.md"
            write_render(path, render_classeur(ctx, shops, final_stock, [], generated_on=a.date))
        else:
            path = out_dir / "audit.md"
            write_render(path, render_audit(ctx, shops, generated_on=a.date))
        atomic_text(out_dir / "manifest.json", encode(make_manifest(ctx, a.date)))
        print(f"Écrit : {path}", file=sys.stderr if a.json else sys.stdout)
        return report(ctx.issues, a.json)
    except DataError as e:
        return report(e.issues, a.json)
    except BinderError as e:
        report([Issue("erreur", "entree_illisible", "entree", str(e))], a.json)
        return 2
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        report([Issue("erreur", "erreur_interne", "programme", f"{type(e).__name__}: {e}")], a.json)
        return 3


if __name__ == "__main__":
    utf8_stdio()
    sys.exit(main())
