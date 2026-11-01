"""Livrables séparés : revue liée à la version, confidentialité, tableurs et HTML."""
import json
import unittest

from test_binder import filler
from test_profiles_v2 import workspace
from test_regressions import cli
from core import BinderError
from exports import export, table_csv
from workflow import record_review


class TestExports(unittest.TestCase):
    def test_served_components_are_reviewed_and_delivered_with_scaled_amounts_and_sources(self):
        from test_planning import schedule
        from test_selection import basic
        from test_sources import registry, source
        from workflow import review_status
        with workspace(recipes=[basic()]) as d:
            component = basic("pomme_de_terre") | {"nom": "Garniture de fixture", "etapes": ["ETAPE_COMPOSANT_UNIQUE"]}
            data = schedule(d, composants={"garniture": {"portions": 2, "recette": component}})
            data["services"][0]["plats"] = [{"composant": "garniture", "portions": 6, "preparation": "prep"},
                                            {"recette": "S01-R01", "portions": 4, "preparation": "prep"}]
            schedule(d, **data)
            registry(d, {"pomme_de_terre": source({}) | {"source": "https://example.invalid/source-composant"}})
            self.assertEqual(cli(d, "render").returncode, 0)
            document = d / "out/classeur.md"
            rendered = document.read_text(encoding="utf-8")
            self.assertIn("ETAPE_COMPOSANT_UNIQUE", rendered)
            self.assertIn("300 g", rendered)
            self.assertIn("source-composant", rendered)
            document.write_text(rendered.replace("ETAPE_COMPOSANT_UNIQUE", ""), encoding="utf-8")
            with self.assertRaises(BinderError):
                record_review(d, "fixture_humaine", "test technique")
            document.write_text(rendered, encoding="utf-8")
            record_review(d, "fixture_humaine", "test technique")
            for audience in ("client", "production"):
                export(d, audience=audience, formats=["html", "csv"])
                folder = d / "out/exports" / audience
                text = (folder / "classeur.html").read_text(encoding="utf-8")
                self.assertIn("ETAPE_COMPOSANT_UNIQUE", text)
                self.assertIn("source-composant", text)
                self.assertIn("6 portions", text)
                csv = (folder / "ingredients.csv").read_text(encoding="utf-8-sig")
                self.assertIn("midi/1,Garniture de fixture", csv)
                self.assertIn(",300.0,g,cru", csv)
                self.assertIn("midi/2", csv)
            data["composants"]["garniture"]["recette"]["etapes"] = ["Étape modifiée"]
            schedule(d, **data)
            self.assertFalse(review_status(d)["revue_actuelle"])
            with self.assertRaises(BinderError):
                export(d)

    def test_delivery_requires_current_review_and_draft_is_visible(self):
        with workspace() as d:
            with self.assertRaises(BinderError):
                export(d)
            export(d, draft=True)
            self.assertIn("BROUILLON", (d / "out/exports/client/classeur.html").read_text(encoding="utf-8"))
            cli(d, "render")
            record_review(d, "relecteur_test", "SECRET_NOTE")
            export(d)
            metadata = json.loads((d / "out/exports/client/manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(metadata["brouillon"])
            self.assertNotIn("profil_effectif", metadata)
            self.assertIn("classeur.html", metadata["fichiers"])
            (d / "profile.yaml").write_text("version: 2\n", encoding="utf-8")
            with self.assertRaises(BinderError):
                export(d)

    def test_client_html_escapes_text_and_excludes_internal_notes(self):
        r = filler("S01-R01"); r["nom"] = '<script>alert("test")</script>'
        with workspace(recipes=[r]) as d:
            cli(d, "render")
            record_review(d, "relecteur_test", "SECRET_NOTE")
            export(d, formats=["html", "csv"])
            text = (d / "out/exports/client/classeur.html").read_text(encoding="utf-8")
            self.assertNotIn("<script>", text)
            self.assertIn("&lt;script&gt;", text)
            self.assertNotIn("SECRET_NOTE", text)
            self.assertNotIn("Stock mobilisé", text)
            export(d, audience="production")
            production = (d / "out/exports/production/classeur.html").read_text(encoding="utf-8")
            self.assertIn("Stock mobilisé", production)
            self.assertIn("NON VÉRIFIÉ", production)

    def test_csv_neutralizes_formulas_even_after_whitespace(self):
        result = table_csv([["=2+2", " @cmd", "+2", "-2", "normal"]]).decode("utf-8-sig")
        self.assertEqual(result, "'=2+2,' @cmd,'+2,'-2,normal\n")

    def test_previous_formats_cannot_remain_silently_stale(self):
        with workspace() as d:
            export(d, formats=["html", "csv"], draft=True)
            with self.assertRaises(BinderError):
                export(d, formats=["html"], draft=True)

    def test_export_never_overwrites_unrecognized_folder(self):
        with workspace() as d:
            target = d / "out/exports/client"
            target.mkdir(parents=True)
            (target / "classeur.html").write_text("Mes notes", encoding="utf-8")
            with self.assertRaises(BinderError):
                export(d, draft=True)
            self.assertEqual((target / "classeur.html").read_text(encoding="utf-8"), "Mes notes")
