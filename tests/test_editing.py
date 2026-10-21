"""Adaptations transactionnelles, verrouillage et réutilisation après revue."""
import json
import unittest

import yaml

from test_binder import filler, ing, recipe
from test_profiles_v2 import workspace, plan
from test_regressions import cli
from checks import analyse
from core import BinderError, DataError
from editing import adapt
from manifest import hashes, input_files
from workflow import record_review, review_status


class TestEditing(unittest.TestCase):
    def test_preview_is_read_only_and_scaling_keeps_per_portion_values(self):
        with workspace() as d:
            initial = hashes(input_files(d), d)
            before = analyse(d, complete=True)
            old = before.profile["projet"]["portions_par_recette"]
            report = adapt(d, portions=old * 2)
            self.assertTrue(report["applicable"])
            self.assertFalse(report["applique"])
            self.assertEqual(initial, hashes(input_files(d), d))
            adapt(d, portions=old * 2, apply=True)
            after = analyse(d, complete=True)
            for metric in ("poids_pp", "prot_pp", "kcal_pp"):
                self.assertAlmostEqual(getattr(before.calcs["S01-R01"], metric), getattr(after.calcs["S01-R01"], metric))
            self.assertEqual(after.recipes["S01-R01"]["ingredients"][0]["qte"], 12)
            self.assertIn("redimensionnement", (d / "history.jsonl").read_text(encoding="utf-8"))

    def test_locks_prevent_scale_and_replacement(self):
        with workspace() as d:
            self.assertEqual(cli(d, "lock-recipe", "--recipe", "S01-R01").returncode, 0)
            with self.assertRaises(BinderError):
                adapt(d, portions=4, apply=True)
            with self.assertRaises(BinderError):
                adapt(d, recipe_id="S01-R01", replacement=filler("source"), source_portions=2)
            self.assertEqual(cli(d, "unlock-recipe", "--recipe", "S01-R01").returncode, 0)
            self.assertTrue(adapt(d, portions=4)["applicable"])

    def test_imperative_exclusion_cannot_be_offset_by_preferences(self):
        with workspace({"aliments": {"exclus": ["oeuf"]}} , recipes=[recipe("S01-R01", [ing("pomme_de_terre", 300, etat="cru")])]) as d:
            initial = hashes(input_files(d), d)
            report = adapt(d, recipe_id="S01-R01", replacement=filler("source"), source_portions=2)
            self.assertFalse(report["applicable"])
            with self.assertRaises(DataError):
                adapt(d, recipe_id="S01-R01", replacement=filler("source"), source_portions=2, apply=True)
            self.assertEqual(initial, hashes(input_files(d), d))

    def test_unknown_imperative_budget_refuses_commit(self):
        with workspace({"budget": {"plafond_eur_semaine": 100}}) as d:
            initial = hashes(input_files(d), d)
            self.assertFalse(adapt(d, portions=4)["applicable"])
            with self.assertRaises(BinderError):
                adapt(d, portions=4, apply=True)
            self.assertEqual(initial, hashes(input_files(d), d))

    def test_replacement_updates_plan_and_invalidates_review(self):
        with workspace() as d:
            declaration = plan()
            declaration["semaines"][0]["recettes"][0].update(espece_poisson="ancien", soja=True, substitut_industriel=True)
            (d / "plan.yaml").write_text(yaml.safe_dump(declaration), encoding="utf-8")
            self.assertEqual(cli(d, "render").returncode, 0)
            record_review(d, "relecteur_test", "Relecture réelle du dossier de test.")
            source = filler("source"); source["nom"] = "Nouveau plat"
            adapt(d, recipe_id="S01-R01", replacement=source, source_portions=2, apply=True)
            self.assertFalse(review_status(d)["revue_actuelle"])
            entry = yaml.safe_load((d / "plan.yaml").read_text(encoding="utf-8"))["semaines"][0]["recettes"][0]
            self.assertEqual(entry["plat"], "Nouveau plat")
            self.assertNotIn("espece_poisson", entry)
            self.assertFalse(entry["soja"])
            self.assertFalse(entry["substitut_industriel"])
            self.assertEqual(cli(d, "check-plan").returncode, 0)

    def test_library_requires_review_and_keeps_favorites_private(self):
        with workspace() as d:
            args = ("--recipe", "S01-R01", "--name", "plat_revu")
            self.assertEqual(cli(d, "save-recipe", *args).returncode, 2)
            cli(d, "render")
            record_review(d, "relecteur_test", "Relecture réelle du dossier de test.")
            self.assertEqual(cli(d, "save-recipe", *args).returncode, 0)
            self.assertEqual(cli(d, "save-recipe", *args).returncode, 2)
            self.assertEqual(cli(d, "favorite", "--name", "plat_revu").returncode, 0)
            listing = json.loads(cli(d, "library").stdout)
            self.assertTrue(listing["recettes"][0]["favori"])
            self.assertTrue(review_status(d)["revue_actuelle"])


if __name__ == "__main__":
    unittest.main()
