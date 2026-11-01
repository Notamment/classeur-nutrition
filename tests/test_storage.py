"""Output paths must not redirect writes outside their checked directory."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_binder import ROOT
from core import BinderError
from storage import atomic_batch, atomic_text, safe_destination


class TestProtectedPaths(unittest.TestCase):
    def test_cli_cannot_resolve_away_the_forbidden_segments_before_checking(self):
        from test_profiles_v2 import workspace
        from test_regressions import cli
        with workspace() as external, tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            try:
                (root / "link").symlink_to(external, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks unavailable")
            for path in (root / "link", root / "absent" / ".." / "link"):
                result = cli(path, "render")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertFalse((external / "out").exists())

    def test_missing_segment_then_parent_cannot_hide_a_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            external = base / "external"
            external.mkdir()
            try:
                (base / "link").symlink_to(external, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks unavailable")
            path = base / "absent" / ".." / "link" / "probe.txt"
            with self.assertRaises(BinderError):
                safe_destination(path)
            with self.assertRaises(BinderError):
                atomic_text(path, "must not escape")
            self.assertEqual(list(external.iterdir()), [])

    @unittest.skipUnless(os.name == "posix", "POSIX directory descriptors")
    def test_parent_swap_during_commit_does_not_redirect_either_writer(self):
        for batch in (False, True):
            with self.subTest(batch=batch), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                parent, moved, external = root / "parent", root / "moved", root / "external"
                parent.mkdir(); external.mkdir()
                original = os.replace
                swapped = False

                def swap(source, target, **kwargs):
                    nonlocal swapped
                    if not swapped:
                        parent.rename(moved)
                        parent.symlink_to(external, target_is_directory=True)
                        swapped = True
                    return original(source, target, **kwargs)

                with patch("storage.os.replace", side_effect=swap):
                    if batch:
                        atomic_batch({parent / "one": b"one", parent / "two": b"two"})
                    else:
                        atomic_text(parent / "one", "one")
                self.assertEqual(list(external.iterdir()), [])
                self.assertEqual((moved / "one").read_text(), "one")

    @unittest.skipUnless(os.name == "nt", "Windows junctions")
    def test_windows_junction_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            external, link = root / "external", root / "junction"
            external.mkdir()
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(external)], check=True, capture_output=True)
            try:
                with self.assertRaises(BinderError):
                    atomic_text(link / "probe", "must not escape")
                self.assertEqual(list(external.iterdir()), [])
            finally:
                link.rmdir()

    @unittest.skipUnless(os.name == "nt", "Windows 8.3 paths")
    def test_short_and_long_paths_have_the_same_canonical_destination(self):
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
        api.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        api.restype = wintypes.DWORD
        with tempfile.TemporaryDirectory() as temp:
            long = Path(temp).resolve() / "long_directory_name_for_regression"
            long.mkdir()
            length = api(str(long), None, 0)
            self.assertGreater(length, 0)
            buffer = ctypes.create_unicode_buffer(length)
            self.assertGreater(api(str(long), buffer, length), 0)
            short = Path(buffer.value)
            if short == long:
                self.skipTest("8.3 aliases disabled on this filesystem")
            self.assertEqual(safe_destination(short / "missing" / "leaf"),
                             safe_destination(long / "missing" / "leaf"))
