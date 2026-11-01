"""Check private destinations against their own Git repository, even when installed."""
from __future__ import annotations

import subprocess
from pathlib import Path

from core import BinderError
from storage import safe_destination


def private_destination(target):
    target = safe_destination(target)
    # .git may be a directory or a worktree's pointer file. Do not infer the
    # destination repository from the location of the installed Python package.
    repository = next((p for p in (target, *target.parents) if (p / ".git").exists()), None)
    if repository is None:
        return target
    relative = target.relative_to(repository).as_posix()
    probes = [relative + "/", relative + "/profile.yaml", relative + "/professional.yaml",
              relative + "/weeks/S01.json", relative + "/out/review.json",
              relative + "/history.jsonl", relative + "/rapport.json"]
    try:
        tracked = subprocess.run(["git", "--literal-pathspecs", "-C", str(repository), "ls-files", "--cached", "-z", "--", relative],
                                 capture_output=True, check=True)
        ignored = subprocess.run(["git", "-C", str(repository), "check-ignore", "--no-index", "-z", "--stdin"],
                                 input=("\0".join(probes) + "\0").encode("utf-8"), capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BinderError("destination privée : impossible de vérifier les exclusions Git") from exc
    if ignored.returncode not in (0, 1):
        raise BinderError("destination privée : erreur de vérification des exclusions Git")
    ignored_paths = set(ignored.stdout.decode("utf-8").rstrip("\0").split("\0"))
    if tracked.stdout or not set(probes) <= ignored_paths:
        raise BinderError("destination privée refusée : dossier et futurs fichiers doivent être ignorés par Git, sans fichier suivi ni exception publique")
    return target
