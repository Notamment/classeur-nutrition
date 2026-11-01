"""Cooperative workspace lock shared by all document writers."""
import contextlib
import json
import os
import uuid
from pathlib import Path

from core import BinderError
from storage import safe_destination


@contextlib.contextmanager
def locked(directory):
    path = safe_destination(Path(directory) / ".dossier.lock")
    token = uuid.uuid4().hex
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise BinderError("dossier occupé ; vérifier le processus propriétaire avant de retirer .dossier.lock") from exc
    except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
        raise BinderError("dossier de travail introuvable ou inaccessible") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "pid": os.getpid(), "token": token}, stream)
        yield
    finally:
        try:
            with path.open(encoding="utf-8") as stream:
                record = json.loads(stream.read(4096))
            owned = record.get("token") == token
        except (OSError, ValueError, AttributeError):
            owned = False
        if not owned:
            raise BinderError("verrou du dossier retiré ou remplacé pendant l'opération ; vérifier les sorties")
        path.unlink()
