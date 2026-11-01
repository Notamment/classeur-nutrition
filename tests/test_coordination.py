"""Writers cooperate across CLI processes and reject stale computations."""
import json
import io
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from test_profiles_v2 import workspace
from test_regressions import cli
from test_selection import proposal
from core import BinderError
from coordination import locked
from selection import select_proposals, save_selection
from workflow import record_review, review_status
import storage
import selection


class TestWorkspaceCoordination(unittest.TestCase):
    def test_missing_workspace_is_a_controlled_input_error(self):
        with workspace() as d:
            for command in ("render", "audit", "select"):
                result = cli(d / "missing", command)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                json.loads(result.stdout)
                self.assertNotIn("Traceback", result.stderr)
            self.assertFalse((d / "missing").exists())

    def test_cli_writers_refuse_a_lock_held_by_another_process(self):
        with workspace() as d:
            proposal(d, "fixture")
            with locked(d):
                for command, args in (("render", ()), ("audit", ()), ("select", ()),
                                      ("snapshot", ("--output", str(d.parent / "archive"))),
                                      ("use-data", ("--edition", "ciqual2025"))):
                    result = cli(d, command, *args)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("dossier occupé", result.stdout)
                    json.loads(result.stdout)
                self.assertEqual(cli(d, "check-all").returncode, 0)
            self.assertFalse((d / "out").exists())
            self.assertFalse((d / "provenance.yaml").exists())
            self.assertEqual(cli(d, "render").returncode, 0)

    def test_failed_operation_releases_lock_but_replaced_lock_is_preserved(self):
        with workspace() as d:
            with self.assertRaises(ValueError):
                with locked(d):
                    raise ValueError("fixture")
            self.assertFalse((d / ".dossier.lock").exists())
            with self.assertRaisesRegex(BinderError, "remplacé"):
                with locked(d):
                    (d / ".dossier.lock").write_text('{"token":"another_owner"}', encoding="utf-8")
            self.assertEqual(json.loads((d / ".dossier.lock").read_text())["token"], "another_owner")

    def test_stale_selection_cannot_replace_the_previous_output(self):
        for change in ("profile", "proposal", "new_proposal"):
            with self.subTest(change=change), workspace() as d:
                proposal(d, "fixture")
                target = save_selection(select_proposals(d), d)
                before = (target / "out/classeur.md").read_bytes()
                calculated = select_proposals(d)
                if change == "profile":
                    with (d / "profile.yaml").open("a", encoding="utf-8") as f:
                        f.write("\n# updated input\n")
                elif change == "proposal":
                    path = d / "propositions/fixture/weeks/S01.json"
                    data = json.loads(path.read_text())
                    data["recettes"][0]["ingredients"][0]["qte"] *= 2
                    path.write_text(json.dumps(data), encoding="utf-8")
                else:
                    proposal(d, "new")
                with self.assertRaisesRegex(BinderError, "obsolète"):
                    save_selection(calculated, d)
                self.assertEqual((target / "out/classeur.md").read_bytes(), before)
                self.assertFalse((d / ".dossier.lock").exists())

    def test_inputs_changed_during_comparison_are_rejected(self):
        with workspace() as d:
            proposal(d, "fixture")
            original = selection.analyse
            def changed(*args, **kwargs):
                result = original(*args, **kwargs)
                with (d / "profile.yaml").open("a", encoding="utf-8") as f:
                    f.write("\n# changed while comparing\n")
                return result
            with patch("selection.analyse", side_effect=changed):
                with self.assertRaisesRegex(BinderError, "pendant la comparaison"):
                    select_proposals(d)
            self.assertFalse((d / "out").exists())

    def test_document_and_manifest_are_restored_together_after_failure(self):
        from binder import main
        with workspace() as d:
            self.assertEqual(cli(d, "render", "--date", "2026-01-02").returncode, 0)
            paths = [d / "out/classeur.md", d / "out/manifest.json"]
            previous = [p.read_bytes() for p in paths]
            original, calls = storage._replace, 0
            def fail_second(*args):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("fixture failure publishing manifest")
                return original(*args)
            with patch("storage._replace", side_effect=fail_second):
                with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
                    code = main(["render", "--dir", str(d), "--date", "2026-01-03", "--json"])
                self.assertEqual(code, 3)
                self.assertEqual(json.loads(output.getvalue())[0]["code"], "erreur_interne")
            self.assertEqual([p.read_bytes() for p in paths], previous)
            self.assertFalse((d / ".dossier.lock").exists())

    def test_audit_preserves_the_manifest_of_the_reviewed_document(self):
        with workspace() as d:
            cli(d, "render", "--date", "2026-01-02")
            record_review(d, "fixture_review", "Technical test only")
            before = (d / "out/manifest.json").read_bytes()
            self.assertEqual(cli(d, "audit", "--date", "2026-01-03").returncode, 0)
            self.assertEqual((d / "out/manifest.json").read_bytes(), before)
            self.assertEqual(json.loads((d / "out/audit.manifest.json").read_text())["date_generation"], "2026-01-03")
            self.assertTrue(review_status(d)["revue_actuelle"])

    def test_input_change_while_building_selected_output_prevents_publication(self):
        with workspace() as d:
            proposal(d, "fixture")
            target = save_selection(select_proposals(d), d)
            previous = (target / "rapport.json").read_bytes()
            result = select_proposals(d)
            original = selection.render_classeur
            def changed(*args, **kwargs):
                text = original(*args, **kwargs)
                with (d / "profile.yaml").open("a", encoding="utf-8") as f:
                    f.write("\n# changed while writing output\n")
                return text
            with patch("selection.render_classeur", side_effect=changed):
                with self.assertRaisesRegex(BinderError, "avant publication"):
                    save_selection(result, d)
            self.assertEqual((target / "rapport.json").read_bytes(), previous)
            self.assertFalse(list((d / "out").glob(".selection-*")))
