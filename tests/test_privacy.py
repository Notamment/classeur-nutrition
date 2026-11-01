"""Private outputs use the destination checkout's ignore policy."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_binder import ROOT
from test_profiles_v2 import workspace
from core import BinderError
from checks import analyse
from manifest import snapshot
from privacy import private_destination
from search import search
from workflow import create_workspace


@unittest.skipUnless(shutil.which("git"), "git required")
class TestPrivateDestinations(unittest.TestCase):
    def repository(self, parent):
        repo = parent / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
        shutil.copyfile(ROOT / ".gitignore", repo / ".gitignore")
        return repo

    def test_all_private_writers_reject_public_destination_before_writing(self):
        with tempfile.TemporaryDirectory() as temp, workspace() as source:
            repo = self.repository(Path(temp))
            for action in (lambda p: create_workspace(p), lambda p: create_workspace(p, source=source),
                           lambda p: snapshot(analyse(source, complete=True), p),
                           lambda p: search(source, output=p)):
                target = repo / "examples" / "client_fixture"
                with self.subTest(action=action), self.assertRaisesRegex(BinderError, "destination privée refusée"):
                    action(target)
                self.assertFalse(target.exists())
            created = repo / "dossiers" / "client_épreuve"
            create_workspace(created)
            visible = subprocess.check_output(["git", "-C", str(repo), "ls-files", "--others", "--exclude-standard", "-z"])
            self.assertEqual(visible, b".gitignore\0")

    def test_tracked_files_are_not_protected_by_later_ignore_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self.repository(Path(temp))
            target = repo / "dossiers" / "client"
            target.mkdir(parents=True)
            (target / "profile.yaml").write_text("version: 2\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "-f", "dossiers/client/profile.yaml"], check=True)
            with self.assertRaises(BinderError):
                private_destination(target)

    def test_worktree_pointer_file_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self.repository(root)
            subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                            "commit", "-qm", "fixture"], check=True)
            worktree = root / "worktree"
            subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(worktree)], check=True, capture_output=True)
            self.assertTrue((worktree / ".git").is_file())
            with self.assertRaises(BinderError):
                create_workspace(worktree / "examples" / "client")
            create_workspace(worktree / "dossiers" / "client")
