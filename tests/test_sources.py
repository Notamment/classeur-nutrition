"""Données sourcées : valeurs bornées, imports stricts et calculs inconnus."""
from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from test_binder import ROOT, codes, ing, recipe
from test_profiles_v2 import workspace
from test_regressions import cli
from checks import analyse
from core import DataError
from sources import load_sources, parse_measure, nutrient_report
from build_foods import main as import_ciqual


def source(nutrients, state="cru"):
    return {"source": "https://example.invalid/fixture", "edition": "test-fictif",
            "date": "2026-01-02", "licence": "fixture de test", "etat_ref": state,
            "nutriments": nutrients}


def registry(directory, entries):
    (directory / "provenance.yaml").write_text(yaml.safe_dump({"version": 1, "aliments": entries}), encoding="utf-8")


class TestProvenance(unittest.TestCase):
    def test_official_dataset_is_opt_in_and_uncovered_foods_become_unknown(self):
        with workspace(recipes=[recipe("S01-R01", [ing("carotte", 100)])]) as d:
            before = analyse(d).foods["oeuf"].prot
            self.assertIsNotNone(before)
            result = cli(d, "use-data", "--edition", "ciqual2025")
            self.assertEqual(result.returncode, 0, result.stderr)
            ctx = analyse(d)
            self.assertIsNone(ctx.foods["oeuf"].prot)
            self.assertIsNotNone(ctx.foods["carotte"].prot)
            self.assertEqual(len(load_sources(d)), 16)
            data = load_sources(d)["carotte"]
            self.assertEqual(data["code"], "20009")
            self.assertEqual(data["nom_source"], "Carotte, crue")
            self.assertEqual(cli(d, "use-data", "--edition", "ciqual2025").returncode, 2)

    def test_traces_missing_bounds_and_zero_are_different(self):
        self.assertEqual(parse_measure("0", "g")["statut"], "exact")
        self.assertEqual(parse_measure("traces", "g"), {"statut": "traces", "unite": "g", "minimum": 0, "maximum": None})
        self.assertEqual(parse_measure("< 0,5", "g"), {"statut": "borne", "unite": "g", "minimum": 0, "maximum": .5})
        self.assertEqual(parse_measure("-", "g")["statut"], "absent")
        for value in ("NaN", "inf", "-1", "texte", "< 0"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_measure(value, "g")

    def test_unknown_protein_cannot_validate_target_but_other_metrics_work(self):
        with workspace({"nutrition": {"mode": "cibles"}, "repas": {"proteines_g_par_portion": [.1, 100]}},
                       recipes=[recipe("S01-R01", [ing("carotte", 200)])]) as d:
            registry(d, {"carotte": source({"proteines_g": parse_measure("< 1", "g"),
                                          "energie_kcal": parse_measure("40", "kcal"),
                                          "fibres_g": parse_measure("2", "g")})})
            ctx = analyse(d, complete=True)
            self.assertIn("proteines", codes(ctx))
            self.assertIsNone(ctx.calcs["S01-R01"].prot_pp)
            self.assertEqual(ctx.calcs["S01-R01"].kcal_pp, 40)
            report = nutrient_report(ctx)["recettes"]["S01-R01"]
            self.assertEqual(report["proteines_g"]["statut"], "borne")
            self.assertEqual(report["proteines_g"]["maximum_par_portion"], 1)
            self.assertEqual(report["fibres_g"]["minimum_par_portion"], 2)

    def test_incompatible_state_and_reversed_bounds_are_rejected(self):
        with workspace() as d:
            registry(d, {"carotte": source({}, state="cuit")})
            with self.assertRaises(DataError):
                analyse(d)
            measure = parse_measure("< 2", "g") | {"minimum": 3}
            registry(d, {"carotte": source({"proteines_g": measure})})
            with self.assertRaises(DataError):
                load_sources(d)

    def test_unsupported_nutrient_data_is_unknown_not_zero(self):
        with workspace(recipes=[recipe("S01-R01", [ing("carotte", 100), ing("pomme_de_terre", 100)])]) as d:
            registry(d, {"carotte": source({"fibres_g": parse_measure("2", "g")})})
            fibre = nutrient_report(analyse(d))["recettes"]["S01-R01"]["fibres_g"]
            self.assertIsNone(fibre["minimum_par_portion"])
            self.assertEqual(fibre["aliments_non_renseignes"], ["pomme_de_terre"])


class TestCiqualImport(unittest.TestCase):
    def fixture(self, directory, value="< 1", duplicate=False):
        foods = directory / "foods.local.csv"
        shutil.copyfile(ROOT / "skills/meal-binder/data/foods.csv", foods)
        mapping = directory / "map.csv"
        mapping.write_text("id,ciqual_code\ncarotte,123\n", encoding="utf-8")
        table = directory / "table.csv"
        row = f"123;{value};40\n"
        table.write_text("alim_code;Protéines Jones;Energie kcal\n" + row + (row if duplicate else ""), encoding="utf-8")
        return ["--ciqual", str(table), "--map", str(mapping), "--foods", str(foods),
                "--source", "https://example.invalid/fixture", "--source-version", "test-fictif",
                "--license", "fixture", "--retrieved-on", "2026-01-02"]

    def test_dry_run_does_not_write_and_import_retains_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp); args = self.fixture(d)
            before = (d / "foods.local.csv").read_bytes()
            self.assertEqual(import_ciqual(args + ["--dry-run"]), 0)
            self.assertEqual((d / "foods.local.csv").read_bytes(), before)
            self.assertFalse((d / "provenance.yaml").exists())
            self.assertEqual(import_ciqual(args), 0)
            with (d / "foods.local.csv").open(encoding="utf-8") as stream:
                row = next(r for r in csv.DictReader(stream) if r["id"] == "carotte")
            self.assertEqual(row["prot_g_100g"], "")
            self.assertEqual(load_sources(d)["carotte"]["nutriments"]["proteines_g"]["statut"], "borne")

    def test_duplicates_and_nonfinite_values_leave_outputs_unchanged(self):
        for options in ({"duplicate": True}, {"value": "NaN"}, {"value": "-1"}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temp:
                d = Path(temp); args = self.fixture(d, **options)
                before = (d / "foods.local.csv").read_bytes()
                self.assertEqual(import_ciqual(args), 1)
                self.assertEqual((d / "foods.local.csv").read_bytes(), before)
                self.assertFalse((d / "provenance.yaml").exists())
