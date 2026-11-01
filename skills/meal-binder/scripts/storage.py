"""Écritures UTF-8 atomiques, sans suivre de lien symbolique de sortie."""
from __future__ import annotations

import os
import stat
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path

from core import BinderError


def _reject_links(path):
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise BinderError(f"sortie protégée : lien ou point de réanalyse {part.name}")


def safe_destination(path):
    # Reject traversal before resolution: absent/../link hides a link from lstat.
    if ".." in Path(path).parts:
        raise BinderError("sortie protégée : segment parent '..' interdit")
    path = Path(path).absolute()
    _reject_links(path)
    if os.name == "nt":
        # Windows 8.3 aliases (RUNNER~1) must compare equal to long paths in
        # containment checks. Inspect both spellings; never resolve first.
        path = path.resolve()
        _reject_links(path)
    return path


@contextmanager
def _parent(path):
    """Pin the parent on POSIX; no component is opened through a symlink."""
    if os.name != "posix":
        safe_destination(path).mkdir(parents=True, exist_ok=True)
        safe_destination(path)
        yield None
        return
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in path.parts[1:]:
            try:
                os.mkdir(name, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def _location(parent, descriptor, name):
    if descriptor is not None:
        return name, {"dir_fd": descriptor}
    return safe_destination(parent / name), {}


def _regular(parent, descriptor, name):
    path, kwargs = _location(parent, descriptor, name)
    try:
        info = os.stat(path, follow_symlinks=False, **kwargs)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise BinderError("sortie protégée : fichier ordinaire sans lien requis")
    return True


def _read(parent, descriptor, name):
    path, kwargs = _location(parent, descriptor, name)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), **kwargs)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise BinderError("sortie protégée : fichier ordinaire requis")
        return stream.read()


def _temporary(parent, descriptor, prefix, data):
    name = prefix + uuid.uuid4().hex
    path, kwargs = _location(parent, descriptor, name)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600, **kwargs)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        _unlink(parent, descriptor, name)
        raise
    return name


def _replace(parent, descriptor, source, destination):
    _regular(parent, descriptor, destination)
    if descriptor is not None:
        os.replace(source, destination, src_dir_fd=descriptor, dst_dir_fd=descriptor)
    else:
        os.replace(safe_destination(parent / source), safe_destination(parent / destination))


def _unlink(parent, descriptor, name):
    path, kwargs = _location(parent, descriptor, name)
    try:
        os.unlink(path, **kwargs)
    except FileNotFoundError:
        pass


def atomic_write(path, data):
    atomic_batch({path: data})


def atomic_text(path, text):
    atomic_write(path, text.replace("\r\n", "\n").encode("utf-8"))


def atomic_batch(contents):
    """Transaction de fichiers ; préserver les sauvegardes si le disque refuse le retour."""
    with ExitStack() as handles:
        staged, backups, parents, committed = {}, {}, {}, []
        success = False
        try:
            for raw, data in contents.items():
                path = safe_destination(raw)
                if path.parent not in parents:
                    parents[path.parent] = handles.enter_context(_parent(path.parent))
                fd = parents[path.parent]
                if _regular(path.parent, fd, path.name):
                    backups[path] = _temporary(path.parent, fd, ".backup-", _read(path.parent, fd, path.name))
                staged[path] = _temporary(path.parent, fd, ".transaction-", data)
            try:
                for path, stage in staged.items():
                    _replace(path.parent, parents[path.parent], stage, path.name)
                    committed.append(path)
            except (OSError, BinderError):
                for path in reversed(committed):
                    if path in backups:
                        _replace(path.parent, parents[path.parent], backups[path], path.name)
                    else:
                        _unlink(path.parent, parents[path.parent], path.name)
                raise
            success = True
        finally:
            for path, stage in staged.items():
                _unlink(path.parent, parents[path.parent], stage)
            for path, backup in backups.items():
                if success or path not in committed:
                    _unlink(path.parent, parents[path.parent], backup)


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
