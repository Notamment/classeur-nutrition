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
