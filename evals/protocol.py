"""Corpus professionnel fictif : préparer, exécuter explicitement et noter séparément."""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills/meal-binder/scripts"))
from core import BinderError, DataError, load_json, load_yaml, utf8_stdio  # noqa: E402
from checks import analyse  # noqa: E402
from manifest import INPUTS, digest, encode, engine_files, hashes, input_files  # noqa: E402
from core import SKILL_DIR  # noqa: E402
from storage import atomic_text, atomic_write, safe_destination  # noqa: E402
from privacy import private_destination  # noqa: E402
from score import score_run  # noqa: E402
from runner import run_command  # noqa: E402

RUBRIC = ("etapes", "quantites", "durees", "materiel", "conservation")
FROZEN_INPUTS = tuple(name for name in INPUTS if name != "plan.yaml")


def runtime_hashes(directory):
    root = Path(directory) / "runtime"
    return hashes(sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"), root)



def prepare(target, repetitions=3, case_ids=None):
    if type(repetitions) is not int or not 1 <= repetitions <= 3:
        raise BinderError("une à trois répétitions par scénario")
    target = private_destination(target)
    if target.exists():
        raise BinderError("destination nouvelle requise")
    corpus = load_yaml(ROOT / "evals/corpus.yaml")
    cases = corpus["cas"]
    if corpus.get("version") != 1 or len(cases) != 24 or len({c["id"] for c in cases}) != 24:
        raise BinderError("corpus attendu : 24 scénarios distincts, version 1")
    if case_ids:
        if set(case_ids) - {c["id"] for c in cases}:
            raise BinderError("scénario inconnu")
        cases = [c for c in cases if c["id"] in case_ids]
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".eval-", dir=target.parent))
    try:
        private_destination(stage)
        for path in [*engine_files(), SKILL_DIR / "SKILL.md", *SKILL_DIR.joinpath("references").glob("*.md")]:
            destination = stage / "runtime" / path.relative_to(SKILL_DIR)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
        for case in cases:
            for repeat in range(1, repetitions + 1):
                directory = stage / f"{case['id']}-{repeat}"
                directory.mkdir()
                atomic_text(directory / "profile.yaml", yaml.safe_dump(case["profil"], allow_unicode=True, sort_keys=False))
                if case["id"] == "N06":
                    shutil.copyfile(SKILL_DIR / "data/ciqual2025/provenance.yaml", directory / "provenance.yaml")
                if case["id"] == "R08":
                    atomic_text(directory / "pantry.yaml", "stock:\n- id: carotte\n  quantite: null\n  unite: g\n")
                task = ("Utiliser le skill meal-binder pour générer ce dossier fictif, sans modifier le profil, le stock ni les sources.\n"
                        "Lire les instructions du skill dans ../runtime/SKILL.md et ses références ; les scripts sont sous ../runtime/scripts/.\n"
                        "Produire plan.yaml, weeks/*.json et out/classeur.md avec les scripts.\n"
                        "Ne pas inventer de prix ni corriger les inconnues par des zéros.\n"
                        "Ne pas poser de question : conserver les impératifs et livrer les diagnostics non résolus.\n"
                        f"Scénario : {case['titre']} ({case['metier']}).\n"
                        + "\n".join("- " + point for point in case["relecture"]) + "\n")
                atomic_text(directory / "task.txt", task)
                atomic_text(directory / "run.json", encode({"version": 1, "cas": case["id"], "repetition": repeat,
                                                            "metier": case["metier"], "statut": "prepare",
                                                            "prompt_sha256": digest(task.encode("utf-8")),
                                                            "corpus_sha256": digest((ROOT / "evals/corpus.yaml").read_bytes()),
                                                            "protocole_sha256": digest(Path(__file__).read_bytes()),
                                                            "runner_sha256": digest(Path(__file__).with_name("runner.py").read_bytes()),
                                                            "entrees_initiales": hashes([directory / n for n in FROZEN_INPUTS if (directory / n).exists()], directory),
                                                            "moteur_fichiers": hashes(engine_files(), SKILL_DIR),
                                                            "runtime_fichiers": runtime_hashes(stage)}))
                atomic_text(directory / "human.template.json", encode({"version": 1, "relecteur": None,
                            "notes": {key: None for key in RUBRIC}, "defauts_critiques": None, "commentaire": None}))
        os.replace(stage, target)
        return {"version": 1, "scenarios": len(cases), "generations_preparees": len(cases) * repetitions, "generations_executees": 0}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def verify_inputs(directory, run):
    paths = [directory / name for name in FROZEN_INPUTS if (directory / name).exists()]
    if hashes(paths, directory) != run["entrees_initiales"]:
        raise BinderError("entrées imposées modifiées ou ajout de configuration non autorisé ; résultat invalide")
    if runtime_hashes(directory.parent) != run.get("runtime_fichiers"):
        raise BinderError("moteur portable ou instructions modifiés après préparation")

    if digest((directory / "task.txt").read_bytes()) != run["prompt_sha256"]:
        raise BinderError("consigne modifiée après préparation")
    if hashes(engine_files(), SKILL_DIR) != run["moteur_fichiers"]:
        raise BinderError("moteur différent du protocole préparé")
    if run.get("corpus_sha256") != digest((ROOT / "evals/corpus.yaml").read_bytes()) or run.get("protocole_sha256") != digest(Path(__file__).read_bytes()):
        raise BinderError("corpus ou protocole différent de la préparation")
    if run.get("runner_sha256") != digest(Path(__file__).with_name("runner.py").read_bytes()):
        raise BinderError("runner différent de la préparation")


def evaluate(directory, reviews_dir=None):
    directory = Path(directory)
    run = load_json(directory / "run.json")
    if run.get("statut") not in ("execute", "termine"):
        raise BinderError("génération non exécutée : aucun score ne doit être attribué")
    verify_inputs(directory, run)
    produced = bool(list(directory.joinpath("weeks").glob("*.json")))
    score = score_run(directory) if produced else None
    if score is not None:
        score.pop("run", None)
        if "codes" in score:
            score["codes"] = dict(score["codes"])
    missing = [name for name in ("plan.yaml", "out/classeur.md") if not (directory / name).is_file()]
    if score is not None and (run.get("code_agent") != 0 or missing):
        score.update(conforme=False, taux=0, generation_interrompue=run.get("code_agent") != 0,
                     sorties_manquantes=missing)
    result = {"version": 1, "cas": run["cas"], "repetition": run["repetition"],
              "modele": run["modele"], "agent": run["agent"], "duree_secondes": run["duree_secondes"],
              "cout_eur": run.get("cout_eur"), "tokens": run.get("tokens"),
              "automatique": score, "humain": None,
              "execution": {"code_agent": run.get("code_agent"), "recettes_produites": produced,
                            "sorties_manquantes": missing}}
    # Nothing in the agent's writable workspace can authorize a human review.
    # Persist automatic results only, even when displaying an external review.
    atomic_text(directory / "evaluation.json", encode(result))
    if reviews_dir is not None:
        result["humain"] = human_review(directory, reviews_dir)
    return result


def validate_human(human):
    if (not isinstance(human, dict) or type(human.get("version")) is not int or human["version"] != 1
        or not isinstance(human.get("relecteur"), str) or not human["relecteur"].strip()
        or not isinstance(human.get("notes"), dict) or set(human["notes"]) != set(RUBRIC)
        or any(type(v) is not int or not 1 <= v <= 5 for v in human["notes"].values())
        or not isinstance(human.get("defauts_critiques"), list)
        or any(not isinstance(v, str) for v in human["defauts_critiques"])
        or (human.get("commentaire") is not None and not isinstance(human["commentaire"], str))):
        raise BinderError("grille humaine incomplète ou invalide")


def external_review_path(directory, target):
    root = safe_destination(directory).parent
    target = safe_destination(target)
    if target == root or root in target.parents or target in root.parents:
        raise BinderError("revue humaine : chemin extérieur à tout le dossier d'exécution requis")
    return target


def review_binding(directory):
    paths = input_files(directory) + [directory / "run.json"]
    paths += [directory / name for name in ("out/classeur.md", "out/manifest.json") if (directory / name).exists()]
    return hashes(paths, directory)


def review_record_path(directory, reviews_dir):
    destination = external_review_path(directory, reviews_dir)
    key = digest(str(safe_destination(directory)).encode("utf-8"))
    return destination / (key + ".json")


def import_human_review(directory, review_file, reviews_dir):
    """Explicit operator action, separate from run/evaluate and agent output."""
    directory = safe_destination(directory)
    review_file = external_review_path(directory, review_file)
    private_destination(external_review_path(directory, reviews_dir))
    result = evaluate(directory)
    if not result["execution"]["recettes_produites"]:
        raise BinderError("aucune recette produite : aucune évaluation humaine possible")
    human = load_json(review_file)
    validate_human(human)
    record = {"version": 1, "entrees": review_binding(directory), "humain": human}
    target = review_record_path(directory, reviews_dir)
    if target.exists():
        raise BinderError("revue externe existante protégée ; utiliser un nouveau dossier de revues")
    atomic_text(target, encode(record))
    return {"version": 1, "revue_importee": True, "fichier": str(target)}


def human_review(directory, reviews_dir):
    path = review_record_path(directory, reviews_dir)
    if not path.exists():
        return None
    record = load_json(safe_destination(path))
    if record.get("version") != 1 or record.get("entrees") != review_binding(directory):
        return None
    validate_human(record.get("humain"))
    return record["humain"]


def execute(directory, command, model, agent, timeout=600):
    directory = Path(directory)
    run = load_json(directory / "run.json")
    if run.get("statut") != "prepare":
        raise BinderError("une génération enregistrée n'est pas relancée ni remplacée")
    if not isinstance(command, list) or not command or any(not isinstance(part, str) for part in command):
        raise BinderError("commande attendue : liste JSON non vide d'arguments, sans shell")
    verify_inputs(directory, run)
    task = (directory / "task.txt").read_text(encoding="utf-8")
    args = [part.replace("{task}", task).replace("{dir}", str(directory.resolve())) for part in command]
    start = time.monotonic()
    try:
        code, stdout, stderr, logs = run_command(args, directory, timeout)
    except OSError as exc:
        code, stdout, stderr, logs = 127, b"", str(exc).encode("utf-8"), {}
    run.update(statut="execute", modele=model, agent=agent, duree_secondes=time.monotonic() - start,
               code_agent=code, cout_eur=None, tokens=None,
               commande_sha256=digest(encode(command).encode("utf-8")), journaux=logs)
    usages = []
    for line in stdout.decode("utf-8", errors="replace").splitlines() if not logs.get("stdout", {}).get("tronque") else []:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            usages.append(event["usage"])
    if usages:
        keys = {key for usage in usages for key, value in usage.items() if type(value) is int and value >= 0}
        run["tokens"] = {key: sum(usage.get(key, 0) for usage in usages) for key in sorted(keys)}
    atomic_write(directory / "agent.stdout.txt", stdout)
    atomic_write(directory / "agent.stderr.txt", stderr)
    atomic_text(directory / "run.json", encode(run))
    return evaluate(directory)


def summarize(directory, reviews_dir=None):
    runs = []
    for path in sorted(Path(directory).glob("*/run.json")):
        metadata = load_json(path)
        result = {"cas": metadata["cas"], "repetition": metadata["repetition"], "statut": metadata["statut"]}
        evaluation = path.parent / "evaluation.json"
        if evaluation.exists():
            value = load_json(evaluation)
            human = human_review(path.parent, reviews_dir) if reviews_dir is not None else None
            result.update(conforme=value["automatique"].get("conforme", False) if value["automatique"] else None,
                          recettes_produites=value.get("execution", {}).get("recettes_produites", False),
                          relecture_humaine=human is not None,
                          defauts_critiques=human.get("defauts_critiques") if human else None)
        runs.append(result)
    return {"version": 1, "generations_preparees": len(runs),
            "tentatives_lancees": sum(r["statut"] != "prepare" for r in runs),
            "generations_produites": sum(r.get("recettes_produites", False) for r in runs),
            "revues_humaines": sum(r.get("relecture_humaine", False) for r in runs), "executions": runs}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "evaluate", "summarize", "review"))
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--case", dest="cases", action="append", help="limiter la préparation à un identifiant de scénario")
    parser.add_argument("--agent-command", help='liste JSON, ex. ["codex", "exec", "{task}"]')
    parser.add_argument("--model")
    parser.add_argument("--agent")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--review-file", type=Path)
    parser.add_argument("--reviews-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare": result = prepare(args.dir, args.repetitions, args.cases)
        elif args.command == "evaluate": result = evaluate(args.dir, args.reviews_dir)
        elif args.command == "summarize": result = summarize(args.dir, args.reviews_dir)
        elif args.command == "review":
            if args.review_file is None or args.reviews_dir is None:
                raise BinderError("review nécessite --review-file et --reviews-dir hors de l'espace d'exécution")
            result = import_human_review(args.dir, args.review_file, args.reviews_dir)
        else:
            if not args.agent_command or not args.model or not args.agent or not 1 <= args.timeout <= 3600:
                raise BinderError("agent, modèle, commande explicite et délai entre 1 et 3600 s requis")
            result = execute(args.dir, json.loads(args.agent_command), args.model, args.agent, args.timeout)
        print(encode(result), end="")
        return 0
    except (BinderError, OSError, ValueError) as exc:
        print(encode({"version": 1, "erreur": str(exc)}), end="")
        return 1


if __name__ == "__main__":
    utf8_stdio()
    sys.exit(main())
