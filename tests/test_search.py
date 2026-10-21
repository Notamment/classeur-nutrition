"""Recherche bornée : contraintes non compensables, compromis et protection."""
import copy
import json
import unittest

import yaml

from test_profiles_v2 import workspace
from test_regressions import local_foods, cli
from test_selection import basic, proposal
from core import BinderError
from manifest import encode, hashes, input_files
from search import search
from selection import select_proposals


def library(d, name, recipe):
    folder = d / "bibliotheque"; folder.mkdir(exist_ok=True)
    (folder / (name + ".json")).write_text(encode({"version": 1, "nom": name, "portions": 2, "recette": recipe, "favori": False}), encoding="utf-8")


def config(d, names):
    (d / "search.yaml").write_text(yaml.safe_dump({"version": 1, "emplacements": [{"id": "S01-R01", "choix": names}]}), encoding="utf-8")


class TestSearch(unittest.TestCase):
    def test_reports_multiple_tradeoffs_and_does_not_change_inputs(self):
        with workspace(recipes=[basic()]) as d:
            local_foods(d, prices=True)
            library(d, "rapide", basic(grams=500, active=2))
            library(d, "econome", basic(grams=100, active=20))
            config(d, ["rapide", "econome"])
            initial = hashes(input_files(d), d)
            result = search(d)
            self.assertEqual(result["admissibles"], 2)
            self.assertEqual(len(result["frontiere"]), 2)
            self.assertFalse(result["tronquee"])
            self.assertEqual(initial, hashes(input_files(d), d))
            self.assertTrue((d / "out/recherche/rapport.json").is_file())
            # Les dossiers retenus passent par le sélecteur existant.
            self.assertIsNotNone(select_proposals(d / "out/recherche").chosen)

    def test_bounds_are_explicit_and_existing_output_is_protected(self):
        with workspace(recipes=[basic()]) as d:
            library(d, "un", basic()); library(d, "deux", basic())
            config(d, ["un", "deux"])
            result = search(d, max_candidates=1)
            self.assertEqual(result["evaluees"], 1)
            self.assertEqual(result["combinaisons_possibles"], 2)
            self.assertTrue(result["tronquee"])
            with self.assertRaises(BinderError):
                search(d)

    def test_exclusion_and_unknown_hard_budget_never_enter_frontier(self):
        for profile in ({"aliments": {"exclus": ["carotte"]}}, {"budget": {"plafond_eur_semaine": 20}}):
            with self.subTest(profile=profile), workspace(profile, recipes=[basic()]) as d:
                library(d, "test", basic()); config(d, ["test"])
                result = search(d)
                self.assertEqual(result["retenues"], [])
                self.assertTrue(result["essais"][0]["motifs_rejet"])

    def test_stock_and_packs_are_used_in_budget_measurements(self):
        with workspace(recipes=[basic()]) as d:
            local_foods(d, {"carotte": {"conditionnements": "500"}}, prices=True)
            (d / "pantry.yaml").write_text("stock:\n- id: carotte\n  quantite: 80\n  unite: g\n", encoding="utf-8")
            library(d, "test", basic()); config(d, ["test"])
            row = search(d)["essais"][0]
            self.assertAlmostEqual(row["mesures"]["budget"], .5)

    def test_locks_protect_search_and_standard_selection(self):
        with workspace(recipes=[basic()]) as d:
            library(d, "test", basic()); config(d, ["test"])
            self.assertEqual(cli(d, "lock-recipe", "--recipe", "S01-R01").returncode, 0)
            with self.assertRaises(BinderError):
                search(d)
            proposal(d, "modification", [basic(grams=200)])
            result = select_proposals(d)
            self.assertIsNone(result.chosen)
            self.assertEqual(result.report["propositions"][0]["ecarts"][0]["code"], "recette_verrouillee")
