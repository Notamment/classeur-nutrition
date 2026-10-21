"""Compare des classeurs proposés sous un même profil, sans modifier les entrées.

Sélection dans un ensemble fini fourni par l'agent, pas optimisation universelle
ni recombinaison exhaustive de recettes. Les achats réels du moteur font référence.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from checks import analyse, check_profile, preference_counts, required_budget_unverified
from core import BinderError, DataError, Issue, load_foods, load_profile, load_weeks
from render import esc, fr, render_classeur
from storage import safe_destination

MAX_PROPOSALS = 30
MARKER = "meal-binder:selection:v1\n"
LABELS = {"budget": "Montant caisse total", "temps_actif": "Temps actif total",
          "difficulte": "Niveau maximal de difficulté", "variete": "Nombre de plats distincts"}
UNITS = {"budget": " EUR", "temps_actif": " min", "difficulte": "", "variete": ""}


@dataclass
class Selection:
    report: dict
    chosen: object = None


def _measurements(ctx):
    expected = ctx.profile["projet"]["semaines"] * ctx.profile["projet"]["recettes_par_semaine"]
    if len(ctx.calcs) != expected or len(ctx.calcs) != len(ctx.declared) or len(ctx.weeks) != ctx.profile["projet"]["semaines"]:
        return {name: None for name in LABELS}  # Aucun total partiel présenté comme complet.
    adaptations = list(ctx.adaptations.values())
    recipes = list(ctx.recipes.values())
    active = [r.get("temps_actif_min") for r in recipes]
    levels = [r.get("niveau") for r in adaptations]
    dishes = [r.get("plat_id") for r in recipes]
    return {
        "budget": math.fsum(s.montant_caisse for s in ctx.shops) if all(s.budget_verifiable for s in ctx.shops) else None,
        "temps_actif": math.fsum(active) if recipes and all(v is not None for v in active) else None,
        "difficulte": max(levels) if levels and all(v is not None for v in levels) else None,
        "variete": len(set(dishes)) if dishes and all(dishes) else None,
    }


def _ranking(row, priorities):
    key = [row["preferences_non_satisfaites"] + row["preferences_non_verifiables"]]
    for criterion in priorities:
        value = row["mesures"][criterion]
        # L'inconnu est classé après le connu, jamais assimilé à zéro.
        key.extend([value is None, 0 if value is None else -value if criterion == "variete" else value])
    return (*key, row["id"])


def _explain_pair(better, other, priorities):
    """Premier critère décisif, dans le même ordre que le classement."""
    a = better["preferences_non_satisfaites"] + better["preferences_non_verifiables"]
    b = other["preferences_non_satisfaites"] + other["preferences_non_verifiables"]
    if a != b:
        reason = f"moins d'écarts préférentiels ({a} contre {b}, incertitudes comprises)"
    else:
        reason = "égalité sur tous les critères ; départage par identifiant"
        for criterion in priorities:
            av, bv = better["mesures"][criterion], other["mesures"][criterion]
            if av == bv:
                continue
            decimals = 2 if criterion == "budget" else 1 if criterion == "temps_actif" else 0
            shown_a = fr(av, decimals) + UNITS[criterion]
            shown_b = fr(bv, decimals) + UNITS[criterion]
            if bv is None:
                reason = f"{LABELS[criterion]} connu ({shown_a}) contre inconnu"
            else:
                reason = f"{LABELS[criterion]} {'supérieur' if criterion == 'variete' else 'inférieur'} ({shown_a} contre {shown_b})"
            break
    return f"{better['id']} devance {other['id']} : {reason}."


def select_proposals(workdir):
    workdir = Path(workdir)
    profile = load_profile(workdir)
    if profile["version"] != 2:
        raise DataError([Issue("erreur", "selection_version", "profil", "la sélection nécessite un profil v2")])
    foods, issues = load_foods(workdir)
    issues += check_profile(profile, foods)
    if any(i.level == "erreur" for i in issues):
        raise DataError(issues)
    folders = sorted(p for p in (workdir / "propositions").glob("*") if p.is_dir())
    if not folders:
        raise BinderError("aucune proposition : créer propositions/<id>/weeks/SXX.json")
    if len(folders) > MAX_PROPOSALS:
        raise DataError([Issue("erreur", "selection_taille", "propositions", f"au plus {MAX_PROPOSALS} propositions par comparaison")])
    priorities = profile["selection"]["priorites"]
    rows, contexts = [], {}
    for folder in folders:
        row = {"id": folder.name, "source": f"propositions/{folder.name}", "admissible": False,
               "preferences_non_satisfaites": 0, "preferences_non_verifiables": 0,
               "mesures": {name: None for name in LABELS}, "ecarts": [], "motifs_rejet": []}
        try:
            if folder.is_symlink() or not re.fullmatch(r"[a-z][a-z0-9_-]*", folder.name):
                raise DataError([Issue("erreur", "proposition_id", folder.name, "dossier simple requis, identifiant a-z, chiffres, _ ou -")])
            for filename in ("profile.yaml", "pantry.yaml", "stores.yaml", "foods.local.csv", "provenance.yaml", "products.yaml", "professional.yaml", "schedule.yaml", "locks.yaml"):
                if (folder / filename).exists():
                    raise DataError([Issue("erreur", "proposition_configuration", folder.name,
                                          f"{filename} doit être commun et placé à la racine du dossier de travail")])
            ctx = analyse(workdir, complete=True, weeks=load_weeks(folder))
            row["ecarts"] = [i.__dict__ for i in ctx.issues]
            row["motifs_rejet"] = [f"{i.where} · {i.code} : {i.msg}" for i in ctx.issues if i.level == "erreur"]
            if required_budget_unverified(ctx):
                row["motifs_rejet"].append("budget impératif non vérifiable : prix, stocks ou achats incomplets")
            try:
                row["mesures"] = _measurements(ctx)
            except OverflowError as exc:
                raise DataError([Issue("erreur", "selection_mesure", folder.name, "total hors capacité numérique")]) from exc
            if any(value is not None and not math.isfinite(value) for value in row["mesures"].values()):
                raise DataError([Issue("erreur", "selection_mesure", folder.name, "mesure non finie")])
            row["preferences_non_satisfaites"], row["preferences_non_verifiables"] = preference_counts(ctx)
            row["admissible"] = not row["motifs_rejet"]
            contexts[folder.name] = ctx
        except DataError as exc:
            row["mesures"] = {name: None for name in LABELS}
            row["ecarts"] = [i.__dict__ for i in exc.issues]
            row["motifs_rejet"] = [i.line() for i in exc.issues]
        except BinderError as exc:
            row["ecarts"] = [Issue("erreur", "proposition_illisible", folder.name, str(exc)).__dict__]
            row["motifs_rejet"] = [str(exc)]
        rows.append(row)
    ranked = sorted((r for r in rows if r["admissible"]), key=lambda row: _ranking(row, priorities))
    winner = ranked[0] if ranked else None
    for rank, row in enumerate(ranked, 1):
        row["rang"] = rank
        row["cle_classement"] = list(_ranking(row, priorities))
        if row is not winner:
            row["departage"] = _explain_pair(winner, row, priorities)
    report = {
        "version": 2, "titre": profile["projet"]["titre"],
        "selectionne": winner["id"] if winner else None, "priorites": priorities,
        "methode": [
            "Rejeter les violations impératives, données invalides et budgets impératifs invérifiables.",
            "Minimiser les écarts préférentiels, y compris les préférences actives invérifiables : un écart par règle et portée (recette, semaine ou classeur).",
            "Départager dans l'ordre de selection.priorites : minimiser budget, temps actif et difficulté ; maximiser variété.",
            "Pour chaque critère, une mesure inconnue est classée après une mesure connue, jamais comme zéro.",
            "À égalité, ordre alphabétique des identifiants. Comparaison limitée aux propositions fournies.",
        ],
        "classement": [r["id"] for r in ranked], "propositions": rows,
        "explication": (f"Proposition « {winner['id']} » retenue : {winner['preferences_non_satisfaites']} préférence(s) non satisfaite(s), "
                         f"{winner['preferences_non_verifiables']} non vérifiable(s). "
                         + (_explain_pair(winner, ranked[1], priorities) if len(ranked) > 1 else "Seule proposition admissible.")
                         if winner else "Aucune proposition admissible. Corriger les motifs de rejet ; aucun classeur n'est retenu."),
    }
    return Selection(report, contexts[winner["id"]] if winner else None)


def render_selection(selection):
    report = selection.report
    lines = ["# Sélection du classeur", "", f"Projet : {esc(report['titre'])}.", "",
             esc(report["explication"]), "", "## Méthode", ""]
    lines += [f"{n}. {esc(s)}" for n, s in enumerate(report["methode"], 1)]
    lines += ["", "Priorités : " + (" → ".join(report["priorites"]) or "aucun critère supplémentaire") + ".",
              "", "Les niveaux de difficulté et temps sont déclaratifs. Les prix sont ceux du dossier, sans vérification commerciale.", "",
              "| Proposition | Rang | Admissible | Préférences non satisfaites / invérifiables | Caisse EUR | Actif min | Difficulté max (1–3) | Plats distincts |",
              "|---|---:|---|---:|---:|---:|---:|---:|"]
    for row in report["propositions"]:
        m = row["mesures"]
        lines.append(f"| {esc(row['id'])} | {row.get('rang', '—')} | {'oui' if row['admissible'] else 'non'} | "
                     f"{row['preferences_non_satisfaites']} / {row['preferences_non_verifiables']} | "
                     f"{fr(m['budget'], 2)} | {fr(m['temps_actif'], 1)} | {fr(m['difficulte'])} | {fr(m['variete'])} |")
    for row in report["propositions"]:
        lines += ["", f"## {esc(row['id'])}", ""]
        if row["motifs_rejet"]:
            lines += [f"- Rejet : {esc(reason)}" for reason in row["motifs_rejet"]]
        elif row["id"] == report["selectionne"]:
            lines.append("- Retenue selon la méthode ci-dessus.")
        else:
            lines.append(f"- Admissible, rang {row['rang']}. {esc(row['departage'])}")
        unknown = [LABELS[c] for c in report["priorites"] if row["mesures"][c] is None]
        if unknown:
            lines.append("- Critères inconnus : " + ", ".join(unknown) + ".")
        lines += [f"- {i['level']} · {esc(i['where'])} · {i['code']} : {esc(i['msg'])}" for i in row["ecarts"] if i["level"] == "alerte"]
    return "\n".join(lines) + "\n"


def save_selection(selection, workdir, *, generated_on=None):
    """Sortie autonome atomique ; aucun fichier d'entrée n'est remplacé."""
    workdir = Path(workdir)
    out = safe_destination(workdir / "out")
    out.mkdir(exist_ok=True)
    target = out / "selection"
    marker = target / "GENERATED"
    if target.is_symlink() or (target.exists() and (not marker.is_file() or marker.read_text(encoding="utf-8") != MARKER)):
        raise BinderError("out/selection existe et n'est pas une sortie générée reconnue ; choisir un autre dossier de travail")
    stage = Path(tempfile.mkdtemp(prefix=".selection-", dir=out))
    backup = None
    published = False
    try:
        (stage / "GENERATED").write_text(MARKER, encoding="utf-8")
        (stage / "rapport.json").write_text(json.dumps(selection.report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        (stage / "rapport.md").write_text(render_selection(selection), encoding="utf-8")
        if selection.chosen:
            ctx = selection.chosen
            for filename, value in (("profile.yaml", ctx.profile), ("pantry.yaml", {"stock": ctx.pantry})):
                (stage / filename).write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")
            if ctx.stores:
                (stage / "stores.yaml").write_text(yaml.safe_dump(ctx.stores, allow_unicode=True, sort_keys=False), encoding="utf-8")
            if (workdir / "foods.local.csv").exists():
                shutil.copy2(workdir / "foods.local.csv", stage / "foods.local.csv")
            for name in ("provenance.yaml", "products.yaml", "professional.yaml", "schedule.yaml", "locks.yaml"):
                if (workdir / name).exists():
                    shutil.copy2(workdir / name, stage / name)
            (stage / "weeks").mkdir()
            for week in ctx.weeks:
                (stage / "weeks" / f"{week['semaine']}.json").write_text(json.dumps(week, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (stage / "out").mkdir()
            (stage / "out/classeur.md").write_text(render_classeur(ctx, ctx.shops, ctx.final_stock, [], generated_on=generated_on).rstrip() + "\n", encoding="utf-8")
            from manifest import make_manifest, encode
            (stage / "out/manifest.json").write_text(encode(make_manifest(analyse(stage, complete=True), generated_on)), encoding="utf-8")
        if target.exists():
            backup = Path(tempfile.mkdtemp(prefix=".selection-backup-", dir=out))
            backup.rmdir()
            os.replace(target, backup)
        try:
            os.replace(stage, target)
            published = True
        except OSError:
            if backup:
                os.replace(backup, target)
                backup = None
            raise
        return target
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if published and backup and backup.exists():
            shutil.rmtree(backup)
