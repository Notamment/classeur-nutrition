"""Planning explicite : portions par service, stocks datés, matériels et budget."""
import copy
import unittest

import yaml

from test_profiles_v2 import workspace
from test_regressions import local_foods
from test_selection import basic
from core import BinderError, DataError
from checks import analyse
from planning import report


def schedule(d, **changes):
    data = {"version": 1, "stock_mode": "lots_exclusifs", "equipements": {"plaque": 1}, "lots": [],
            "preparations": [{"id": "prep", "debut": "2026-01-02T10:00+01:00", "duree_min": 60,
                "equipements": ["plaque"], "utilisable_jusqua": "2026-01-02T13:00+01:00"}],
            "services": [{"id": "midi", "debut": "2026-01-02T12:00+01:00",
                "plats": [{"recette": "S01-R01", "portions": 4, "preparation": "prep"}]}]} | changes
    (d / "schedule.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return data


def lot(identifier="lot_test", **changes):
    return {"id": identifier, "food": "carotte", "quantite": 100, "unite": "g", "etat": "cru",
            "disponible_le": "2026-01-01", "limite": "2026-01-03", "type_limite": "DLC", "source": "fixture"} | changes


class TestPlanning(unittest.TestCase):
    def test_per_service_portions_do_not_modify_legacy_profile(self):
        with workspace(recipes=[basic()]) as d:
            local_foods(d, prices=True)
            before = (d / "profile.yaml").read_bytes()
            schedule(d, lots=[lot()])
            result = report(d)
            self.assertTrue(result["admissible"], result["ecarts"])
            job = result["services"][0]
            self.assertEqual(job["portions"], 4)
            self.assertEqual(job["achats"][0]["besoin"], 200)
            self.assertEqual(job["lots_mobilises"][0]["quantite"], 100)
            self.assertEqual((d / "profile.yaml").read_bytes(), before)

    def test_lots_use_earliest_limit_and_never_consume_expired_or_future_stock(self):
        with workspace(recipes=[basic()]) as d:
            schedule(d, lots=[lot("plus_tard", limite="2026-01-10"), lot("prioritaire"),
                              lot("perime", limite="2026-01-01"), lot("futur", disponible_le="2026-01-03")])
            result = report(d)
            self.assertEqual([v["lot"] for v in result["services"][0]["lots_mobilises"]], ["prioritaire", "plus_tard"])
            remaining = {v["id"]: v["reste"] for v in result["lots_restants"]}
            self.assertEqual(remaining["perime"], 100)
            self.assertEqual(remaining["futur"], 100)

    def test_unknown_quantity_and_imperative_budget_remain_unverifiable(self):
        with workspace({"budget": {"plafond_eur_semaine": 100}}, recipes=[basic()]) as d:
            local_foods(d, prices=True)
            schedule(d, lots=[lot(quantite=None)])
            result = report(d)
            self.assertFalse(result["admissible"])
            self.assertTrue(result["budget_imperatif_inverifiable"])
            self.assertEqual(result["services"][0]["lots_mobilises"], [])

    def test_equipment_conflicts_and_conservation_limits_are_imperative(self):
        with workspace(recipes=[basic()]) as d:
            data = schedule(d)
            second = copy.deepcopy(data["preparations"][0]); second["id"] = "autre"
            data["preparations"].append(second)
            data["preparations"][0]["utilisable_jusqua"] = "2026-01-02T11:30+01:00"
            schedule(d, **data)
            result = report(d)
            codes = {i["code"] for i in result["ecarts"]}
            self.assertIn("planning_capacite", codes)
            self.assertIn("planning_conservation", codes)
            self.assertFalse(result["admissible"])

    def test_weekly_budget_is_aggregated_across_services(self):
        with workspace({"budget": {"plafond_eur_semaine": 0.3}}, recipes=[basic()]) as d:
            local_foods(d, prices=True)
            data = schedule(d)
            data["services"].append({**data["services"][0], "id": "soir"})
            schedule(d, **data)
            result = report(d)
            self.assertIn("budget_depasse", {i["code"] for i in result["ecarts"]})
            self.assertFalse(result["admissible"])

    def test_components_are_explicit_and_use_same_food_exclusions(self):
        with workspace({"aliments": {"exclus": ["oeuf"]}}, recipes=[basic()]) as d:
            from test_binder import filler
            data = schedule(d)
            data["composants"] = {"garniture": {"portions": 2, "recette": filler("S01-R02")}}
            data["services"][0]["plats"] = [{"composant": "garniture", "portions": 6, "preparation": "prep"}]
            schedule(d, **data)
            result = report(d)
            self.assertFalse(result["admissible"])
            self.assertIn("aliment_exclu", {i["code"] for i in result["ecarts"]})

    def test_undated_stock_and_ambiguous_times_are_refused(self):
        with workspace(recipes=[basic()]) as d:
            schedule(d)
            (d / "pantry.yaml").write_text("stock:\n- id: carotte\n  quantite: 10\n  unite: g\n", encoding="utf-8")
            with self.assertRaises(BinderError):
                report(d)
            (d / "pantry.yaml").unlink()
            data = schedule(d)
            data["services"][0]["debut"] = "2026-01-02T12:00"
            schedule(d, **data)
            with self.assertRaises(BinderError):
                report(d)

    def test_schedule_errors_are_shared_with_render_review_and_analysis(self):
        from test_regressions import cli
        from workflow import record_review
        with workspace(recipes=[basic()]) as d:
            data = schedule(d)
            data["preparations"][0]["utilisable_jusqua"] = "2026-01-02T11:30+01:00"
            schedule(d, **data)
            self.assertIn("planning_conservation", {i.code for i in analyse(d).issues})
            self.assertEqual(cli(d, "render").returncode, 1)
            self.assertIn("Planning opérationnel", (d / "out/classeur.md").read_text(encoding="utf-8"))
            with self.assertRaises(BinderError):
                record_review(d, "relecteur_test", "Ne peut pas valider un planning invalide")
