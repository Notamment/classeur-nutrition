"""Parcours publics v2, compatibilité et intégrité des préférences."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import yaml

from test_binder import ROOT, DEMO, codes, filler, ing, recipe
from test_regressions import cli, local_foods, score_run
from checks import analyse, check_plan, check_profile
from core import DEFAULT_PROFILE, DataError, compute_recipe, deep_merge, load_foods
from profiles import list_presets, resolve_profile
from render import audit_rows, render_audit, render_classeur
from shopping import build_shopping


@contextmanager
def workspace(profile=None, recipes=None, weeks=None):
    with tempfile.TemporaryDirectory() as temp:
        d = Path(temp)
        rs = recipes or [filler("S01-R01")]
        p = deep_merge({"version": 2, "projet": {"recettes_par_semaine": len(rs), "mois": ["octobre"]}}, profile or {})
        (d / "profile.yaml").write_text(yaml.safe_dump(p, allow_unicode=True), encoding="utf-8")
        (d / "weeks").mkdir()
        for w in weeks or [{"semaine": "S01", "recettes": rs}]:
            (d / "weeks" / (w["semaine"] + ".json")).write_text(json.dumps(w), encoding="utf-8")
        yield d


def plan(cuisine=None, theme=None, categorie="vegetarien"):
    w = {"id": "S01", "recettes": [{"id": "S01-R01", "plat": "Repas", "categorie": categorie, "legumineuses": False}]}
    if cuisine:
        w["cuisine"] = cuisine
    if theme:
        w["theme"] = theme
    return {"semaines": [w]}


class TestResolution(unittest.TestCase):
    def test_missing_version_keeps_legacy_defaults(self):
        self.assertEqual(resolve_profile({}).profile, DEFAULT_PROFILE)
        self.assertEqual(resolve_profile({"version": 1}).profile, DEFAULT_PROFILE)

    def test_neutral_defaults_are_valid_without_hidden_targets(self):
        p = resolve_profile({"version": 2}).profile
        foods, _ = load_foods()
        self.assertFalse([i for i in check_profile(p, foods) if i.level == "erreur"])
        self.assertIsNone(p["repartition"])
        self.assertIsNone(p["repas"]["proteines_g_par_portion"])
        self.assertIsNone(p["materiel"])
        self.assertEqual(p["aliments"]["exclus"], [])
        self.assertEqual(p["nutrition"]["mode"], "desactive")
        self.assertFalse(p["variete"]["cuisines_distinctes"])
        self.assertNotEqual(p["labels"]["defaut"], "bio")

    def test_each_bundled_preset_resolves_and_validates(self):
        foods, _ = load_foods()
        self.assertEqual(len(list_presets()), 6)
        for name in list_presets():
            with self.subTest(name=name):
                p = resolve_profile({"version": 2, "prereglages": [name]}).profile
                self.assertFalse([i for i in check_profile(p, foods) if i.level == "erreur"])

    def test_composition_is_order_independent_and_explicit_values_win(self):
        names = ["rapide", "vegetarien", "petit_budget", "gamelles"]
        raw = {"version": 2, "prereglages": names, "repas": {"duree_totale_max_min": 25},
               "budget": {"plafond_eur_semaine": 35}, "projet": {"portions_par_recette": 4}}
        r = resolve_profile(raw)
        other = resolve_profile({**raw, "prereglages": names[::-1]})
        a, b = copy.deepcopy(r.profile), copy.deepcopy(other.profile)
        a.pop("prereglages"); b.pop("prereglages")
        self.assertEqual(a, b)
        self.assertEqual(r.profile["projet"]["portions_par_recette"], 4)
        self.assertEqual(r.origins["repas.duree_totale_max_min"], "profil")
        self.assertEqual(r.origins["alimentation.regime"], "prereglage:vegetarien")
        self.assertEqual(r.origins["nutrition.mode"], "defaut:v2")

    def test_empty_mapping_does_not_erase_provenance_or_resolve_conflicts(self):
        r = resolve_profile({"version": 2, "projet": {}})
        self.assertEqual(r.origins["projet.semaines"], "defaut:v2")
        catalog = {"a": {"profil": {"repas": {"duree_totale_max_min": 20}}},
                   "b": {"profil": {"repas": {"duree_totale_max_min": 40}}}}
        with patch("profiles.list_presets", return_value=catalog):
            with self.assertRaises(DataError):
                resolve_profile({"version": 2, "prereglages": ["a", "b"], "repas": {}})

    def test_preset_conflict_requires_explicit_choice(self):
        catalog = {"a": {"profil": {"repas": {"duree_totale_max_min": 20}}},
                   "b": {"profil": {"repas": {"duree_totale_max_min": 40}}}}
        with patch("profiles.list_presets", return_value=catalog):
            with self.assertRaises(DataError) as cm:
                resolve_profile({"version": 2, "prereglages": ["a", "b"]})
            self.assertEqual(cm.exception.issues[0].code, "prereglages_conflit")
            p = resolve_profile({"version": 2, "prereglages": ["a", "b"],
                                 "repas": {"duree_totale_max_min": None}}).profile
            self.assertIsNone(p["repas"]["duree_totale_max_min"])

    def test_invalid_names_versions_and_duplicates_are_controlled(self):
        for raw in ({"version": True}, {"version": 3}, {"version": "2"},
                    {"version": 2, "prereglages": ["../profile"]},
                    {"version": 2, "prereglages": ["inconnu"]},
                    {"version": 2, "prereglages": ["rapide", "rapide"]}):
            with self.subTest(raw=raw), self.assertRaises(DataError):
                resolve_profile(raw)

    def test_v1_rejects_v2_configuration(self):
        foods, _ = load_foods()
        p = resolve_profile({"version": 1, "prereglages": ["rapide"]}).profile
        self.assertIn("schema_profil", {i.code for i in check_profile(p, foods)})

    def test_invalid_partial_preset_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            (d / "bad.yaml").write_text("nom: Test\ndescription: Test\nprofil:\n  repas:\n    duree_totale_max_min: faux\n", encoding="utf-8")
            with patch("profiles.PRESETS_DIR", d), self.assertRaises(DataError):
                list_presets()

    def test_template_is_v2_and_neutral(self):
        raw = yaml.safe_load((ROOT / "skills/meal-setup/assets/profile.template.yaml").read_text(encoding="utf-8"))
        self.assertEqual(raw["version"], 2)
        self.assertIsNone(resolve_profile(raw).profile["repas"]["proteines_g_par_portion"])


class TestOptionalNutrition(unittest.TestCase):
    def test_disabled_missing_nutrients_keep_recipe_shopping_and_render(self):
        r = filler("S01-R01")
        r.pop("gamelle"); r.pop("authenticite")
        with workspace(recipes=[r]) as d:
            local_foods(d, {"oeuf": {"prot_g_100g": "", "kcal_100g": ""}})
            ctx = analyse(d, complete=True)
            self.assertFalse(codes(ctx))
            self.assertIsNone(ctx.calcs["S01-R01"].prot_pp)
            self.assertEqual(next(s for s in ctx.shops[0].lines if s.food.id == "oeuf").besoin, 6)
            self.assertNotIn("nutrition_absente", {i.code for i in ctx.issues})
            text = render_classeur(ctx, ctx.shops, ctx.final_stock, [])
            for unwanted in ("Prot./portion", "kcal", "Fer + vitamine C", "**Gamelle**", "**Authenticité**", "bio"):
                self.assertNotIn(unwanted, text)
            self.assertIn("aucun calcul nutritionnel", text)

    def test_information_has_unknown_value_not_false_zero_or_partial_sum(self):
        with workspace({"nutrition": {"mode": "information"}}) as d:
            local_foods(d, {"oeuf": {"prot_g_100g": ""}})
            ctx = analyse(d, complete=True)
            rc = ctx.calcs["S01-R01"]
            self.assertIsNone(rc.prot_pp)
            self.assertIsNotNone(rc.kcal_pp)
            self.assertFalse(codes(ctx))
            self.assertIn("nutrition_absente", {i.code for i in ctx.issues})
            self.assertIn("— g de protéines", render_classeur(ctx, ctx.shops, ctx.final_stock, []))

    def test_missing_required_nutrient_blocks_target_but_keeps_shopping(self):
        with workspace({"nutrition": {"mode": "cibles"}, "repas": {"proteines_g_par_portion": [1, 99]}}) as d:
            local_foods(d, {"oeuf": {"prot_g_100g": ""}})
            ctx = analyse(d, complete=True)
            self.assertIn("proteines", codes(ctx))
            self.assertEqual(len(ctx.calcs), 1)
            self.assertTrue(ctx.shops[0].lines)
            self.assertFalse(score_run(d)["conforme"])

    def test_information_does_not_enforce_configured_macro_targets(self):
        with workspace({"nutrition": {"mode": "information", "fer_vitamine_c": "chaque_repas"},
                        "repas": {"proteines_g_par_portion": [100, 150], "kcal_par_portion": [1, 2]}}) as d:
            ctx = analyse(d, complete=True)
            self.assertFalse(codes(ctx))
            self.assertIn("cibles_inactives", {i.code for i in ctx.issues})

    def test_nutrition_mode_preserves_quantities_and_purchase_allocations(self):
        snapshots = []
        w = json.loads((DEMO / "weeks/S01.json").read_text(encoding="utf-8"))
        for mode in ("desactive", "information", "cibles"):
            with workspace({"projet": {"recettes_par_semaine": 5}, "nutrition": {"mode": mode}}, weeks=[w]) as d:
                ctx = analyse(d, complete=True)
                snapshots.append([(s.food.id, s.besoin, s.achat, s.reste, s.allocations) for s in ctx.shops[0].lines])
        self.assertEqual(snapshots[0], snapshots[1])
        self.assertEqual(snapshots[1], snapshots[2])

    def test_v1_still_rejects_missing_nutrition(self):
        foods, _ = load_foods()
        foods["oeuf"].prot = None
        calc, issues = compute_recipe(filler("S01-R01"), foods, 2)
        self.assertIsNone(calc)
        self.assertIn("nutrition_absente", {i.code for i in issues})

    def test_alternatives_with_unknown_nutrition_render_in_all_modes(self):
        r = recipe("S01-R01", [ing("sardine", 200)], alternatives_poisson=[ing("hareng_marine", 200)])
        for mode in ("desactive", "information", "cibles"):
            with self.subTest(mode=mode), workspace({"nutrition": {"mode": mode}}, recipes=[r]) as d:
                local_foods(d, {"hareng_marine": {"prot_g_100g": "", "kcal_100g": ""}})
                ctx = analyse(d, complete=True)
                self.assertFalse(codes(ctx))
                self.assertIsNone(ctx.alts["S01-R01"][0]["prot_pp"])
                self.assertIn("Alternatives poisson", render_classeur(ctx, ctx.shops, ctx.final_stock, []))


class TestRequirements(unittest.TestCase):
    def test_duration_hard_vs_preference_in_cli_audit_and_score(self):
        for severity in ("imperative", "preference"):
            with self.subTest(severity=severity), workspace({"repas": {"duree_totale_max_min": 20},
                                                           "exigences": {"duree": severity}}) as d:
                ctx = analyse(d, complete=True)
                self.assertEqual("duree" in codes(ctx), severity == "imperative")
                result = cli(d, "render")
                self.assertEqual(result.returncode, int(severity == "imperative"), result.stderr)
                row = next(r for r in audit_rows(ctx, ctx.shops) if r[0] == "Temps total maximal")
                self.assertEqual(row[-1], "non conforme" if severity == "imperative" else "préférence non satisfaite")
                self.assertEqual(score_run(d)["conforme"], severity == "preference")

    def test_impossible_times_are_never_softened(self):
        with workspace({"exigences": {"duree": "preference"}}, recipes=[filler("S01-R01") | {"temps_actif_min": 60}]) as d:
            self.assertIn("temps_incoherent", codes(analyse(d)))

    def test_structural_and_diet_rules_cannot_be_downgraded(self):
        foods, _ = load_foods()
        for code in ("schema_recette", "regime", "aliment_exclu", "conversion", "temps_incoherent"):
            p = resolve_profile({"version": 2, "exigences": {code: "preference"}}).profile
            self.assertIn("schema_profil", {i.code for i in check_profile(p, foods)})

    def test_excluded_vs_avoided_ingredient(self):
        for field, code, level in (("exclus", "aliment_exclu", "erreur"), ("a_eviter", "aliment_a_eviter", "alerte")):
            with workspace({"aliments": {field: ["oeuf"]}}) as d:
                issues = analyse(d).issues
                self.assertEqual(next(i.level for i in issues if i.code == code), level)

    def test_unknown_macro_target_can_be_a_preference_without_claiming_validated(self):
        with workspace({"nutrition": {"mode": "cibles"}, "repas": {"proteines_g_par_portion": [30, 40]},
                        "exigences": {"proteines": "preference"}}) as d:
            local_foods(d, {"oeuf": {"prot_g_100g": ""}})
            ctx = analyse(d)
            self.assertFalse(codes(ctx))
            self.assertIn("non vérifiable", next(i.msg for i in ctx.issues if i.code == "proteines"))

    def test_budget_preference_reaches_shopping_cli_audit_and_evaluation(self):
        for severity in ("imperative", "preference"):
            with workspace({"budget": {"plafond_eur_semaine": 0}, "exigences": {"budget_depasse": severity}}) as d:
                local_foods(d, prices=True)
                ctx = analyse(d, complete=True)
                _, _, issues = build_shopping(ctx)
                issue = next(i for i in issues if i.code == "budget_depasse")
                self.assertEqual(issue.level, "erreur" if severity == "imperative" else "alerte")
                self.assertEqual(cli(d, "audit").returncode, int(severity == "imperative"))
                self.assertEqual(score_run(d)["conforme"], severity == "preference")
                self.assertIn("non conforme" if severity == "imperative" else "préférence non satisfaite", render_audit(ctx, ctx.shops))

    def test_unknown_budget_is_not_a_false_failure_for_preferences(self):
        for severity in ("imperative", "preference"):
            with workspace({"budget": {"plafond_eur_semaine": 40}, "exigences": {"budget_depasse": severity}}) as d:
                score = score_run(d)
                self.assertEqual(score["budget"], "non vérifié")
                self.assertEqual(score["conforme"], severity == "preference")

    def test_invalid_quantity_remains_hard_with_nutrition_off_and_preferences(self):
        with workspace({"exigences": {"proteines": "preference", "budget_depasse": "preference"}},
                       recipes=[recipe("S01-R01", [ing("oeuf", -1, "piece")])]) as d:
            ctx = analyse(d)
            self.assertIn("schema_recette", codes(ctx))
            self.assertFalse(ctx.calcs)


class TestGeneralistScenarios(unittest.TestCase):
    def test_fish_alternatives_without_fish_are_not_silently_ignored(self):
        r = filler("S01-R01") | {"alternatives_poisson": [ing("sardine", 100)]}
        with workspace({"alimentation": {"regime": "vegetarien"}}, recipes=[r]) as d:
            self.assertIn("alternative_invalide", codes(analyse(d)))

    def test_distinct_cuisines_require_cuisine_names_even_in_free_mode(self):
        with workspace({"variete": {"cuisines_distinctes": True}}) as d:
            ctx = analyse(d)
            self.assertIn("organisation", codes(ctx))
            self.assertIn("organisation", {i.code for i in check_plan(plan(), ctx.profile)})

    def test_diets_use_actual_ingredients_including_animal_condiments(self):
        cases = [("vegetarien", "sardine", False), ("vegetarien", "oeuf", True),
                 ("vegetalien", "oeuf", False), ("vegetalien", "skyr", False),
                 ("vegetalien", "pois_chiche_egoutte", True), ("pescetarien", "sardine", True),
                 ("pescetarien", "poulet_cuisse", False)]
        for regime, food, valid in cases:
            with self.subTest(regime=regime, food=food), workspace({"alimentation": {"regime": regime}},
                    recipes=[recipe("S01-R01", [ing(food, 100)])]) as d:
                self.assertEqual("regime" not in codes(analyse(d)), valid)

    def test_conflicting_diet_and_quota_is_profile_error(self):
        foods, _ = load_foods()
        p = resolve_profile({"version": 2, "prereglages": ["vegetarien"],
                             "repartition": {"vegetarien": 4, "poisson": 1, "viande": 0},
                             "exigences": {"repartition": "preference"}}).profile
        self.assertIn("regime", {i.code for i in check_profile(p, foods) if i.level == "erreur"})

    def test_mixed_meat_and_fish_allowed_only_if_diet_permits(self):
        r = recipe("S01-R01", [ing("sardine", 100), ing("poulet_cuisse", 100)])
        with workspace(recipes=[r]) as d:
            ctx = analyse(d, complete=True)
            self.assertEqual(ctx.calcs["S01-R01"].categorie, "mixte")
            self.assertFalse(codes(ctx))
        with workspace({"alimentation": {"regime": "pescetarien"}}, recipes=[r]) as d:
            self.assertIn("regime", codes(analyse(d)))

    def test_free_plan_and_conditional_theme_or_cuisine(self):
        for mode, valid, invalid in (("libre", plan(), None), ("themes", plan(theme="Repas froids"), plan()),
                                     ("cuisines", plan(cuisine="Pologne"), plan())):
            p = resolve_profile({"version": 2, "projet": {"recettes_par_semaine": 1, "organisation": mode}}).profile
            self.assertFalse([i for i in check_plan(valid, p) if i.level == "erreur"])
            if invalid:
                self.assertIn("organisation", {i.code for i in check_plan(invalid, p)})

    def test_plan_quota_can_be_preference_but_sum_remains_strict(self):
        p = resolve_profile({"version": 2, "projet": {"recettes_par_semaine": 1},
                             "repartition": {"vegetarien": 0, "poisson": 1, "viande": 0},
                             "exigences": {"repartition": "preference"}}).profile
        issues = check_plan(plan(), p)
        self.assertFalse([i for i in issues if i.level == "erreur"])
        self.assertTrue([i for i in issues if i.code == "repartition"])
        p["repartition"]["poisson"] = 2
        self.assertTrue([i for i in check_profile(p, load_foods()[0]) if i.code == "repartition" and i.level == "erreur"])

    def test_repeated_cuisines_are_free_unless_requested(self):
        ws = [{"semaine": f"S0{n}", "cuisine": "France", "recettes": [filler(f"S0{n}-R01")]} for n in (1, 2)]
        for distinct in (False, True):
            with workspace({"projet": {"semaines": 2}, "variete": {"cuisines_distinctes": distinct}}, weeks=ws) as d:
                self.assertEqual("cuisine_doublon" in codes(analyse(d, complete=True)), distinct)

    def test_documented_authenticity_is_conditional(self):
        r = filler("S01-R01")
        r.pop("authenticite")
        with workspace({"prereglages": ["cuisines_du_monde"]},
                       weeks=[{"semaine": "S01", "cuisine": "France", "recettes": [r]}]) as d:
            self.assertIn("authenticite", codes(analyse(d)))

    def test_cli_catalog_and_resolved_profile_have_stable_json_shapes(self):
        with workspace({"prereglages": ["rapide"]}) as d:
            r = cli(d, "list-presets")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("rapide", json.loads(r.stdout))
            r = cli(d, "show-profile")
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(payload["profil"]["repas"]["duree_totale_max_min"], 30)
            self.assertEqual(payload["origines"]["repas.duree_totale_max_min"], "prereglage:rapide")
            self.assertIsInstance(payload["ecarts"], list)

    def test_example_workflows_all_render_without_errors(self):
        import shutil
        folders = sorted((ROOT / "examples/generaliste").glob("*/profile.yaml"))
        self.assertEqual(len(folders), 3)
        for profile in folders:
            with self.subTest(example=profile.parent.name), tempfile.TemporaryDirectory() as temp:
                d = Path(temp) / "example"
                shutil.copytree(profile.parent, d)
                for command, args in (("check-profile", ()), ("show-profile", ()), ("check-plan", ()),
                                      ("check-week", ("S01",)), ("check-all", ()), ("render", ()), ("audit", ())):
                    r = cli(d, command, *args)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertTrue((d / "out/classeur.md").exists())


if __name__ == "__main__":
    unittest.main()
