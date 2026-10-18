"""Régressions issues de la revue : entrées hostiles, conversions et parcours réels."""
from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from test_binder import ROOT, DEMO, Workdir, codes, filler, ing, recipe
from checks import analyse, check_pantry, check_plan, check_profile
from core import (DataError, BinderError, compute_recipe, fmt_qty, load_foods,
                  load_json, load_profile, load_yaml, to_base, to_grams)
from render import audit_rows, render_classeur, shopping_block
from shopping import build_shopping, choose_packs, initial_stock
import binder

sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "tools"))
from score import score_run
from check_demo import EXPECTED, verify_result

CLI = ROOT / "skills/meal-binder/scripts/binder.py"


def week(first=None, n=1):
    wid = f"S{n:02d}"
    return {"semaine": wid, "cuisine": f"Test {n}",
            "recettes": [first or filler(f"{wid}-R01")] + [filler(f"{wid}-R{i:02d}") for i in range(2, 6)]}


def local_foods(directory, changes=None, prices=False):
    with (ROOT / "skills/meal-binder/data/foods.csv").open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields, rows = reader.fieldnames, list(reader)
    for row in rows:
        if prices:
            row["prix_eur"] = "1"  # Prix FICTIFS, réservés aux tests.
        row.update((changes or {}).get(row["id"], {}))
    with (directory / "foods.local.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        writer.writerows(rows)


def cli(directory, command="check-all", *args, env=None):
    return subprocess.run([sys.executable, str(CLI), command, *args, "--dir", str(directory), "--json"],
                          capture_output=True, text=True, encoding="utf-8", timeout=15, env=env)


def line(ctx, food, index=0):
    return next(sl for sl in ctx.shops[index].lines if sl.food.id == food)


class TestSchemas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.foods, _ = load_foods()

    def test_invalid_profiles_are_rejected_before_calculation(self):
        for path, value in [("projet.portions_par_recette", 0), ("projet.semaines", True),
                            ("repas.duree_totale_max_min", "45"), ("repas.proteines_g_par_portion", [40, 32]),
                            ("repas.proteines_g_par_portion", [0, float("inf")]),
                            ("repartition.poisson", -1), ("budget.plafond_eur_semaine", float("nan")),
                            ("legumineuses.soja_compte", "false"), ("materiel", "plaque"),
                            ("projet", None)]:
            with self.subTest(path=path, value=value):
                p = load_profile(DEMO)
                parts = path.split(".")
                node = p
                for key in parts[:-1]:
                    node = node[key]
                node[parts[-1]] = value
                self.assertTrue(any(i.code == "schema_profil" for i in check_profile(p, self.foods)))

    def test_zero_portions_no_division_by_zero(self):
        calc, issues = compute_recipe(filler("S01-R01"), self.foods, 0)
        self.assertIsNone(calc)
        self.assertEqual({i.code for i in issues}, {"portions"})
        with Workdir([week()], projet__portions_par_recette=0) as d:
            with self.assertRaises(DataError):
                analyse(d)
            result = cli(d)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)[0]["code"], "schema_profil")
            self.assertNotIn("Traceback", result.stderr)

    def test_recipe_schema_rejects_invalid_values(self):
        mutations = [dict(temps_total_min="999"), dict(temps_total_min=-1), dict(eau_retenue_g=-100),
                     dict(eau_retenue_g=float("nan")), dict(sel_ajoute="false"), dict(etapes="x"),
                     dict(ingredients=[None]), dict(appareils="plaque"), dict(champ_invente=True)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                r = filler("S01-R01")
                r.update(mutation)
                calc, issues = compute_recipe(r, self.foods, 2)
                self.assertIsNone(calc)
                self.assertTrue(issues)

    def test_ingredient_schema_rejects_nonpositive_and_nonfinite_quantities(self):
        for value in (0, -1, True, "20", None, float("nan"), float("inf"), 10**400):
            with self.subTest(value=value):
                calc, issues = compute_recipe(recipe("S01-R01", [ing("citron_jus", value, "ml")]), self.foods, 2)
                self.assertIsNone(calc)
                self.assertTrue(any("qte" in i.msg for i in issues))

    def test_zero_lemon_cannot_validate_vitamin_c(self):
        r = recipe("S01-R01", [ing("oeuf", 6, "piece"), ing("citron_jus", 0, "ml")])
        with Workdir([week(r)]) as d:
            ctx = analyse(d, complete=True)
            self.assertNotIn("S01-R01", ctx.calcs)
            self.assertIn("schema_recette", codes(ctx, "S01-R01"))
            self.assertFalse(score_run(d)["conforme"])

    def test_invalid_yields_and_purchase_blocks(self):
        for kw in ({"rendement": 0}, {"rendement": -1}, {"rendement": "1.5"},
                   {"rendement": float("inf")}, {"achat": {}},
                   {"achat": {"qte": -550, "unite": "g", "forme": "entier"}},
                   {"achat": {"qte": 550, "unite": "g"}}):
            with self.subTest(kw=kw):
                calc, issues = compute_recipe(recipe("S01-R01", [ing("sardine", 270, **kw)]), self.foods, 2)
                self.assertIsNone(calc)
                self.assertTrue(issues)

    def test_raw_purchase_smaller_than_edible_or_wrong_dimension(self):
        for purchase in ({"qte": 200, "unite": "g", "forme": "entier"},
                         {"qte": 550, "unite": "ml", "forme": "entier"}):
            calc, issues = compute_recipe(recipe("S01-R01", [ing("sardine", 270, achat=purchase)]), self.foods, 2)
            self.assertIsNone(calc)
            self.assertIn("achat", {i.code for i in issues})

    def test_pantry_and_plan_shapes(self):
        for entries in ({"id": "oeuf"}, [None], [{"id": "oeuf", "quantite": -1}],
                        [{"id": "oeuf", "quantite": True}]):
            self.assertTrue(check_pantry(entries, self.foods))
            with self.assertRaises(DataError):
                initial_stock(entries, self.foods)
        self.assertTrue(check_plan({"semaines": "S01"}, load_profile(DEMO)))

    def test_invalid_week_and_stores_return_controlled_errors(self):
        for filename, data in [("weeks/S01.json", {"semaine": "S01", "cuisine": "Test", "recettes": [None]}),
                               ("stores.yaml", {"magasins": "supermarché"})]:
            with self.subTest(filename=filename), Workdir([week()]) as d:
                (d / filename).write_text(json.dumps(data), encoding="utf-8")
                result = cli(d)
                self.assertEqual(result.returncode, 1)
                self.assertTrue(json.loads(result.stdout)[0]["code"].startswith("schema_"))

    def test_loaders_reject_duplicates_malformed_and_nonfinite_json(self):
        cases = [("x.json", '{"a":1,"a":2}', load_json), ("x.json", '{"a":NaN}', load_json),
                 ("x.json", '{"a":Infinity}', load_json), ("x.yaml", "a: 1\na: 2\n", load_yaml),
                 ("x.yaml", "a: [", load_yaml), ("x.yaml", "- item\n", load_yaml)]
        with tempfile.TemporaryDirectory() as td:
            for name, data, loader in cases:
                with self.subTest(data=data):
                    path = Path(td) / name
                    path.write_text(data, encoding="utf-8")
                    with self.assertRaises(BinderError):
                        loader(path)

    def test_food_numbers_and_duplicate_ids(self):
        cases = [{"rendement": "0"}, {"densite_g_ml": "-1"}, {"prix_eur": "NaN"},
                 {"prot_g_100g": "-1"}, {"kcal_100g": "inf"}, {"conditionnements": "0.5"},
                 {"conditionnements": "-2"}, {"report_ok": "yes"}, {"rayon": "Inconnu"}]
        with Workdir([week()]) as d:
            for change in cases:
                with self.subTest(change=change):
                    local_foods(d, {"oeuf": change})
                    _, issues = load_foods(d)
                    self.assertTrue(any(i.level == "erreur" for i in issues))
            local_foods(d)
            path = d / "foods.local.csv"
            text = path.read_text(encoding="utf-8")
            path.write_text(text + text.splitlines()[1] + "\n", encoding="utf-8")
            self.assertIn("foods_doublon", {i.code for i in load_foods(d)[1]})

    def test_csv_headers_and_truncated_rows(self):
        with Workdir([week()]) as d:
            local_foods(d)
            path = d / "foods.local.csv"
            text = path.read_text(encoding="utf-8")
            for bad in ("", "id,nom\noeuf,Œuf\n", text.splitlines()[0] + ",id\n"):
                with self.subTest(bad=bad):
                    path.write_text(bad, encoding="utf-8")
                    self.assertIn("foods_colonnes", {i.code for i in load_foods(d)[1]})
            path.write_text(text.splitlines()[0] + "\noeuf,Œuf\n", encoding="utf-8")
            self.assertIn("foods_ligne", {i.code for i in load_foods(d)[1]})


class TestConversions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.foods, _ = load_foods()

    def test_dry_legumes_override_used_everywhere(self):
        r = recipe("S01-R01", [ing("lentille_verte_seche", 95, rendement=1.5), ing("citron_jus", 10, "ml")])
        with Workdir([week(r)]) as d:
            ctx = analyse(d)
            rc = ctx.calcs["S01-R01"]
            self.assertAlmostEqual(rc.legumes_g_pp, 71.25)
            self.assertAlmostEqual(rc.lines[0].served / 2, 71.25)
            self.assertIn("legumineuses_g", codes(ctx, "S01-R01"))

    def test_base_conversion_keeps_fractional_pieces(self):
        lemon = self.foods["citron_jus"]
        self.assertAlmostEqual(to_grams(lemon, 10, "ml"), 10.3)
        self.assertAlmostEqual(to_base(lemon, 10, "ml"), 0.2575)
        self.assertEqual(fmt_qty(to_base(lemon, 10, "ml"), "piece"), "0,2575 pc")

    def test_mass_volume_and_spoon_conversions(self):
        oil = self.foods["huile_olive"]
        self.assertAlmostEqual(to_grams(oil, 1, "cas"), 13.8)
        self.assertEqual(to_base(oil, 1, "cas"), 15)
        self.assertAlmostEqual(to_base(oil, 13.8, "g"), 15)
        self.assertEqual(to_grams(self.foods["poivre"], 1, "cac"), 2.5)
        self.assertEqual(to_grams(self.foods["sardine"], .27, "kg"), 270)

    def test_precision_of_displayed_quantities(self):
        for value, unit, expected in [(0.5, "g", "0,5 g"), (0.3, "g", "0,3 g"),
                                       (0.125, "piece", "0,125 pc"), (0.1 + 0.2, "g", "0,3 g"),
                                       (1500, "g", "1,5 kg"), (.000001, "g", "1e-06 g")]:
            with self.subTest(value=value):
                self.assertEqual(fmt_qty(value, unit), expected)

    def test_invalid_pack_sizes_are_not_silently_rounded(self):
        for sizes in ([0.5], [0], [-1], [True], [float("nan")]):
            with self.assertRaises(ValueError):
                choose_packs(1, sizes)
        self.assertEqual(choose_packs(.000001, []), (1.0, []))

    def test_fish_cannot_be_hidden_as_a_pinch(self):
        rc, issues = compute_recipe(recipe("S01-R01", [ing("sardine", 1, "pincee")]), self.foods, 2)
        self.assertIsNone(rc)
        self.assertIn("unite", {i.code for i in issues})

    def test_alternative_nature_state_and_profile_exclusions(self):
        for alternative, exclusions in [(ing("poulet_cuisse", 270), []),
                                         (ing("sardine", 270, etat="cuit"), []),
                                         (ing("sardine", 270), ["sardine"])]:
            with self.subTest(alternative=alternative):
                r = recipe("S01-R01", [ing("hareng_marine", 260), ing("citron_jus", 10, "ml")],
                           alternatives_poisson=[alternative])
                with Workdir([week(r)], repartition=(4, 1, 0), aliments__exclus=exclusions) as d:
                    self.assertIn("alternative_invalide", codes(analyse(d), "S01-R01"))

    def test_alternative_uses_same_recipe_calculator(self):
        r = recipe("S01-R01", [ing("sardine", 270), ing("citron_jus", 10, "ml")],
                   alternatives_poisson=[ing("sardine", 270, rendement=0.5)])
        with Workdir([week(r)], repartition=(4, 1, 0)) as d:
            ctx = analyse(d)
            alt = ctx.alts["S01-R01"][0]
            self.assertAlmostEqual(alt["poids_pp"], (135 + 10.3) / 2)
            self.assertAlmostEqual(alt["prot_pp"], ctx.calcs["S01-R01"].prot_pp)


class TestShoppingRegressions(unittest.TestCase):
    def fish_recipe(self, **purchase):
        return recipe("S01-R01", [ing("sardine", 270, achat={"qte": 550, "unite": "g", "forme": "entier", **purchase}),
                                   ing("citron_jus", 10, "ml")])

    def test_edible_stock_is_deducted_before_raw_conversion(self):
        for stock, expected in [(270, 0), (135, 275), (0, 550)]:
            with self.subTest(stock=stock), Workdir([week(self.fish_recipe())], repartition=(4, 1, 0),
                 pantry=[{"id": "sardine", "quantite": stock, "unite": "g", "etat": "cru"}]) as d:
                ctx = analyse(d)
                sl = line(ctx, "sardine")
                self.assertEqual(sl.besoin, 270)
                self.assertEqual(sl.mobilise, stock)
                self.assertEqual(sl.achat, expected)
                self.assertEqual(sl.net, 270 - stock)
                self.assertEqual(sum(a[1] for a in sl.allocations), 270)

    def test_raw_packages_and_price_are_separate_from_reference_food(self):
        with Workdir([week(self.fish_recipe(conditionnements=[300], prix_eur=10))], repartition=(4, 1, 0),
                     pantry=[{"id": "sardine", "quantite": 135, "unite": "g"}]) as d:
            local_foods(d, {"sardine": {"prix_eur": "99", "conditionnements": "1000"}})
            ctx = analyse(d)
            sl = line(ctx, "sardine")
            self.assertEqual(sl.achat, 300)
            self.assertAlmostEqual(sl.reste, 300 * 270 / 550 - 135)
            self.assertAlmostEqual(ctx.shops[0].montant_caisse, 3)
            text = "\n".join(shopping_block(ctx, ctx.shops[0]))
            self.assertIn("300 g brut (déficit converti : 275 g)", text)

    def test_gross_price_is_not_inferred_from_filet_price(self):
        with Workdir([week(self.fish_recipe())], repartition=(4, 1, 0)) as d:
            local_foods(d, prices=True)
            ctx = analyse(d)
            self.assertIn(ctx.foods["sardine"].nom, ctx.shops[0].prix_manquants)
            self.assertEqual(line(ctx, "sardine").achat, 550)

    def test_incompatible_purchase_forms_fail_closed(self):
        r = self.fish_recipe()
        r["ingredients"].append(ing("sardine", 10))
        with Workdir([week(r)], repartition=(4, 1, 0)) as d:
            ctx = analyse(d)
            self.assertIn("achat_formes", codes(ctx))
            self.assertFalse(line(ctx, "sardine").valide)
            self.assertIn("à corriger", "\n".join(shopping_block(ctx, ctx.shops[0])))

    def test_nonreportable_initial_stock_expires(self):
        weeks = [week(recipe(f"S0{n}-R01", [ing("cottage_cheese", 100), ing("citron_jus", 10, "ml")]), n)
                 for n in (1, 2)]
        with Workdir(weeks, semaines=2, repartition=(10, 0, 0),
                     pantry=[{"id": "cottage_cheese", "quantite": 200, "unite": "g"}]) as d:
            ctx = analyse(d)
            self.assertEqual(line(ctx, "cottage_cheese", 0).mobilise, 100)
            self.assertEqual(line(ctx, "cottage_cheese", 1).mobilise, 0)
            self.assertEqual(line(ctx, "cottage_cheese", 1).achat, 200)
            self.assertIn("stock_non_reportable", {i.code for i in ctx.issues})

    def test_unknown_stock_is_order_independent(self):
        foods, _ = load_foods()
        entries = [{"id": "oeuf", "quantite": None}, {"id": "oeuf", "quantite": 6}]
        self.assertIsNone(initial_stock(entries, foods)["oeuf"])
        self.assertIsNone(initial_stock(entries[::-1], foods)["oeuf"])

    def test_shopping_display_and_allocations_preserve_small_quantities(self):
        r = filler("S01-R01")
        r["ingredients"] += [ing("poivre", .3), ing("poivre", .2)]
        with Workdir([week(r)]) as d:
            ctx = analyse(d)
            sl = line(ctx, "poivre")
            self.assertAlmostEqual(sl.besoin, .5)
            text = "\n".join(shopping_block(ctx, ctx.shops[0]))
            self.assertIn("S01-R01 0,3 g + S01-R01 0,2 g | 0,5 g", text)

    def test_invalid_consumption_order_does_not_drop_or_duplicate_shopping(self):
        w = week()
        w["ordre"] = ["S01-R01"] * 5
        with Workdir([w]) as d:
            ctx = analyse(d)
            self.assertIn("ordre", codes(ctx))
            self.assertEqual(line(ctx, "oeuf").besoin, 30)

    def test_repeated_render_does_not_accumulate_issues(self):
        with Workdir([week()]) as d:
            ctx = analyse(d)
            before = list(ctx.issues)
            shops, stock, extra = build_shopping(ctx)
            a = render_classeur(ctx, shops, stock, extra)
            b = render_classeur(ctx, shops, stock, extra)
            self.assertEqual(a, b)
            self.assertEqual(ctx.issues, before)

    def test_raw_surplus_is_carried_as_edible_stock(self):
        first = self.fish_recipe(conditionnements=[600])
        second = recipe("S02-R01", [ing("sardine", 10), ing("citron_jus", 10, "ml")])
        with Workdir([week(first), week(second, 2)], semaines=2, repartition=(8, 2, 0)) as d:
            local_foods(d, {"sardine": {"report_ok": "1"}})  # Scénario de conservation fictif.
            ctx = analyse(d)
            self.assertAlmostEqual(line(ctx, "sardine").reste, 600 * 270 / 550 - 270)
            self.assertEqual(line(ctx, "sardine", 1).mobilise, 10)
            self.assertEqual(line(ctx, "sardine", 1).achat, 0)
            self.assertAlmostEqual(ctx.final_stock["sardine"], 600 * 270 / 550 - 280)


class TestBudgetAndCommands(unittest.TestCase):
    def budget_week(self):
        w = week()
        w["recettes"] = [recipe(f"S01-R{i:02d}", [ing("oeuf", 8, "piece"), ing("pomme_de_terre", 500),
                        ing("skyr", 100), ing("citron_jus", 10, "ml")]) for i in range(1, 6)]
        return w

    def test_cap_reaches_checks_render_audit_and_score(self):
        with Workdir([self.budget_week()], budget__plafond_eur_semaine=1,
                     repas__proteines_g_par_portion=[32, 40], repas__poids_servi_g_par_portion=[450, 580]) as d:
            local_foods(d, prices=True)
            ctx = analyse(d, complete=True)
            self.assertAlmostEqual(ctx.shops[0].montant_caisse, 47.1)
            self.assertEqual(codes(ctx), {"budget_depasse"})
            self.assertEqual(next(r[-1] for r in audit_rows(ctx, ctx.shops) if r[0] == "Budget"), "non conforme")
            score = score_run(d)
            self.assertEqual(score["taux_recettes"], 1)
            self.assertEqual(score["taux"], 0)
            self.assertFalse(score["conforme"])
            for command, args in [("check-all", ()), ("check-week", ("S01",)), ("render", ()), ("audit", ())]:
                with self.subTest(command=command):
                    result = cli(d, command, *args)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("budget_depasse", {i["code"] for i in json.loads(result.stdout)})
            self.assertIn("Plafond dépassé", (d / "out/classeur.md").read_text(encoding="utf-8"))

    def test_unknown_prices_and_stock_do_not_validate_budget(self):
        for missing_prices, pantry in [(True, []), (False, [{"id": "oeuf", "quantite": None, "unite": "piece"}])]:
            with self.subTest(missing_prices=missing_prices), Workdir([self.budget_week()], pantry=pantry,
                                                        budget__plafond_eur_semaine=100) as d:
                if not missing_prices:
                    local_foods(d, prices=True)
                ctx = analyse(d, complete=True)
                self.assertIn("budget_non_verifie", {i.code for i in ctx.issues})
                self.assertEqual(next(r[-1] for r in audit_rows(ctx, ctx.shops) if r[0] == "Budget"), "non vérifié")
                self.assertEqual(score_run(d)["taux"], 0)
                self.assertFalse(score_run(d)["conforme"])

    def test_known_subtotal_above_cap_still_fails_with_missing_prices(self):
        with Workdir([self.budget_week()], budget__plafond_eur_semaine=1) as d:
            local_foods(d, {"oeuf": {"prix_eur": "1"}})
            ctx = analyse(d)
            self.assertIn("budget_depasse", codes(ctx))
            self.assertIn("budget_non_verifie", {i.code for i in ctx.issues})

    def test_budget_at_cap_is_accepted(self):
        with Workdir([self.budget_week()], budget__plafond_eur_semaine=47.1) as d:
            local_foods(d, prices=True)
            ctx = analyse(d, complete=True)
            self.assertNotIn("budget_depasse", codes(ctx))
            self.assertTrue(score_run(d)["conforme"])

    def test_json_stdout_for_every_command(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "demo"
            shutil.copytree(DEMO, d)
            for command in ("check-profile", "check-plan", "check-week", "check-all", "render", "audit"):
                with self.subTest(command=command):
                    args = ("S01",) if command == "check-week" else ()
                    result = cli(d, command, *args)
                    self.assertIn(result.returncode, (0, 1), result.stderr)
                    self.assertIsInstance(json.loads(result.stdout), list)

    def test_windows_cp1252_pipe_does_not_crash(self):
        """Sortie redirigée sous Windows (cp1252) : « ≠ » et « Ś » ne doivent pas provoquer de panne."""
        import os
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "demo"
            shutil.copytree(DEMO, d)
            w = json.loads((d / "weeks/S01.json").read_text(encoding="utf-8"))
            w["recettes"] = w["recettes"][:4]
            w["ordre"] = [r["id"] for r in w["recettes"]]
            (d / "weeks/S01.json").write_text(json.dumps(w, ensure_ascii=False), encoding="utf-8")
            env = dict(os.environ, PYTHONIOENCODING="cp1252")
            for args in (("check-week", "S01"), ("render",)):
                with self.subTest(command=args[0]):
                    result = cli(d, *args, env=env)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    msgs = " ".join(i["msg"] for i in json.loads(result.stdout))
                    self.assertIn("≠", msgs)

    def test_csv_errors_survive_check_week_scope(self):
        with Workdir([week()]) as d:
            local_foods(d, {"oeuf": {"rendement": "0"}})
            result = cli(d, "check-week", "S01")
            self.assertEqual(result.returncode, 1)
            self.assertIn("foods_nombre", {i["code"] for i in json.loads(result.stdout)})

    def test_unreadable_input_returns_json_and_code_two(self):
        with Workdir([week()]) as d:
            (d / "profile.yaml").write_text("projet: [", encoding="utf-8")
            result = cli(d)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)[0]["code"], "entree_illisible")
            self.assertNotIn("Traceback", result.stderr)

    def test_internal_failure_has_distinct_code_and_valid_json(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("binder.analyse", side_effect=RuntimeError("test interne")), redirect_stdout(stdout), redirect_stderr(stderr):
            rc = binder.main(["check-all", "--dir", str(DEMO), "--json"])
        self.assertEqual(rc, 3)
        self.assertEqual(json.loads(stdout.getvalue())[0]["code"], "erreur_interne")
        self.assertIn("Traceback", stderr.getvalue())

    def test_ci_rejects_exception_even_with_exit_one(self):
        good = [{"level": "erreur", "where": where, "code": code} for where, code in EXPECTED]
        verify_result(subprocess.CompletedProcess([], 1, json.dumps(good), ""))
        for rc, output, error in [(1, "", "Traceback: crash"), (3, "[]", "Traceback"),
                                  (1, json.dumps(good), "Traceback: crash"), (0, "[]", "")]:
            with self.subTest(rc=rc, error=error), self.assertRaises(ValueError):
                verify_result(subprocess.CompletedProcess([], rc, output, error))

    def test_demo_pepper_in_steps_has_an_ingredient_line(self):
        for r in load_json(DEMO / "weeks/S01.json")["recettes"]:
            if any("poivr" in step.lower() for step in r["etapes"]):
                self.assertIn("poivre", {i["food"] for i in r["ingredients"]}, r["id"])


if __name__ == "__main__":
    unittest.main()
