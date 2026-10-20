"""Sélection réelle : contraintes, budget caisse, classement et sorties atomiques."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from test_binder import ROOT, codes, ing, recipe
from test_adaptation import adapted
from test_profiles_v2 import workspace
from test_regressions import cli, local_foods
from checks import analyse
from core import BinderError
from selection import select_proposals, save_selection


def proposal(directory, name, recipes=None, weeks=None):
    path = directory / "propositions" / name / "weeks"
    path.mkdir(parents=True)
    for week in weeks or [{"semaine": "S01", "recettes": recipes or [adapted()]}]:
        (path / (week["semaine"] + ".json")).write_text(json.dumps(week), encoding="utf-8")
    return path.parent


def basic(food="carotte", grams=100, active=10):
    r = recipe("S01-R01", [ing(food, grams)], plat_id="plat_test", ingredients_principaux=[food],
               execution={"techniques": ["assemblage"], "taches_simultanees": 1})
    if active is not None:
        r["temps_actif_min"] = active
    return r


def set_profile(directory, updates):
    from core import deep_merge
    path = directory / "profile.yaml"
    path.write_text(yaml.safe_dump(deep_merge(yaml.safe_load(path.read_text(encoding="utf-8")), updates)), encoding="utf-8")


def input_hashes(directory):
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob("*") if p.is_file() and "out" not in p.relative_to(directory).parts}


class TestSelection(unittest.TestCase):
    def test_raw_purchase_price_and_stock_are_preserved_in_selected_snapshot(self):
        with workspace({"selection": {"priorites": ["budget"]}}) as d:
            local_foods(d, {"sardine": {"prix_eur": "99", "conditionnements": "1000"},
                            "carotte": {"prix_eur": "10"}}, prices=True)
            fish = basic("sardine", 270)
            fish["ingredients"][0]["achat"] = {
                "qte": 550, "unite": "g", "forme": "entier", "conditionnements": [300], "prix_eur": 10}
            proposal(d, "poisson", [fish])
            proposal(d, "carottes", [basic("carotte", 400)])
            self.assertEqual(select_proposals(d).report["selectionne"], "carottes")
            (d / "pantry.yaml").write_text(yaml.safe_dump({"stock": [
                {"id": "sardine", "quantite": 135, "unite": "g"}]}), encoding="utf-8")
            result = select_proposals(d)
            self.assertEqual(result.report["selectionne"], "poisson")
            row = next(r for r in result.report["propositions"] if r["id"] == "poisson")
            self.assertEqual(row["mesures"]["budget"], 3)
            target = save_selection(result, d)
            ctx = analyse(target, complete=True)
            self.assertFalse(codes(ctx))
            self.assertEqual(ctx.shops[0].montant_caisse, row["mesures"]["budget"])
            self.assertEqual(ctx.shops[0].lines[0].achat, 300)

    def test_multiweek_ranking_uses_package_rollover_and_weekly_limits(self):
        with workspace({"projet": {"semaines": 2}, "budget": {"plafond_eur_semaine": 1},
                        "selection": {"priorites": ["budget"]}}) as d:
            local_foods(d, {"pomme_de_terre": {"report_ok": "1", "conditionnements": "1000"}}, prices=True)
            proposal(d, "report", weeks=[{"semaine": wid, "recettes": [
                basic("pomme_de_terre", 400) | {"id": wid + "-R01"}]} for wid in ("S01", "S02")])
            result = select_proposals(d)
            self.assertEqual(result.report["selectionne"], "report")
            self.assertEqual(result.report["propositions"][0]["mesures"]["budget"], 1)
            self.assertEqual([s.montant_caisse for s in result.chosen.shops], [1, 0])
            self.assertEqual(cli(save_selection(result, d), "check-all").returncode, 0)

    def test_unknown_stock_rejects_required_budget_and_counts_soft_uncertainty(self):
        with workspace({"budget": {"plafond_eur_semaine": 20}}) as d:
            local_foods(d, prices=True)
            proposal(d, "stock_inconnu", [basic()])
            (d / "pantry.yaml").write_text(yaml.safe_dump({"stock": [
                {"id": "carotte", "quantite": None, "unite": "g"}]}), encoding="utf-8")
            result = select_proposals(d)
            self.assertIsNone(result.chosen)
            self.assertIsNone(result.report["propositions"][0]["mesures"]["budget"])
            set_profile(d, {"exigences": {"budget_depasse": "preference"}})
            result = select_proposals(d)
            self.assertIsNotNone(result.chosen)
            self.assertEqual(result.report["propositions"][0]["preferences_non_verifiables"], 1)
            self.assertIsNone(result.report["propositions"][0]["mesures"]["budget"])

    def test_checkout_with_packs_then_stock_decides_instead_of_consumed_cost(self):
        with workspace({"selection": {"priorites": ["budget"]}}) as d:
            local_foods(d, {"carotte": {"prix_eur": "2"}}, prices=True)
            proposal(d, "pommes_de_terre", [basic("pomme_de_terre", 100)])  # Consommé 0,10 ; caisse 1.
            proposal(d, "carottes", [basic("carotte", 400)])                # Consommé et caisse 0,80.
            result = select_proposals(d)
            self.assertEqual(result.report["selectionne"], "carottes")
            self.assertIn("Montant caisse total inférieur", result.report["explication"])
            (d / "pantry.yaml").write_text(yaml.safe_dump({"stock": [{"id": "pomme_de_terre", "quantite": 100, "unite": "g"}]}), encoding="utf-8")
            result = select_proposals(d)
            self.assertEqual(result.report["selectionne"], "pommes_de_terre")
            self.assertEqual(result.report["propositions"][1]["mesures"]["budget"], 0)

    def test_weekly_budget_cap_is_not_replaced_by_a_binder_average(self):
        with workspace({"projet": {"semaines": 2}, "budget": {"plafond_eur_semaine": 1}}) as d:
            local_foods(d, prices=True)
            weeks = [{"semaine": wid, "recettes": [basic(grams=grams) | {"id": wid + "-R01"}]} for wid, grams in (("S01", 1200), ("S02", 100))]
            proposal(d, "depassement", weeks=weeks)
            result = select_proposals(d)
            self.assertIsNone(result.chosen)
            self.assertIn("budget_depasse", " ".join(result.report["propositions"][0]["motifs_rejet"]))

    def test_unknown_imperative_budget_rejects_instead_of_assuming_free(self):
        with workspace({"budget": {"plafond_eur_semaine": 20}}) as d:
            proposal(d, "inconnue")
            result = cli(d, "select")
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(result.stdout)
            self.assertIsNone(report["selectionne"])
            self.assertIsNone(report["propositions"][0]["mesures"]["budget"])
            self.assertIn("non vérifiable", " ".join(report["propositions"][0]["motifs_rejet"]))

    def test_unknown_preference_is_counted_and_known_failure_not_double_counted(self):
        with workspace({"budget": {"plafond_eur_semaine": 0}, "exigences": {"budget_depasse": "preference"}}) as d:
            local_foods(d, {"carotte": {"prix_eur": "1"}})
            r = basic() | {"ingredients": [ing("carotte", 100), ing("oeuf", 1, "piece")]}
            proposal(d, "partielle", [r])
            result = select_proposals(d)
            row = result.report["propositions"][0]
            self.assertTrue(row["admissible"])
            self.assertEqual((row["preferences_non_satisfaites"], row["preferences_non_verifiables"]), (1, 0))
            set_profile(d, {"budget": {"plafond_eur_semaine": 20}})
            row = select_proposals(d).report["propositions"][0]
            self.assertEqual((row["preferences_non_satisfaites"], row["preferences_non_verifiables"]), (0, 1))

    def test_fewer_preference_gaps_precede_optimization_priorities(self):
        with workspace({"repas": {"duree_active_max_min": 10}, "exigences": {"duree_active": "preference"},
                        "selection": {"priorites": ["budget"]}}) as d:
            local_foods(d, prices=True)
            proposal(d, "economique", [basic(grams=100, active=20)])
            proposal(d, "rapide", [basic(grams=2000, active=5)])
            result = select_proposals(d)
            self.assertEqual(result.report["selectionne"], "rapide")
            self.assertIn("moins d'écarts", result.report["explication"])

    def test_priority_order_changes_the_choice_and_explanation(self):
        with workspace({"selection": {"priorites": ["budget", "temps_actif"]}}) as d:
            local_foods(d, prices=True)
            proposal(d, "economique", [basic(grams=100, active=20)])
            proposal(d, "rapide", [basic(grams=2000, active=5)])
            self.assertEqual(select_proposals(d).report["selectionne"], "economique")
            set_profile(d, {"selection": {"priorites": ["temps_actif", "budget"]}})
            result = select_proposals(d)
            self.assertEqual(result.report["selectionne"], "rapide")
            self.assertIn("Temps actif total inférieur", result.report["explication"])

    def test_unknown_measurement_sorts_after_known_even_with_lower_slug(self):
        for criterion in ("temps_actif", "difficulte", "variete", "budget"):
            with self.subTest(criterion=criterion), workspace({"selection": {"priorites": [criterion]}}) as d:
                unknown = basic("pomme_de_terre", active=None)
                unknown.pop("execution"); unknown.pop("plat_id")
                local_foods(d, {"carotte": {"prix_eur": "1"}})
                proposal(d, "a_inconnue", [unknown])
                proposal(d, "z_connue", [basic()])
                result = select_proposals(d)
                self.assertEqual(result.report["selectionne"], "z_connue")
                self.assertIn("contre inconnu", result.report["explication"])

    def test_variety_is_maximized_and_difficulty_uses_the_worst_recipe(self):
        with workspace({"projet": {"recettes_par_semaine": 2}, "selection": {"priorites": ["variete"]}}) as d:
            proposal(d, "repetee", [adapted(), adapted("S01-R02")])
            proposal(d, "variee", [adapted(), adapted("S01-R02", plat_id="autre", execution={"techniques": ["emulsion_chaude"], "taches_simultanees": 1})])
            self.assertEqual(select_proposals(d).report["selectionne"], "variee")
            set_profile(d, {"selection": {"priorites": ["difficulte", "variete"]}})
            result = select_proposals(d)
            self.assertEqual(result.report["selectionne"], "repetee")
            self.assertIn("Niveau maximal de difficulté inférieur", result.report["explication"])

    def test_ties_are_deterministic_and_explained(self):
        with workspace() as d:
            proposal(d, "z_identique")
            proposal(d, "a_identique")
            report = select_proposals(d).report
            self.assertEqual(report["classement"], ["a_identique", "z_identique"])
            self.assertIn("départage par identifiant", report["explication"])

    def test_bad_candidate_does_not_hide_a_valid_one(self):
        with workspace() as d:
            bad = proposal(d, "invalide")
            (bad / "weeks/S01.json").write_text("{erreur}", encoding="utf-8")
            proposal(d, "valide")
            result = cli(d, "select")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["selectionne"], "valide")
            self.assertFalse(report["propositions"][0]["admissible"])
            self.assertNotIn("Traceback", result.stderr)

    def test_incomplete_binder_never_reports_partial_measures_as_complete(self):
        with workspace({"projet": {"recettes_par_semaine": 2}}) as d:
            proposal(d, "incomplete", [adapted()])
            result = select_proposals(d)
            self.assertIsNone(result.chosen)
            self.assertTrue(all(x is None for x in result.report["propositions"][0]["mesures"].values()))

    def test_candidate_cannot_change_the_common_profile(self):
        with workspace() as d:
            path = proposal(d, "modifiee")
            (path / "profile.yaml").write_text("version: 2\n", encoding="utf-8")
            result = select_proposals(d)
            self.assertIsNone(result.chosen)
            self.assertIn("proposition_configuration", result.report["propositions"][0]["motifs_rejet"][0])

    def test_nonfinite_or_invalid_recipe_remains_a_rejection_with_soft_rules(self):
        with workspace({"exigences": {"difficulte": "preference", "budget_depasse": "preference"}}) as d:
            proposal(d, "invalide", [basic() | {"ingredients": [ing("carotte", -100)]}])
            row = select_proposals(d).report["propositions"][0]
            self.assertFalse(row["admissible"])
            self.assertTrue(all(value is None for value in row["mesures"].values()))

    def test_overflowing_total_rejects_candidate_without_breaking_json_report(self):
        with workspace({"projet": {"recettes_par_semaine": 2}}) as d:
            proposal(d, "depassement", [adapted(rid, temps_actif_min=1e308, temps_total_min=1e308)
                                        for rid in ("S01-R01", "S01-R02")])
            result = cli(d, "select")
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(result.stdout)
            self.assertIsNone(report["selectionne"])
            self.assertIn("selection_mesure", report["propositions"][0]["motifs_rejet"][0])
            self.assertNotIn("Traceback", result.stderr)

    def test_v1_selection_and_missing_proposals_return_documented_codes(self):
        for profile, expected in (({"version": 1}, 1), ({"version": 2}, 2)):
            with self.subTest(profile=profile), workspace(profile) as d:
                result = cli(d, "select")
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertIsInstance(json.loads(result.stdout), list)

    def test_catalogue_command_exposes_known_ids_without_a_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            result = cli(Path(temp), "list-options")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["familles"]["soja"]["parents"], ["legumineuses"])
            self.assertIn("cuisson_poele", payload["techniques"])
            self.assertIn("budget", payload["criteres_selection"])


class TestSelectionOutput(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git"), "git requis pour vérifier les exclusions de publication")
    def test_private_proposals_are_ignored_at_every_depth_but_public_examples_are_visible(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            shutil.copyfile(ROOT / ".gitignore", d / ".gitignore")
            subprocess.run(["git", "init", "--quiet", str(d)], check=True, capture_output=True)
            paths = ["propositions/economique/notes.md", "mon-classeur/propositions/rapide/notes.md",
                     "mon-classeur/out/selection/rapport.json", "mon-classeur/profile.yaml"]
            public = "examples/adaptation/propositions/rapide/weeks/S01.json"
            result = subprocess.run(["git", "check-ignore", "--stdin"], cwd=d,
                                    input="\n".join(paths + [public]) + "\n", capture_output=True,
                                    text=True, encoding="utf-8", check=True)
            self.assertEqual(result.stdout.splitlines(), paths)

    def test_documented_example_changes_winner_with_priority_and_rejects_soy(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp) / "adaptation"
            shutil.copytree(ROOT / "examples/adaptation", d, ignore=shutil.ignore_patterns("out"))
            result = cli(d, "select")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["selectionne"], "economique")
            rejected = next(row for row in report["propositions"] if row["id"] == "avec_soja")
            self.assertFalse(rejected["admissible"])
            self.assertIn("famille_exclue", " ".join(rejected["motifs_rejet"]))
            self.assertEqual(cli(d / "out/selection", "check-all").returncode, 0)
            set_profile(d, {"selection": {"priorites": ["temps_actif", "budget"]}})
            result = cli(d, "select")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["selectionne"], "rapide")
            self.assertEqual(cli(d / "out/selection", "audit").returncode, 0)

    def test_selected_snapshot_is_autonomous_and_inputs_are_unchanged(self):
        with workspace({"prereglages": ["rapide"], "selection": {"priorites": ["budget"]}}) as d:
            local_foods(d, prices=True)
            proposal(d, "seule", [basic()])
            before = input_hashes(d)
            result = select_proposals(d)
            target = save_selection(result, d)
            self.assertEqual(input_hashes(d), before)
            self.assertFalse(codes(analyse(target, complete=True)))
            self.assertEqual(cli(target, "check-all").returncode, 0)
            self.assertIn("Difficulté estimée", (target / "out/classeur.md").read_text(encoding="utf-8"))
            self.assertEqual(json.loads((target / "rapport.json").read_text(encoding="utf-8")), result.report)
            # La copie reste utilisable après retrait des propositions source.
            shutil.rmtree(d / "propositions")
            self.assertEqual(cli(target, "render").returncode, 0)

    def test_no_winner_clears_old_generated_binder_but_keeps_report(self):
        with workspace() as d:
            proposal(d, "seule", [basic()])
            target = save_selection(select_proposals(d), d)
            self.assertTrue((target / "weeks/S01.json").exists())
            set_profile(d, {"aliments": {"familles_exclues": ["oeufs"]}})
            # Le changement concerne bien le plat proposé, pas les semaines racine.
            path = d / "propositions/seule/weeks/S01.json"
            path.write_text(json.dumps({"semaine": "S01", "recettes": [adapted()]}), encoding="utf-8")
            result = select_proposals(d)
            self.assertIsNone(result.chosen)
            save_selection(result, d)
            self.assertFalse((target / "weeks").exists())
            self.assertFalse((target / "out/classeur.md").exists())
            self.assertTrue((target / "rapport.md").exists())

    def test_unrecognized_output_directory_is_never_overwritten(self):
        with workspace() as d:
            proposal(d, "seule")
            target = d / "out/selection"
            target.mkdir(parents=True)
            (target / "mes_notes.md").write_text("À garder", encoding="utf-8")
            with self.assertRaises(BinderError):
                save_selection(select_proposals(d), d)
            self.assertEqual((target / "mes_notes.md").read_text(encoding="utf-8"), "À garder")

    def test_failed_replacement_restores_previous_generated_output(self):
        with workspace() as d:
            proposal(d, "z_premiere")
            target = save_selection(select_proposals(d), d)
            before = (target / "rapport.json").read_bytes()
            proposal(d, "a_nouvelle")
            selected = select_proposals(d)
            self.assertEqual(selected.report["selectionne"], "a_nouvelle")
            real_replace, calls = os.replace, 0

            def fail_once(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("échec de remplacement simulé")
                return real_replace(source, destination)

            with patch("selection.os.replace", side_effect=fail_once), self.assertRaises(OSError):
                save_selection(selected, d)
            self.assertEqual((target / "rapport.json").read_bytes(), before)
            self.assertEqual(cli(target, "check-all").returncode, 0)
            self.assertEqual(sorted(p.name for p in (d / "out").iterdir()), ["selection"])


if __name__ == "__main__":
    unittest.main()
