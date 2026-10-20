"""Dossiers professionnels locaux, revue humaine et historique privé."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

import yaml

from checks import analyse, required_budget_unverified
from core import BinderError, DataError, SKILL_DIR, load_json
from manifest import encode, input_files, make_manifest, hashes, snapshot
from storage import atomic_batch, atomic_text, safe_destination

COMMANDS = {"init", "clone", "review", "review-status", "archive", "history"}


@contextlib.contextmanager
def locked(directory):
    path = safe_destination(Path(directory) / ".dossier.lock")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise BinderError("dossier occupé ; vérifier le processus propriétaire avant de retirer .dossier.lock") from exc
    os.close(descriptor)
    try:
        yield
    finally:
        path.unlink()


def journal(directory, action, details):
    path = Path(directory) / "history.jsonl"
    previous = path.read_text(encoding="utf-8") if path.exists() else ""
    event = {"version": 1, "date_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "action": action,
             "details": details}
    return path, (previous + json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def create_workspace(target, *, source=None, identifier=None, profession="nutrition"):
    target = safe_destination(target)
    if target.exists():
        raise BinderError("dossier cible existant : création ou duplication refusée")
    # Les exceptions publiques examples/ ne doivent jamais accueillir un dossier client.
    repository = SKILL_DIR.parent.parent
    if (repository / ".git").exists() and repository in target.parents:
        relative = target.relative_to(repository)
        if relative.parts[0] not in ("dossiers", "archives"):
            raise BinderError("dans le dépôt, créer les dossiers privés sous dossiers/ ou archives/")
    identifier = identifier or "dossier_" + uuid.uuid4().hex[:12]
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", identifier):
        raise BinderError("identifiant pseudonyme attendu : 3 à 64 caractères a-z, chiffres, _ ou -")
    if profession not in ("nutrition", "restauration"):
        raise BinderError("métier attendu : nutrition ou restauration")
    files = input_files(Path(source)) if source else []
    if source:
        if not (Path(source) / "profile.yaml").is_file():
            raise BinderError("source sans profile.yaml")
        hashes(files, Path(source))  # Refuser les liens avant toute copie.
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".dossier-", dir=target.parent))
    try:
        if source:
            for path in files:
                if path.name == "professional.yaml":
                    continue
                destination = stage / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        else:
            atomic_text(stage / "profile.yaml", "version: 2\n")
            (stage / "weeks").mkdir()
        atomic_text(stage / "professional.yaml", yaml.safe_dump({"version": 1, "dossier_id": identifier, "metier": profession}))
        path, data = journal(stage, "duplication" if source else "creation", {"dossier_id": identifier})
        atomic_batch({path: data})
        os.replace(stage, target)
        return {"version": 1, "dossier_id": identifier, "metier": profession, "dossier": str(target)}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def review_status(directory):
    directory = Path(directory)
    path = directory / "out/review.json"
    if not path.exists():
        return {"version": 1, "revue_actuelle": False, "motif": "aucune revue enregistrée"}
    record = load_json(path)
    manifest = make_manifest(analyse(directory, complete=True))
    current = all(record.get(key) == manifest[key] for key in ("entrees", "moteur_fichiers", "analyse_sha256"))
    document = directory / "out/classeur.md"
    from manifest import digest
    current = current and document.is_file() and digest(document.read_bytes()) == record.get("document_sha256")
    return {"version": 1, "revue_actuelle": bool(current), "decision": record.get("decision"),
            "relecteur": record.get("relecteur"), "note": record.get("note"),
            "motif": "revue liée aux données et au document actuels" if current else "entrées, moteur, calculs ou document modifiés"}


def record_review(directory, reviewer, note, decision="revu"):
    directory = Path(directory)
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", reviewer):
        raise BinderError("identifiant pseudonyme de relecteur requis")
    if decision not in ("revu", "a_revoir"):
        raise BinderError("décision attendue : revu ou a_revoir")
    with locked(directory):
        ctx = analyse(directory, complete=True)
        manifest = make_manifest(ctx)
        if decision == "revu" and (any(i.level == "erreur" for i in ctx.issues) or required_budget_unverified(ctx)):
            raise BinderError("revue ne peut pas valider des erreurs ou un budget impératif invérifiable")
        document = directory / "out/classeur.md"
        rendered_manifest = load_json(directory / "out/manifest.json")
        if any(rendered_manifest.get(key) != manifest[key] for key in ("entrees", "moteur_fichiers", "analyse_sha256")):
            raise BinderError("rendu obsolète : relancer render avant la revue")
        from render import render_classeur
        expected = render_classeur(ctx, ctx.shops, ctx.final_stock, [], generated_on=rendered_manifest["date_generation"])
        if not document.is_file() or document.read_text(encoding="utf-8").rstrip() != expected.rstrip():
            raise BinderError("document différent du calcul : relancer render avant la revue")
        from manifest import digest
        record = {"version": 1, "decision": decision, "relecteur": reviewer, "note": note,
                  "date_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                  "document_sha256": digest(document.read_bytes()),
                  **{key: manifest[key] for key in ("entrees", "moteur_fichiers", "analyse_sha256")},
                  "limites": [i.__dict__ for i in ctx.issues if i.level != "erreur"]}
        path, data = journal(directory, "revue_humaine", {"decision": decision, "relecteur": reviewer,
                                                          "analyse_sha256": manifest["analyse_sha256"]})
        atomic_batch({directory / "out/review.json": encode(record).encode("utf-8"), path: data})
        return record


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--id", dest="identifier")
    parser.add_argument("--profession", choices=("nutrition", "restauration"), default="nutrition")
    parser.add_argument("--reviewer")
    parser.add_argument("--note", default="")
    parser.add_argument("--decision", choices=("revu", "a_revoir"), default="revu")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command in ("init", "clone"):
            if args.command == "clone" and args.source is None:
                raise BinderError("clone nécessite --source")
            result = create_workspace(args.dir, source=args.source if args.command == "clone" else None,
                                      identifier=args.identifier, profession=args.profession)
        elif args.command == "review-status":
            result = review_status(args.dir)
        elif args.command == "review":
            if not args.reviewer:
                raise BinderError("review nécessite --reviewer avec un identifiant pseudonyme")
            result = record_review(args.dir, args.reviewer, args.note, args.decision)
        elif args.command == "archive":
            if args.output is None:
                raise BinderError("archive nécessite --output vers un dossier nouveau")
            with locked(args.dir):
                date = None
                if (args.dir / "out/manifest.json").exists():
                    date = load_json(args.dir / "out/manifest.json").get("date_generation")
                result = snapshot(analyse(args.dir, complete=True), args.output, date)
        else:
            path = args.dir / "history.jsonl"
            result = {"version": 1, "evenements": [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []}
        print(encode(result), end="")
        return 1 if args.command == "review-status" and not result["revue_actuelle"] else 0
    except DataError as exc:
        print(encode({"version": 1, "ecarts": [i.__dict__ for i in exc.issues]}), end="")
        return 1
    except (BinderError, OSError, ValueError) as exc:
        print(encode({"version": 1, "erreur": str(exc)}), end="")
        return 2
