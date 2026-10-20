"""Dossiers isolés, revue invalide après changement, journal local."""
import json
import tempfile
import unittest
from pathlib import Path

from test_profiles_v2 import workspace
from test_regressions import cli
from core import BinderError
from workflow import create_workspace, locked, record_review, review_status


class TestProfessionalWorkspace(unittest.TestCase):
    def test_new_workspace_never_replaces_existing_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "dossier"
            result = create_workspace(target, identifier="client_test", profession="restauration")
            self.assertEqual(result["dossier_id"], "client_test")
            self.assertTrue((target / "profile.yaml").is_file())
            with self.assertRaises(BinderError):
                create_workspace(target)

    def test_clone_changes_identifier_and_never_copies_reviews_or_notes(self):
        with workspace() as source, tempfile.TemporaryDirectory() as temp:
            cli(source, "render")
            record_review(source, "relecteur_test", "Métadonnées déclaratives relues.")
            (source / "notes_privees.txt").write_text("secret", encoding="utf-8")
            target = Path(temp) / "copie"
            create_workspace(target, source=source, identifier="autre_client")
            self.assertFalse((target / "notes_privees.txt").exists())
            self.assertFalse((target / "out/review.json").exists())
            self.assertIn("autre_client", (target / "professional.yaml").read_text(encoding="utf-8"))
            self.assertEqual(cli(target).returncode, 0)

    def test_review_is_invalidated_by_input_or_document_changes(self):
        with workspace() as d:
            self.assertEqual(cli(d, "render").returncode, 0)
            record_review(d, "relecteur_test", "Revue humaine ; limites conservées.")
            self.assertTrue(review_status(d)["revue_actuelle"])
            document = d / "out/classeur.md"
            old = document.read_bytes(); document.write_bytes(old + b'\nModification')
            self.assertFalse(review_status(d)["revue_actuelle"])
            document.write_bytes(old)
            (d / "profile.yaml").write_text((d / "profile.yaml").read_text(encoding="utf-8") + "# modification\n", encoding="utf-8")
            self.assertFalse(review_status(d)["revue_actuelle"])

    def test_human_review_never_overrides_imperative_violation(self):
        with workspace({"repas": {"difficulte_max": "facile"}}) as d:
            cli(d, "render")
            with self.assertRaises(BinderError):
                record_review(d, "relecteur_test", "Tentative de validation")
            self.assertFalse((d / "out/review.json").exists())
            record_review(d, "relecteur_test", "À corriger", decision="a_revoir")
            self.assertEqual(review_status(d)["decision"], "a_revoir")

    def test_concurrent_change_is_refused_and_lock_is_released(self):
        with workspace() as d:
            with locked(d):
                with self.assertRaises(BinderError):
                    with locked(d):
                        pass
            self.assertFalse((d / ".dossier.lock").exists())

    def test_review_refuses_stale_render(self):
        with workspace() as d:
            cli(d, "render")
            (d / "profile.yaml").write_text("version: 2\n", encoding="utf-8")
            with self.assertRaises(BinderError):
                record_review(d, "relecteur_test", "Ancien rendu")
