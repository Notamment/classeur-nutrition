"""Adaptation v2 : métadonnées, contrôles stricts/préférentiels et catalogues."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from test_binder import codes, filler, ing, recipe
from test_profiles_v2 import workspace, plan
from test_regressions import cli, local_foods, score_run
from adaptation import recipe_metadata
from catalogs import DATA, load_catalogs
from checks import analyse, check_plan, check_profile, preference_counts
from core import DataError, load_foods
from profiles import resolve_profile
from render import audit_rows, render_classeur


def adapted(rid="S01-R01", **changes):
    return filler(rid) | {"plat_id": "omelette_pommes_de_terre", "ingredients_principaux": ["oeuf", "pomme_de_terre"],
                          "temps_actif_min": 15,
                          "execution": {"techniques": ["decoupe_simple", "cuisson_poele"], "taches_simultanees": 2}} | changes


def plan_for(recipes):
    result = plan()
    result["semaines"][0]["recettes"] = [
        {"id": r["id"], "plat": r["nom"], "categorie": "vegetarien", "legumineuses": False}
        | {key: r[key] for key in ("plat_id", "ingredients_principaux", "execution", "temps_actif_min", "temps_total_min") if key in r}
        for r in recipes]
    return result


class TestAdaptationData(unittest.TestCase):
    def test_v2_adaptation_defaults_are_neutral_for_legacy_recipes(self):
        with workspace() as d:
            ctx = analyse(d, complete=True)
            for key in ("difficulte_max", "duree_active_max_min"):
                self.assertIsNone(ctx.profile["repas"][key])
            for key in ("recettes_distinctes_min_par_semaine", "ingredient_principal_max_par_semaine",
                        "techniques_distinctes_min_par_semaine", "repetition_plat_max"):
                self.assertIsNone(ctx.profile["variete"][key])
            self.assertEqual(ctx.profile["selection"]["priorites"], [])
            self.assertEqual(ctx.profile["aliments"]["familles_exclues"], [])
            self.assertEqual(ctx.profile["aliments"]["familles_a_eviter"], [])
            self.assertFalse(codes(ctx))
            self.assertEqual(preference_counts(ctx), (0, 0))

    def test_invalid_profile_types_and_enums_are_not_coerced(self):
        cases = [("repas", "duree_active_max_min", True), ("repas", "duree_active_max_min", -1),
                 ("repas", "difficulte_max", "debutant"), ("variete", "repetition_plat_max", 1.5),
                 ("variete", "ingredient_principal_max_par_semaine", "2"),
                 ("aliments", "familles_exclues", "soja"), ("selection", "priorites", ["prix"])]
        for section, field, value in cases:
            with self.subTest(field=field), workspace({section: {field: value}}) as d:
                result = cli(d, "check-profile")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("schema_profil", {i["code"] for i in json.loads(result.stdout)})

    def test_invalid_recipe_metadata_is_hard_even_without_targets(self):
        cases = [{"plat_id": "Deux mots"}, {"ingredients_principaux": []},
                 {"ingredients_principaux": ["oeuf"] * 4}, {"execution": None},
                 {"execution": {"techniques": [], "taches_simultanees": 1}},
                 {"execution": {"techniques": ["assemblage"], "taches_simultanees": True}},
                 {"execution": {"techniques": ["assemblage"], "taches_simultanees": 0}}]
        for change in cases:
            with self.subTest(change=change), workspace(recipes=[adapted(**change)]) as d:
                self.assertIn("schema_recette", codes(analyse(d)))

    def test_unknown_techniques_and_duplicate_metadata_stay_hard(self):
        cases = [({"execution": {"techniques": ["inventee"], "taches_simultanees": 1}}, "technique_inconnue"),
                 ({"execution": {"techniques": ["assemblage", "assemblage"], "taches_simultanees": 1}}, "metadata_recette"),
                 ({"ingredients_principaux": ["oeuf", "oeuf"]}, "metadata_recette"),
                 ({"ingredients_principaux": ["brocoli"]}, "metadata_recette")]
        for change, code in cases:
            with self.subTest(change=change), workspace({"exigences": {"difficulte": "preference", "ingredient_recurrent": "preference"}},
                                                       recipes=[adapted(**change)]) as d:
                self.assertIn(code, codes(analyse(d)))

    def test_incoherent_profile_is_rejected_before_selection(self):
        foods, _ = load_foods()
        for change in ({"selection": {"priorites": ["budget", "budget"]}},
                       {"variete": {"recettes_distinctes_min_par_semaine": 6}}):
            p = resolve_profile({"version": 2} | change).profile
            self.assertIn("configuration_adaptation", {i.code for i in check_profile(p, foods)})

    def test_catalogues_reject_cycles_unknown_parents_and_invalid_levels(self):
        for defect in ("cycle", "parent", "niveau"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as temp:
                d = Path(temp)
                for name in ("families.yaml", "techniques.yaml"):
                    shutil.copyfile(DATA / name, d / name)
                path = d / ("techniques.yaml" if defect == "niveau" else "families.yaml")
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                if defect == "niveau":
                    data["techniques"]["assemblage"]["niveau"] = "inconnu"
                else:
                    data["familles"]["legumineuses"]["parents"] = ["soja" if defect == "cycle" else "inconnu"]
                path.write_text(yaml.safe_dump(data), encoding="utf-8")
                with self.assertRaises(DataError) as error:
                    load_catalogs(d)
                self.assertTrue(all(i.code == "schema_catalogue" for i in error.exception.issues))

    def test_unknown_family_in_profile_or_food_tag_is_explicit(self):
        with workspace({"aliments": {"familles_exclues": ["inconnue"]}}) as d:
            self.assertIn("famille_inconnue", codes(analyse(d)))
        with workspace() as d:
            local_foods(d, {"oeuf": {"tags": "famille:inconnue"}})
            self.assertIn("foods_famille", codes(analyse(d)))

    def test_v1_does_not_accept_v2_metadata_silently(self):
        with workspace({"version": 1}, weeks=[{"semaine": "S01", "cuisine": "France", "recettes": [adapted()]}]) as d:
            self.assertIn("schema_recette", codes(analyse(d)))


class TestDifficultyAndTime(unittest.TestCase):
    def test_difficulty_uses_most_demanding_technique_and_concurrency(self):
        catalog = load_catalogs()
        for techniques, concurrent, expected in ((["cuisson_poele"], 2, "facile"),
                                                 (["cuisson_poele"], 3, "intermediaire"),
                                                 (["assemblage"], 4, "avancee"),
                                                 (["assemblage", "panure"], 1, "intermediaire"),
                                                 (["emulsion_chaude"], 1, "avancee")):
            with self.subTest(techniques=techniques, concurrent=concurrent):
                meta, issues = recipe_metadata(adapted(execution={"techniques": techniques, "taches_simultanees": concurrent}), catalog)
                self.assertEqual(meta["difficulte"], expected)
                self.assertFalse(issues)
                self.assertIn(str(concurrent), meta["raisons"][-1])

    def test_difficulty_policy_is_shared_by_plan_cli_audit_and_evaluation(self):
        r = adapted(execution={"techniques": ["panure"], "taches_simultanees": 1})
        for policy in ("imperative", "preference"):
            with self.subTest(policy=policy), workspace({"repas": {"difficulte_max": "facile"},
                                                        "exigences": {"difficulte": policy}}, recipes=[r]) as d:
                ctx = analyse(d, complete=True)
                self.assertEqual("difficulte" in codes(ctx), policy == "imperative")
                pissues = [i for i in check_plan(plan_for([r]), ctx.profile) if i.code == "difficulte"]
                self.assertEqual(pissues[0].level, "erreur" if policy == "imperative" else "alerte")
                self.assertEqual(cli(d, "render").returncode, int(policy == "imperative"))
                row = next(r for r in audit_rows(ctx, ctx.shops) if r[0] == "Difficulté maximale")
                self.assertEqual(row[-1], "non conforme" if policy == "imperative" else "préférence non satisfaite")
                self.assertEqual(score_run(d)["conforme"], policy == "preference")
                self.assertIn("panure", (d / "out/classeur.md").read_text(encoding="utf-8").lower())

    def test_missing_metadata_is_not_an_easy_or_zero_time_recipe(self):
        for policy in ("imperative", "preference"):
            with self.subTest(policy=policy), workspace({"repas": {"difficulte_max": "facile", "duree_active_max_min": 20},
                                                        "exigences": {"difficulte": policy, "duree_active": policy}}) as d:
                ctx = analyse(d)
                self.assertEqual({"difficulte", "duree_active"} <= codes(ctx), policy == "imperative")
                if policy == "preference":
                    self.assertEqual(preference_counts(ctx), (0, 2))
                    for row in audit_rows(ctx, ctx.shops):
                        if row[0] in ("Difficulté maximale", "Temps actif maximal"):
                            self.assertEqual(row[-1], "non vérifié")

    def test_active_time_zero_and_boundary_are_respected(self):
        for minutes, cap, error in ((0, 0, False), (10, 10, False), (10, 0, True)):
            with self.subTest(minutes=minutes, cap=cap), workspace({"repas": {"duree_active_max_min": cap}},
                                                                  recipes=[adapted(temps_actif_min=minutes)]) as d:
                self.assertEqual("duree_active" in codes(analyse(d)), error)

    def test_active_time_above_total_is_hard_in_plan_and_recipe(self):
        r = adapted(temps_actif_min=40)
        with workspace({"exigences": {"duree_active": "preference", "duree": "preference"}}, recipes=[r]) as d:
            ctx = analyse(d)
            self.assertIn("temps_incoherent", codes(ctx))
            self.assertIn("temps_incoherent", {i.code for i in check_plan(plan_for([r]), ctx.profile) if i.level == "erreur"})


class TestFamiliesAndVariety(unittest.TestCase):
    def test_soy_derivatives_and_parent_family_are_excluded(self):
        for family in ("soja", "legumineuses"):
            for fid, unit in (("miso", "g"), ("sauce_soja", "ml")):
                with self.subTest(family=family, food=fid), workspace({"aliments": {"familles_exclues": [family]}},
                        recipes=[recipe("S01-R01", [ing(fid, 5, unit)])]) as d:
                    self.assertIn("famille_exclue", codes(analyse(d)))

    def test_family_avoidance_is_a_visible_preference(self):
        with workspace({"aliments": {"familles_a_eviter": ["produits_animaux"]}}) as d:
            ctx = analyse(d)
            self.assertFalse(codes(ctx))
            self.assertEqual(preference_counts(ctx), (1, 0))
            self.assertIn("famille_a_eviter", render_classeur(ctx, ctx.shops, ctx.final_stock, []))

    def test_explicit_composite_tag_and_its_parents_are_checked(self):
        with workspace({"aliments": {"familles_exclues": ["legumineuses"]}}) as d:
            local_foods(d, {"oeuf": {"tags": "famille:soja"}})  # Produit composite fictif pour ce test.
            self.assertIn("famille_exclue", codes(analyse(d)))

    def test_family_exclusion_in_fish_alternative_cannot_be_bypassed(self):
        r = recipe("S01-R01", [ing("sardine", 200)], alternatives_poisson=[ing("maquereau_fume", 200)])
        with workspace({"aliments": {"familles_exclues": ["soja"]}}, recipes=[r]) as d:
            local_foods(d, {"maquereau_fume": {"tags": "famille:soja|espece:maquereau"}})
            ctx = analyse(d)
            self.assertIn("famille_exclue", codes(ctx))
            self.assertIn("alternative", next(i.msg for i in ctx.issues if i.code == "famille_exclue"))

    def test_same_dish_renamed_does_not_increase_variety(self):
        recipes = [adapted(), adapted("S01-R02", nom="Autre titre")]
        with workspace({"variete": {"recettes_distinctes_min_par_semaine": 2, "repetition_plat_max": 1}}, recipes=recipes) as d:
            ctx = analyse(d)
            self.assertTrue({"variete_plats", "repetition_plat"} <= codes(ctx))
            self.assertTrue({"variete_plats", "repetition_plat"} <= {i.code for i in check_plan(plan_for(recipes), ctx.profile)})

    def test_repeat_limit_spans_weeks_and_zero_forbids_any_dish(self):
        weeks = [{"semaine": wid, "recettes": [adapted(wid + "-R01")]} for wid in ("S01", "S02")]
        with workspace({"projet": {"semaines": 2}, "variete": {"repetition_plat_max": 1}}, weeks=weeks) as d:
            self.assertIn("repetition_plat", codes(analyse(d)))
        with workspace({"variete": {"repetition_plat_max": 0}}, recipes=[adapted()]) as d:
            self.assertIn("repetition_plat", codes(analyse(d)))

    def test_only_declared_principal_ingredients_count_for_recurrence(self):
        recipes = [adapted(ingredients_principaux=["oeuf"]), adapted("S01-R02", ingredients_principaux=["pomme_de_terre"])]
        with workspace({"variete": {"ingredient_principal_max_par_semaine": 1}}, recipes=recipes) as d:
            self.assertNotIn("ingredient_recurrent", codes(analyse(d)))
        recipes[1]["ingredients_principaux"] = ["oeuf"]
        with workspace({"variete": {"ingredient_principal_max_par_semaine": 1}}, recipes=recipes) as d:
            self.assertIn("ingredient_recurrent", codes(analyse(d)))

    def test_technique_variety_counts_unique_techniques(self):
        recipes = [adapted(), adapted("S01-R02")]
        for target in (2, 3):
            with self.subTest(target=target), workspace({"variete": {"techniques_distinctes_min_par_semaine": target}}, recipes=recipes) as d:
                self.assertEqual("variete_techniques" in codes(analyse(d)), target == 3)

    def test_all_variety_targets_require_metadata_and_can_be_preferences(self):
        rules = {"variete_plats": "recettes_distinctes_min_par_semaine", "repetition_plat": "repetition_plat_max",
                 "ingredient_recurrent": "ingredient_principal_max_par_semaine", "variete_techniques": "techniques_distinctes_min_par_semaine"}
        for policy in ("imperative", "preference"):
            with self.subTest(policy=policy), workspace({"variete": {key: 1 for key in rules.values()},
                                                        "exigences": {key: policy for key in rules}}) as d:
                ctx = analyse(d)
                self.assertEqual(set(rules) <= codes(ctx), policy == "imperative")
                if policy == "preference":
                    self.assertEqual(preference_counts(ctx), (0, 4))
                    self.assertEqual(score_run(d)["preferences_non_verifiables"], 4)


if __name__ == "__main__":
    unittest.main()
