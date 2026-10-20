"""Prix datés et composition : cohérence entre achats et sélection."""
import unittest

import yaml

from test_binder import codes
from test_profiles_v2 import workspace
from test_regressions import local_foods
from test_selection import basic, proposal
from checks import analyse, preference_counts
from core import DataError
from products import product_report
from selection import select_proposals, save_selection


def product(**changes):
    return {"reference": "test-fictif", "fournisseur": "fournisseur fictif", "source": "fixture",
            "observe_le": "2026-01-01", "prix_eur": 2, "prix_pour": 500, "unite": "g",
            "conditionnements": [500], "composition": {"statut": "documentee", "familles": [],
                "allergenes_presents": [], "traces_declarees": []}} | changes


def products(d, item, **changes):
    data = {"version": 1, "date_reference": "2026-01-15", "validite_jours": 30,
            "produits": {"carotte": item}} | changes
    (d / "products.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


class TestProducts(unittest.TestCase):
    def test_pack_price_is_normalized_and_selected_copy_keeps_it(self):
        with workspace({"budget": {"plafond_eur_semaine": 3}}, recipes=[basic()]) as d:
            products(d, product())
            proposal(d, "carottes", [basic()])
            result = select_proposals(d)
            self.assertEqual(result.chosen.foods["carotte"].prix_eur, 4)
            self.assertEqual(result.report["propositions"][0]["mesures"]["budget"], 2)
            target = save_selection(result, d)
            self.assertEqual(analyse(target).shops[0].montant_caisse, 2)
            self.assertEqual(product_report(target, analyse(target).foods)["produits"]["carotte"]["source"], "fixture")

    def test_stale_price_cannot_fall_back_to_undated_csv(self):
        with workspace({"budget": {"plafond_eur_semaine": 10}}, recipes=[basic()]) as d:
            local_foods(d, prices=True)
            products(d, product(), validite_jours=1)
            proposal(d, "carottes", [basic()])
            ctx = analyse(d)
            self.assertIsNone(ctx.foods["carotte"].prix_eur)
            self.assertTrue(any(i.code == "prix_perime" for i in ctx.issues))
            self.assertFalse(ctx.shops[0].budget_verifiable)
            self.assertIsNone(select_proposals(d).chosen)

    def test_future_price_and_incompatible_units_are_data_errors(self):
        for item in (product(observe_le="2027-01-01"), product(unite="piece")):
            with self.subTest(item=item), workspace() as d:
                products(d, item)
                with self.assertRaises(DataError):
                    analyse(d)

    def test_unknown_composition_blocks_exclusion_and_counts_uncertain_preference(self):
        unknown = product(composition={"statut": "inconnue", "familles": [], "allergenes_presents": [], "traces_declarees": []})
        with workspace({"aliments": {"familles_exclues": ["soja"]}}, recipes=[basic()]) as d:
            products(d, unknown)
            self.assertIn("famille_non_verifiable", codes(analyse(d)))
        with workspace({"aliments": {"familles_a_eviter": ["soja"]}}, recipes=[basic()]) as d:
            products(d, unknown)
            self.assertEqual(preference_counts(analyse(d)), (0, 1))

    def test_documented_derivative_is_checked_through_family_parents(self):
        with workspace({"aliments": {"familles_exclues": ["legumineuses"]}}, recipes=[basic()]) as d:
            products(d, product(composition={"statut": "documentee", "familles": ["soja"],
                "allergenes_presents": ["soja"], "traces_declarees": []}))
            self.assertIn("famille_exclue", codes(analyse(d)))
