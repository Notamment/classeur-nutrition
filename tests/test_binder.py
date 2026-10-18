"""Tests des calculs et contrôles. Lancer : python -m unittest discover tests"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "meal-binder" / "scripts"))

from checks import analyse, check_profile  # noqa: E402
from core import load_foods, load_profile  # noqa: E402
from shopping import build_shopping, choose_packs  # noqa: E402

TEMPLATE = ROOT / "skills" / "meal-setup" / "assets" / "profile.v1.template.yaml"
DEMO = ROOT / "examples" / "demo"


def ing(food, qte, unite="g", etat=None, **kw):
    d = {"food": food, "qte": qte, "unite": unite}
    if etat:
        d["etat"] = etat
    d.update(kw)
    return d


def recipe(rid, ingredients, **kw):
    r = {"id": rid, "nom": rid, "ingredients": ingredients, "etapes": ["x"], "temps_total_min": 30,
         "gamelle": "x", "authenticite": "x", "sel_ajoute": False, "appareils": ["plaque"]}
    r.update(kw)
    return r


def filler(rid):
    """Recette végétarienne neutre : œufs + pommes de terre + citron."""
    return recipe(rid, [ing("oeuf", 6, "piece", "net"), ing("pomme_de_terre", 300, "g", "cru"),
                        ing("citron_jus", 10, "ml", "net")])


class Workdir:
    def __init__(self, weeks, semaines=1, repartition=(5, 0, 0), pantry=None, **profile_over):
        self.dir = Path(tempfile.mkdtemp())
        p = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
        p["projet"]["semaines"] = semaines
        p["projet"]["mois"] = ["octobre"]
        p["repartition"] = dict(zip(("vegetarien", "poisson", "viande"), repartition))
        p["repas"]["proteines_g_par_portion"] = [0, 999]
        p["repas"]["poids_servi_g_par_portion"] = [0, 9999]
        p["variete"]["feculents_distincts_min_par_semaine"] = 0
        for path, value in profile_over.items():
            node = p
            keys = path.split("__")
            for k in keys[:-1]:
                node = node[k]
            node[keys[-1]] = value
        (self.dir / "profile.yaml").write_text(yaml.safe_dump(p, allow_unicode=True), encoding="utf-8")
        (self.dir / "pantry.yaml").write_text(yaml.safe_dump({"stock": pantry or []}), encoding="utf-8")
        (self.dir / "weeks").mkdir()
        for w in weeks:
            (self.dir / "weeks" / f"{w['semaine']}.json").write_text(json.dumps(w), encoding="utf-8")

    def __enter__(self):
        return self.dir

    def __exit__(self, *exc):
        shutil.rmtree(self.dir)


def codes(ctx, where=None):
    return {i.code for i in ctx.issues if i.level == "erreur" and (where is None or i.where == where)}


class TestPacks(unittest.TestCase):
    def test_eggs(self):
        self.assertEqual(choose_packs(14, [6, 12]), (18.0, [12, 6]))

    def test_exact_combination(self):
        self.assertEqual(choose_packs(600, [150, 450]), (600.0, [450, 150]))

    def test_bulk_rounds_up(self):
        self.assertEqual(choose_packs(0.9, []), (1.0, []))

    def test_zero(self):
        self.assertEqual(choose_packs(0, [500]), (0.0, []))


class TestDemo(unittest.TestCase):
    """Valeurs recalculées à la main à partir de foods.csv (données provisoires)."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = analyse(DEMO, complete=True)

    def test_herring_recipe(self):
        rc = self.ctx.calcs["S01-R01"]
        # hareng 46,8 + skyr 15 + crème 1,68 + pomme 0,36 + oignon 1,2 + cornichons 0,36 + pdt 8 + beurre 0,07 + aneth 0,525
        self.assertAlmostEqual(rc.prot_pp, 73.995 / 2, places=2)
        self.assertAlmostEqual(rc.poids_pp, 1175 / 2, places=2)
        self.assertEqual(rc.categorie, "poisson")
        self.assertEqual(rc.especes_poisson, ["hareng"])

    def test_buckwheat_weight_uses_yields(self):
        # 130×2,5 + 350×0,6 + 120×0,7 + 60 + 10 + 15 + 200 + 150×0,9 + 100 + 10×1,03 + 15 + eau 80
        self.assertAlmostEqual(self.ctx.calcs["S01-R02"].poids_pp, 1244.3 / 2, places=2)

    def test_expected_errors(self):
        errs = {(i.where, i.code) for i in self.ctx.issues if i.level == "erreur"}
        self.assertEqual(errs, {("S01-R01", "poids_servi"), ("S01-R01", "duree"), ("S01-R02", "poids_servi"),
                                ("S01-R04", "poids_servi"), ("S01-R05", "fer_vitc")})

    def test_shopping_sums_and_stock(self):
        shops, stock, _ = build_shopping(self.ctx)
        lines = {sl.food.id: sl for sl in shops[0].lines}
        self.assertEqual(lines["oeuf"].besoin, 14)
        self.assertEqual(lines["oeuf"].achat, 18)
        self.assertEqual(lines["farine_ble"].mobilise, 150)
        self.assertEqual(lines["farine_ble"].achat, 0)
        self.assertFalse(lines["farine_ble"].sans_marge)        # 50 g restent en stock
        self.assertEqual(lines["beurre"].stock_statut, "inconnu")
        self.assertEqual(lines["beurre"].achat, 0)
        self.assertEqual(lines["beurre"].achat_si_insuffisant, 250)
        self.assertEqual(stock["kasza_sarrasin"], 370)
        for sl in shops[0].lines:                               # affectations = besoin
            self.assertAlmostEqual(sum(q for _, q, _ in sl.allocations), sl.besoin)


class TestRules(unittest.TestCase):
    def test_dry_legumes_cooked_weight(self):
        w = {"semaine": "S01", "cuisine": "Test", "recettes": [
            recipe("S01-R01", [ing("lentille_verte_seche", 95, "g", "sec"), ing("citron_jus", 10, "ml", "net")]),
            *[filler(f"S01-R0{i}") for i in range(2, 6)]]}
        with Workdir([w]) as d:
            ctx = analyse(d)
            self.assertAlmostEqual(ctx.calcs["S01-R01"].legumes_g_pp, 95 * 2.5 / 2)

    def test_consecutive_legumes(self):
        leg = lambda rid: recipe(rid, [ing("pois_chiche_egoutte", 200, "g", "egoutte"), ing("citron_jus", 10, "ml", "net")])
        w = {"semaine": "S01", "cuisine": "Test", "ordre": ["S01-R01", "S01-R02", "S01-R03", "S01-R04", "S01-R05"],
             "recettes": [leg("S01-R01"), leg("S01-R02"), *[filler(f"S01-R0{i}") for i in range(3, 6)]]}
        with Workdir([w]) as d:
            self.assertIn("legumineuses_consecutives", codes(analyse(d), "S01-R02"))

    def test_state_mismatch(self):
        w = {"semaine": "S01", "cuisine": "Test", "recettes": [
            recipe("S01-R01", [ing("lentille_verte_seche", 200, "g", "cuit")]),
            *[filler(f"S01-R0{i}") for i in range(2, 6)]]}
        with Workdir([w]) as d:
            self.assertIn("etat", codes(analyse(d), "S01-R01"))

    def test_mixed_category(self):
        w = {"semaine": "S01", "cuisine": "Test", "recettes": [
            recipe("S01-R01", [ing("poulet_cuisse", 200, "g", "cru"), ing("sardine", 100, "g", "cru")]),
            *[filler(f"S01-R0{i}") for i in range(2, 6)]]}
        with Workdir([w]) as d:
            self.assertIn("categorie_mixte", codes(analyse(d), "S01-R01"))

    def test_no_salt_with_feta(self):
        w = {"semaine": "S01", "cuisine": "Test", "recettes": [
            recipe("S01-R01", [ing("feta", 150, "g", "net"), ing("oeuf", 4, "piece", "net"),
                               ing("citron_jus", 10, "ml", "net")], sel_ajoute=True),
            *[filler(f"S01-R0{i}") for i in range(2, 6)]]}
        with Workdir([w]) as d:
            self.assertIn("sel", codes(analyse(d), "S01-R01"))

    def test_rice_limit(self):
        rice = lambda rid: recipe(rid, [ing("riz_basmati", 120, "g", "sec"), ing("oeuf", 4, "piece", "net"),
                                        ing("citron_jus", 10, "ml", "net")])
        w = {"semaine": "S01", "cuisine": "Test",
             "recettes": [rice(f"S01-R0{i}") for i in range(1, 4)] + [filler("S01-R04"), filler("S01-R05")]}
        with Workdir([w]) as d:
            self.assertIn("riz", codes(analyse(d), "S01"))

    def test_stock_carries_over_between_weeks(self):
        kasza = lambda rid: recipe(rid, [ing("kasza_sarrasin", 130, "g", "sec"), ing("oeuf", 4, "piece", "net"),
                                         ing("citron_jus", 10, "ml", "net")])
        weeks = [{"semaine": f"S0{n}", "cuisine": f"Test{n}",
                  "recettes": [kasza(f"S0{n}-R01")] + [filler(f"S0{n}-R0{i}") for i in range(2, 6)]} for n in (1, 2)]
        with Workdir(weeks, semaines=2, repartition=(10, 0, 0)) as d:
            shops, stock, _ = build_shopping(analyse(d, complete=True))
            w1 = {sl.food.id: sl for sl in shops[0].lines}["kasza_sarrasin"]
            w2 = {sl.food.id: sl for sl in shops[1].lines}["kasza_sarrasin"]
            self.assertEqual((w1.achat, w2.mobilise, w2.achat), (500, 130, 0))
            self.assertEqual(stock["kasza_sarrasin"], 240)

    def test_fish_species_unique(self):
        fish = lambda rid: recipe(rid, [ing("sardine", 300, "g", "cru"), ing("citron_jus", 10, "ml", "net")])
        weeks = [{"semaine": f"S0{n}", "cuisine": f"Test{n}",
                  "recettes": [fish(f"S0{n}-R01")] + [filler(f"S0{n}-R0{i}") for i in range(2, 6)]} for n in (1, 2)]
        with Workdir(weeks, semaines=2, repartition=(8, 2, 0)) as d:
            self.assertIn("espece_doublon", codes(analyse(d, complete=True), "S02-R01"))

    def test_profile_repartition(self):
        foods, _ = load_foods()
        p = load_profile(DEMO)
        p["repartition"]["viande"] = 1
        self.assertIn("repartition", {i.code for i in check_profile(p, foods)})


class TestPrompt(unittest.TestCase):
    def test_monolithic_prompt_has_no_script_instructions(self):
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "tools" / "build_prompt.py")], check=True, capture_output=True)
        text = (ROOT / "dist" / "prompt.md").read_text(encoding="utf-8")
        for word in ("binder.py", "check-plan", "JSON"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
