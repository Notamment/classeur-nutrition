"""Écritures UTF-8 atomiques, sans suivre de lien symbolique de sortie."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from core import BinderError


def safe_destination(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise BinderError(f"sortie protégée : lien symbolique {part.name}")
    return path


def atomic_write(path, data):
    path = safe_destination(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_text(path, text):
    atomic_write(path, text.replace("\r\n", "\n").encode("utf-8"))


def write_render(path, text):
    """Un document utilisateur n'est jamais assimilé à une sortie générée."""
    path = safe_destination(path)
    if path.exists():
        if not path.is_file():
            raise BinderError("sortie protégée : fichier ordinaire requis")
        previous = path.read_text(encoding="utf-8")
        if "par meal-binder." not in previous or not previous.startswith("# "):
            raise BinderError(f"sortie protégée : {path.name} n'est pas un rendu reconnu")
    atomic_text(path, text)
