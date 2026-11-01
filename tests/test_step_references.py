"""Quantities in instructions follow ingredient lines across all serving paths."""
import json
import unittest

from test_profiles_v2 import workspace
from test_selection import basic
from test_binder import ing
from test_regressions import cli
from test_planning import schedule
from test_search import library, config
from checks import analyse
from core import DataError
from editing import adapt
from exports import export
from planning import scaled
from recipe_views import resolve_steps, check_scalable_steps
from search import search
from selection import select_and_save
from workflow import record_review


def templated():
    return basic() | {"etapes": ["Ajouter {{qte:carotte}} de carotte ; cuire 10 minutes à 180 °C."]}


class TestStepReferences(unittest.TestCase):
    def test_scale_resolves_markdown_and_reviewed_html_but_preserves_source_template(self):
        with workspace(recipes=[templated()]) as d:
            before = analyse(d).calcs["S01-R01"].poids_pp
            result = adapt(d, portions=4, apply=True)
            self.assertTrue(result["applique"])
            ctx = analyse(d)
            self.assertEqual(ctx.calcs["S01-R01"].poids_pp, before)
            self.assertIn("{{qte:carotte}}", ctx.recipes["S01-R01"]["etapes"][0])
            self.assertEqual(cli(d, "render").returncode, 0)
            text = (d / "out/classeur.md").read_text(encoding="utf-8")
            self.assertIn("Ajouter 200 g de carotte", text)
            self.assertNotIn("{{qte:", text)
            record_review(d, "fixture_review", "technical fixture only")
            export(d)
            html = (d / "out/exports/client/classeur.html").read_text(encoding="utf-8")
            self.assertIn("Ajouter 200 g de carotte", html)
            self.assertIn("10 minutes à 180 °C", html)

    def test_repeated_food_lines_use_stable_ids_even_after_reordering(self):
        recipe = basic() | {"ingredients": [ing("carotte", 20) | {"id_ligne": "sauce"},
                                           ing("carotte", 80) | {"id_ligne": "garniture"}],
                            "etapes": ["Sauce : {{qte:sauce}}. Garniture : {{qte:garniture}}."]}
        doubled = scaled(recipe, 2)
        doubled["ingredients"].reverse()
        self.assertEqual(resolve_steps(doubled), ["Sauce : 40 g. Garniture : 160 g."])
        self.assertEqual(recipe["ingredients"][0]["qte"], 20)

    def test_invalid_and_ambiguous_references_are_controlled_data_errors(self):
        for step in ("{{qte:absent}}", "{{qte:carotte}", "{{{{qte:carotte}}}}", "{{__import__('os')}}", "{{qte:1}}"):
            with self.subTest(step=step), workspace(recipes=[basic() | {"etapes": [step]}]) as d:
                result = cli(d, "check-all")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("etapes_reference", {i["code"] for i in json.loads(result.stdout)})
        with self.assertRaises(DataError):
            resolve_steps(basic() | {"ingredients": [ing("carotte", 20), ing("carotte", 80)], "etapes": ["{{qte:carotte}}"]})

    def test_duplicate_line_ids_and_collisions_with_food_ids_are_rejected(self):
        with self.assertRaises(DataError):
            resolve_steps(basic() | {"ingredients": [ing("carotte", 20) | {"id_ligne": "sauce"},
                                                     ing("carotte", 80) | {"id_ligne": "sauce"}]})
        with self.assertRaises(DataError):
            resolve_steps(basic() | {"ingredients": [ing("carotte", 20), ing("pomme_de_terre", 80) | {"id_ligne": "carotte"}],
                                     "etapes": ["{{qte:carotte}}"]})

    def test_literal_doses_still_block_scaling_even_alongside_references(self):
        recipe = templated()
        recipe["etapes"][0] += " Ajouter 100 ml d'eau."
        with self.assertRaises(DataError):
            check_scalable_steps(recipe, 2)

    def test_decimal_amounts_are_kept_and_identifiers_do_not_become_literal_doses(self):
        recipe = basic() | {"ingredients": [ing("carotte", .3) | {"id_ligne": "carotte_100g"}],
                            "etapes": ["Ajouter {{qte:carotte_100g}}."]}
        self.assertEqual(resolve_steps(scaled(recipe, 2)), ["Ajouter 0,6 g."])

    def test_calendar_renders_and_exports_the_scaled_service_quantity(self):
        with workspace(recipes=[templated()]) as d:
            data = schedule(d)
            data["services"][0]["plats"][0]["portions"] = 6
            schedule(d, **data)
            self.assertEqual(cli(d, "render").returncode, 0)
            text = (d / "out/classeur.md").read_text(encoding="utf-8")
            self.assertIn("Ajouter 300 g de carotte", text)
            record_review(d, "fixture_review", "technical fixture only")
            export(d)
            self.assertIn("Ajouter 300 g de carotte", (d / "out/exports/client/classeur.html").read_text(encoding="utf-8"))

    def test_library_search_and_selection_preserve_resolvable_steps(self):
        with workspace(recipes=[basic()]) as d:
            library(d, "linked", templated())
            path = d / "bibliotheque/linked.json"
            entry = json.loads(path.read_text(encoding="utf-8")); entry["portions"] = 1
            path.write_text(json.dumps(entry), encoding="utf-8")
            config(d, ["linked"])
            result = search(d)
            self.assertEqual(result["admissibles"], 1)
            selected, target = select_and_save(d / "out/recherche")
            self.assertIsNotNone(selected.chosen)
            self.assertIn("Ajouter 200 g de carotte", (target / "out/classeur.md").read_text(encoding="utf-8"))

    def test_replacement_resolves_at_the_destination_portions(self):
        with workspace(recipes=[basic()]) as d:
            adapt(d, recipe_id="S01-R01", replacement=templated(), source_portions=1, apply=True)
            self.assertEqual(cli(d, "render").returncode, 0)
            self.assertIn("Ajouter 200 g de carotte", (d / "out/classeur.md").read_text(encoding="utf-8"))

    def test_v1_rejects_references_and_keeps_ordinary_text_unchanged(self):
        with self.assertRaises(DataError):
            resolve_steps(templated(), version=1)
        plain = basic() | {"etapes": ["Cuire 10 minutes à 180 °C."]}
        self.assertEqual(resolve_steps(plain, version=1), plain["etapes"])
