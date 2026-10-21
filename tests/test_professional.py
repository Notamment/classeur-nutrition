"""Contrats professionnels : données explicites, protection et traçabilité."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_binder import codes
from test_profiles_v2 import workspace
from test_regressions import cli
from checks import analyse, preference_counts
from core import BinderError
from storage import atomic_text
from manifest import snapshot, verify_snapshot


class TestStructuredDiagnostics(unittest.TestCase):
    def test_legacy_render_keeps_missing_sourced_proteins_explicit(self):
        with workspace({"version": 1}) as d:
            week_path = d / "weeks/S01.json"
            week = json.loads(week_path.read_text(encoding="utf-8"))
            week["cuisine"] = "Exemple fictif"
            week_path.write_text(json.dumps(week), encoding="utf-8")
            (d / "provenance.yaml").write_text("version: 1\nexiger_sources: true\naliments: {}\n", encoding="utf-8")
            result = cli(d, "render")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("valeur inconnue, jamais zéro", (d / "out/classeur.md").read_text(encoding="utf-8"))
            self.assertIn("nutrition_absente", {i["code"] for i in json.loads(result.stdout)})

    def test_translating_messages_never_changes_preference_counts(self):
        with workspace({"repas": {"difficulte_max": "facile", "duree_active_max_min": 1},
                        "exigences": {"difficulte": "preference", "duree_active": "preference"}}) as d:
            ctx = analyse(d)
            self.assertEqual(preference_counts(ctx), (0, 2))
            for issue in ctx.issues:
                issue.msg = "Translated message without status keywords"
            self.assertEqual(preference_counts(ctx), (0, 2))
            self.assertTrue(all(i.kind == "unknown" and i.requirement == "preference"
                                for i in ctx.issues if i.code in {"difficulte", "duree_active"}))

    def test_cli_keeps_legacy_fields_and_exposes_machine_readable_reason(self):
        with workspace({"repas": {"difficulte_max": "facile"}}) as d:
            result = cli(d)
            self.assertEqual(result.returncode, 1)
            issue = next(i for i in json.loads(result.stdout) if i["code"] == "difficulte")
            self.assertTrue({"level", "code", "where", "msg"} <= issue.keys())
            self.assertEqual((issue["kind"], issue["requirement"]), ("unknown", "imperative"))


class TestAtomicOutputs(unittest.TestCase):
    def test_failed_file_replace_preserves_previous_output(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "classeur.md"
            path.write_text("Document précédent", encoding="utf-8")
            with patch("storage.os.replace", side_effect=OSError("disque indisponible")):
                with self.assertRaises(OSError):
                    atomic_text(path, "Nouveau document")
            self.assertEqual(path.read_text(encoding="utf-8"), "Document précédent")
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_render_never_replaces_user_document(self):
        with workspace() as d:
            (d / "out").mkdir()
            target = d / "out/classeur.md"
            target.write_text("# Mes notes\nÀ conserver.", encoding="utf-8")
            result = cli(d, "render")
            self.assertEqual(result.returncode, 2)
            self.assertIn("À conserver", target.read_text(encoding="utf-8"))

    def test_selection_restoration_failure_keeps_recoverable_backup(self):
        from selection import select_proposals, save_selection
        from test_selection import proposal
        with workspace() as d:
            proposal(d, "ancienne")
            target = save_selection(select_proposals(d), d)
            previous = (target / "rapport.json").read_bytes()
            real_replace, calls = os.replace, 0

            def fail_after_backup(source, destination):
                nonlocal calls
                calls += 1
                if calls >= 2:
                    raise OSError("remplacement et restauration indisponibles")
                return real_replace(source, destination)

            with patch("selection.os.replace", side_effect=fail_after_backup), self.assertRaises(OSError):
                save_selection(select_proposals(d), d)
            backups = list((d / "out").glob(".selection-backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "rapport.json").read_bytes(), previous)

    def test_output_directory_symlink_is_refused(self):
        with workspace() as d, tempfile.TemporaryDirectory() as external:
            try:
                (d / "out").symlink_to(external, target_is_directory=True)
            except OSError:
                self.skipTest("création de liens symboliques indisponible")
            self.assertEqual(cli(d, "render").returncode, 2)
            self.assertEqual(list(Path(external).iterdir()), [])


class TestReproducibleSnapshots(unittest.TestCase):
    def test_modified_rendered_document_is_detected(self):
        with workspace() as d, tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "archive"
            snapshot(analyse(d, complete=True), archive)
            (archive / "out/classeur.md").write_text("# Document modifié", encoding="utf-8")
            self.assertFalse(verify_snapshot(archive)["integre"])

    def test_parent_traversal_cannot_hide_source_descendant(self):
        with workspace() as d:
            sibling = d.parent / "intermediaire"
            target = sibling / ".." / d.name / "archive"
            with self.assertRaises(BinderError):
                snapshot(analyse(d, complete=True), target)

    def test_snapshot_is_autonomous_and_identical_across_processes(self):
        with workspace() as d, tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "archive"
            snapshot(analyse(d, complete=True), archive, "2026-01-02")
            self.assertIn("Généré le 2026-01-02", (archive / "out/classeur.md").read_text(encoding="utf-8"))
            self.assertTrue(verify_snapshot(archive)["integre"])
            result = cli(archive, "verify-snapshot")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(json.loads(result.stdout)["integre"])
            (d / "profile.yaml").unlink()
            self.assertTrue(verify_snapshot(archive)["integre"])

    def test_input_change_and_addition_are_detected(self):
        with workspace() as d, tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "archive"
            snapshot(analyse(d, complete=True), archive)
            (archive / "pantry.yaml").write_text("stock: []\n", encoding="utf-8")
            self.assertFalse(verify_snapshot(archive)["integre"])
            (archive / "pantry.yaml").unlink()
            (archive / "profile.yaml").write_text("version: 2\n", encoding="utf-8")
            self.assertIn("entrees/profile.yaml : modifié", verify_snapshot(archive)["differences"])

    def test_changed_engine_is_reported_without_executing_archived_code(self):
        with workspace() as d, tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "archive"
            snapshot(analyse(d, complete=True), archive)
            engine = archive / ".runtime/meal-binder/scripts/binder.py"
            engine.write_text("raise RuntimeError('ne jamais exécuter')", encoding="utf-8")
            result = cli(archive, "verify-snapshot")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("modifié", result.stdout)
            self.assertNotIn("Traceback", result.stderr)

    def test_snapshot_refuses_overwrite_and_source_descendants(self):
        with workspace() as d:
            ctx = analyse(d, complete=True)
            for destination in (d, d / "archive", d.parent):
                with self.subTest(destination=destination), self.assertRaises(BinderError):
                    snapshot(ctx, destination)

    def test_fixed_date_makes_repeated_render_and_manifest_identical(self):
        with workspace() as d:
            self.assertEqual(cli(d, "render", "--date", "2026-01-02").returncode, 0)
            first = [(d / name).read_bytes() for name in ("out/classeur.md", "out/manifest.json")]
            self.assertEqual(cli(d, "render", "--date", "2026-01-02").returncode, 0)
            self.assertEqual(first, [(d / name).read_bytes() for name in ("out/classeur.md", "out/manifest.json")])
