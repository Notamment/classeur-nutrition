"""Empreintes et archives autonomes ; aucune donnée n'est envoyée au réseau."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from core import BinderError, SKILL_DIR, load_json
from storage import atomic_text, safe_destination
from version import ENGINE_VERSION, DIAGNOSTICS_VERSION

INPUTS = ("profile.yaml", "pantry.yaml", "stores.yaml", "plan.yaml", "foods.local.csv",
          "provenance.yaml", "products.yaml", "professional.yaml", "schedule.yaml")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def generation_date(value=None):
    return dt.date.fromisoformat(value).isoformat() if value else dt.date.today().isoformat()


def engine_files():
    return sorted([*SKILL_DIR.joinpath("scripts").glob("*.py"),
                   *SKILL_DIR.joinpath("data").rglob("*.csv"),
                   *SKILL_DIR.joinpath("data").rglob("*.json"),
                   *SKILL_DIR.joinpath("data").rglob("*.yaml")])


def input_files(workdir):
    workdir = Path(workdir)
    return sorted([p for name in INPUTS if (p := workdir / name).exists()]
                  + list((workdir / "weeks").glob("*.json")))


def hashes(paths, root):
    result = {}
    for path in paths:
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise BinderError(f"archive protégée : lien symbolique {path.name}")
        result[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return result


def analysis_payload(ctx):
    from checks import preference_counts, required_budget_unverified
    return {"diagnostics_version": DIAGNOSTICS_VERSION, "profil": ctx.profile,
            "ecarts": [i.__dict__ for i in ctx.issues],
            "preferences": preference_counts(ctx),
            "budget_imperatif_inverifiable": required_budget_unverified(ctx),
            "recettes": {rid: {"proteines": c.prot_pp, "kcal": c.kcal_pp,
                               "poids_servi": c.poids_pp, "categorie": c.categorie}
                         for rid, c in sorted(ctx.calcs.items())},
            "courses": [{"semaine": s.semaine, "montant_caisse": s.montant_caisse,
                         "verifiable": s.budget_verifiable,
                         "lignes": [{"food": l.food.id, "besoin": l.besoin, "achat": l.achat,
                                     "mobilise": l.mobilise, "reste": l.reste} for l in s.lines]}
                        for s in ctx.shops]}


def make_manifest(ctx, date=None):
    payload = analysis_payload(ctx)
    return {"version": 1, "moteur": ENGINE_VERSION, "date_generation": generation_date(date),
            "entrees": hashes(input_files(ctx.workdir), ctx.workdir),
            "moteur_fichiers": hashes(engine_files(), SKILL_DIR),
            "profil_effectif": ctx.profile, "analyse_sha256": digest(encode(payload).encode("utf-8"))}


def snapshot(ctx, target, date=None):
    """Une archive inclut seulement les entrées déclarées et le moteur calculant."""
    target = safe_destination(target)
    source = Path(ctx.workdir).resolve()
    if target.exists() or target == source or target in source.parents or source in target.parents:
        raise BinderError("archive : destination nouvelle et extérieure au dossier de travail requise")
    manifest = make_manifest(ctx, date)
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=target.parent))
    try:
        for relative in manifest["entrees"]:
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, destination)
        for relative in manifest["moteur_fichiers"]:
            destination = stage / ".runtime/meal-binder" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SKILL_DIR / relative, destination)
        atomic_text(stage / "snapshot.json", encode(manifest))
        atomic_text(stage / "analyse.json", encode(analysis_payload(ctx)))
        from render import render_classeur
        atomic_text(stage / "out/classeur.md", render_classeur(ctx, ctx.shops, ctx.final_stock, [],
                                                              generated_on=manifest["date_generation"]))
        os.replace(stage, target)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _relative(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
        raise BinderError("chemin invalide dans le manifeste")
    return path


def verify_snapshot(directory):
    directory = Path(directory)
    manifest = load_json(directory / "snapshot.json")
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise BinderError("version de manifeste non prise en charge")
    differences = []
    for key, root in (("entrees", directory), ("moteur_fichiers", directory / ".runtime/meal-binder")):
        entries = manifest.get(key)
        if not isinstance(entries, dict):
            raise BinderError("manifeste incomplet")
        for name, expected in entries.items():
            path = root / _relative(name)
            if path.is_symlink() or any(p.is_symlink() for p in path.parents) or not path.is_file():
                differences.append(f"{key}/{name} : absent ou lien symbolique")
            elif digest(path.read_bytes()) != expected:
                differences.append(f"{key}/{name} : modifié")
    actual_inputs = {p.relative_to(directory).as_posix() for p in input_files(directory)}
    if actual_inputs != set(manifest["entrees"]):
        differences.append("inventaire des entrées modifié")
    current = hashes(engine_files(), SKILL_DIR)
    archived_root = directory / ".runtime/meal-binder"
    archived_paths = {p.relative_to(archived_root).as_posix() for p in archived_root.rglob("*")
                      if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    if archived_paths != set(manifest["moteur_fichiers"]):
        differences.append("inventaire du moteur archivé modifié")
    engine_matches = current == manifest["moteur_fichiers"]
    if not engine_matches:
        differences.append("moteur courant différent : utiliser explicitement le moteur archivé de confiance")
    if not differences:
        from checks import analyse
        actual = digest(encode(analysis_payload(analyse(directory, complete=True))).encode("utf-8"))
        if actual != manifest["analyse_sha256"]:
            differences.append("résultats recalculés différents")
        if digest((directory / "analyse.json").read_bytes()) != manifest["analyse_sha256"]:
            differences.append("rapport d'analyse modifié")
    return {"version": 1, "integre": not differences, "moteur_identique": engine_matches, "differences": differences}
