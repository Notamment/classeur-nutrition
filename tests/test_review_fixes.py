"""Integration regressions from the review of 30e852a; all data is fictional."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_profiles_v2 import workspace
from test_selection import basic
from test_sources import source, registry, parse_measure
from test_planning import schedule
from test_regressions import cli, local_foods, score_run
from checks import analyse, required_budget_unverified, preference_counts
from core import BinderError, DataError
from workflow import create_workspace, locked, record_review
from exports import export
from editing import adapt
from planning import scaled
from sources import nutrient_report
from manifest import hashes, input_files
import workflow


def serve_component(d, recipe, portions=6):
    data = schedule(d, composants={"garniture": {"portions": 2, "recette": recipe}})
    data["services"][0]["plats"] = [{"composant": "garniture", "portions": portions, "preparation": "prep"}]
    schedule(d, **data)
    return data


class TestConsistentClone(unittest.TestCase):
    def test_clone_refuses_a_locked_source_before_copying(self):
        with workspace() as source_dir, tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "clone"
            with locked(source_dir):
                result = cli(target, "clone", "--source", str(source_dir))
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("occupé", result.stdout)
                self.assertFalse(target.exists())
            create_workspace(target, source=source_dir)

    def test_cooperating_scale_is_refused_while_source_is_copied(self):
        with workspace(recipes=[basic()]) as source_dir, tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "clone"
            original = workflow.shutil.copyfile
            attempted = []
            def copying(src, dst, *args, **kwargs):
                result = original(src, dst, *args, **kwargs)
                if Path(src).resolve() == (source_dir / "profile.yaml").resolve():
                    attempted.append(cli(source_dir, "scale", "--portions", "4", "--apply"))
                return result
            with patch("workflow.shutil.copyfile", side_effect=copying):
                create_workspace(target, source=source_dir)
            self.assertEqual(attempted[0].returncode, 2)
            self.assertEqual(analyse(target).calcs["S01-R01"].poids_pp, 50)
            self.assertFalse((source_dir / ".dossier.lock").exists())

    def test_external_source_change_prevents_publication(self):
        with workspace(recipes=[basic()]) as source_dir, tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "clone"
            original = workflow.shutil.copyfile
            def copying(src, dst, *args, **kwargs):
                result = original(src, dst, *args, **kwargs)
                if Path(src).resolve() == (source_dir / "profile.yaml").resolve():
                    with (source_dir / "profile.yaml").open("a", encoding="utf-8") as stream:
                        stream.write("\n# external change\n")
                return result
            with patch("workflow.shutil.copyfile", side_effect=copying):
                with self.assertRaisesRegex(BinderError, "source modifiée"):
                    create_workspace(target, source=source_dir)
            self.assertFalse(target.exists())
            self.assertFalse(list(Path(temp).glob(".dossier-*")))
            self.assertFalse((source_dir / ".dossier.lock").exists())


class TestServedNutrients(unittest.TestCase):
    def test_components_and_repeated_sources_use_service_ids_and_their_own_portions(self):
        with workspace({"nutrition": {"mode": "information"}}, recipes=[basic()]) as d:
            data = serve_component(d, basic("pomme_de_terre", 200), portions=6)
            data["services"][0]["plats"].append({"recette": "S01-R01", "portions": 4, "preparation": "prep"})
            schedule(d, **data)
            registry(d, {"carotte": source({"proteines_g": parse_measure("1", "g")}),
                         "pomme_de_terre": source({"proteines_g": parse_measure("2", "g")})})
            result = cli(d, "nutrients")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["version"], 2)
            self.assertEqual(report["portions"], {"midi/1": 6, "midi/2": 4})
            self.assertEqual(set(report["recettes"]), {"midi/1", "midi/2"})
            self.assertEqual(report["recettes"]["midi/1"]["proteines_g"]["minimum_par_portion"], 2)
            self.assertEqual(report["recettes"]["midi/2"]["proteines_g"]["minimum_par_portion"], .5)

    def test_unknown_component_nutrients_never_reuse_source_values(self):
        with workspace(recipes=[basic()]) as d:
            serve_component(d, basic("pomme_de_terre", 200))
            registry(d, {"carotte": source({"proteines_g": parse_measure("1", "g")})})
            result = nutrient_report(analyse(d))["recettes"]["midi/1"]["proteines_g"]
            self.assertIsNone(result["minimum_par_portion"])
            self.assertEqual(result["aliments_non_renseignes"], ["pomme_de_terre"])


class TestOperationalBudget(unittest.TestCase):
    def test_service_within_cap_is_not_rejected_by_more_expensive_source(self):
        with workspace({"budget": {"plafond_eur_semaine": .75}}, recipes=[basic()]) as d:
            local_foods(d, {"carotte": {"prix_eur": "10"}}, prices=True)
            serve_component(d, basic(), portions=1)
            ctx = analyse(d, complete=True)
            self.assertEqual(ctx.shops[0].montant_caisse, 1)
            self.assertEqual(ctx.schedule["semaines_achat"]["2026-W01"]["caisse_connue"], .5)
            self.assertTrue(ctx.schedule["admissible"], ctx.issues)
            self.assertFalse(required_budget_unverified(ctx))
            self.assertTrue(score_run(d)["conforme"])
            from test_selection import proposal
            from selection import select_proposals
            proposal(d, "fixture", [basic()])
            selected = select_proposals(d)
            self.assertIsNotNone(selected.chosen)
            self.assertEqual(selected.report["propositions"][0]["mesures"]["budget"], .5)
            self.assertEqual(cli(d, "render").returncode, 0)
            record_review(d, "fixture_review", "technical fixture only")
            export(d, audience="production")
            self.assertIn("Budget du calendrier", (d / "out/exports/production/classeur.html").read_text(encoding="utf-8"))

    def test_service_over_cap_is_rejected_even_when_source_is_cheap(self):
        with workspace({"budget": {"plafond_eur_semaine": .75}}, recipes=[basic(grams=10)]) as d:
            local_foods(d, {"carotte": {"prix_eur": "10"}}, prices=True)
            serve_component(d, basic(), portions=4)
            ctx = analyse(d, complete=True)
            self.assertFalse(ctx.schedule["admissible"])
            self.assertTrue(any(i.code == "budget_depasse" and i.where == "2026-W01" for i in ctx.issues))

    def test_unknown_source_price_does_not_block_known_service_budget(self):
        with workspace({"budget": {"plafond_eur_semaine": 100}}, recipes=[basic("pomme_de_terre")]) as d:
            local_foods(d, {"carotte": {"prix_eur": "10"}})
            serve_component(d, basic(), portions=1)
            ctx = analyse(d, complete=True)
            self.assertFalse(ctx.shops[0].budget_verifiable)
            self.assertTrue(ctx.schedule["admissible"], ctx.issues)
            self.assertFalse(required_budget_unverified(ctx))

    def test_unknown_service_price_stays_blocking_with_known_source_budget(self):
        with workspace({"budget": {"plafond_eur_semaine": 100}}, recipes=[basic()]) as d:
            local_foods(d, {"carotte": {"prix_eur": "10"}})
            serve_component(d, basic("pomme_de_terre"), portions=1)
            ctx = analyse(d, complete=True)
            self.assertTrue(required_budget_unverified(ctx))
            self.assertFalse(ctx.schedule["admissible"])

    def test_preference_counts_only_the_operational_budget(self):
        with workspace({"budget": {"plafond_eur_semaine": .1}, "exigences": {"budget_depasse": "preference"}}, recipes=[basic()]) as d:
            local_foods(d, {"carotte": {"prix_eur": "10"}}, prices=True)
            serve_component(d, basic(), portions=1)
            ctx = analyse(d, complete=True)
            self.assertEqual(preference_counts(ctx), (1, 0))
            self.assertTrue(ctx.schedule["admissible"])


class TestQuantifiedSteps(unittest.TestCase):
    def test_scaling_numeric_doses_fails_without_modifying_inputs(self):
        for dose in ("100 g", "100 grammes", "100 ml", "2 œufs", "2 c. à café", "½ litre"):
            with self.subTest(dose=dose), workspace(recipes=[basic() | {"etapes": ["Utiliser " + dose + "."]}]) as d:
                before = hashes(input_files(d), d)
                with self.assertRaises(DataError):
                    adapt(d, portions=4, apply=True)
                self.assertEqual(hashes(input_files(d), d), before)
                self.assertFalse((d / ".dossier.lock").exists())

    def test_schedule_and_search_scaler_refuse_the_same_stale_steps(self):
        from test_search import library, config
        from search import search
        with workspace(recipes=[basic()]) as d:
            recipe = basic() | {"etapes": ["Utiliser 100 g de carotte."]}
            serve_component(d, recipe, portions=4)
            self.assertEqual(cli(d, "schedule").returncode, 1)
            (d / "schedule.yaml").unlink()
            library(d, "quantified", recipe)
            path = d / "bibliotheque/quantified.json"
            entry = json.loads(path.read_text(encoding="utf-8")); entry["portions"] = 1
            path.write_text(json.dumps(entry), encoding="utf-8")
            config(d, ["quantified"])
            self.assertEqual(search(d)["admissibles"], 0)

    def test_same_portions_and_time_only_instructions_remain_usable(self):
        quantified = basic() | {"etapes": ["Utiliser 100 g de carotte."]}
        self.assertEqual(scaled(quantified, 1), quantified)
        timed = basic() | {"etapes": ["Cuire 10 minutes à 180 °C."]}
        self.assertEqual(scaled(timed, 2)["ingredients"][0]["qte"], 200)
