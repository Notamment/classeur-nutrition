"""Le protocole ne confond pas préparations, exécutions et revues humaines."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from test_binder import ROOT
sys.path.insert(0, str(ROOT / "evals"))
from core import BinderError, load_yaml
from protocol import prepare, evaluate, execute, summarize


class TestEvaluationProtocol(unittest.TestCase):
    def test_corpus_has_twelve_cases_per_profession_and_prepares_no_scores(self):
        cases = load_yaml(ROOT / "evals/corpus.yaml")["cas"]
        self.assertEqual(sum(c["metier"] == "nutrition" for c in cases), 12)
        self.assertEqual(sum(c["metier"] == "restauration" for c in cases), 12)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runs"
            result = prepare(root)
            self.assertEqual(result["generations_preparees"], 72)
            self.assertEqual(result["generations_executees"], 0)
            self.assertFalse(list(root.rglob("evaluation.json")))
            self.assertEqual(summarize(root)["revues_humaines"], 0)
            with self.assertRaises(BinderError):
                evaluate(root / "N01-1")

    def test_failed_fixture_agent_is_recorded_without_fabricated_human_or_cost(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runs"; prepare(root, repetitions=1)
            case = root / "N01-1"
            result = execute(case, [sys.executable, "-c", "raise SystemExit(7)"], "fixture-test", "fixture-test")
            self.assertIsNone(result["automatique"])
            self.assertIsNone(result["humain"])
            self.assertIsNone(result["cout_eur"])
            self.assertEqual(summarize(root)["tentatives_lancees"], 1)
            self.assertEqual(summarize(root)["generations_produites"], 0)
            with self.assertRaises(BinderError):
                execute(case, [sys.executable, "-c", "pass"], "fixture-test", "fixture-test")

    def test_agent_editing_imposed_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runs"; prepare(root, repetitions=1)
            case = root / "N01-1"
            command = [sys.executable, "-c", "from pathlib import Path; Path('profile.yaml').write_text('version: 2', encoding='utf-8')"]
            with self.assertRaises(BinderError):
                execute(case, command, "fixture-test", "fixture-test")
            self.assertFalse((case / "evaluation.json").exists())

    def test_added_price_override_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runs"; prepare(root, repetitions=1, case_ids=["N10"])
            case = root / "N10-1"
            (case / "products.yaml").write_text("version: 1", encoding="utf-8")
            with self.assertRaises(BinderError):
                execute(case, [sys.executable, "-c", "raise RuntimeError('must not run')"], "fixture-test", "fixture-test")
            self.assertFalse((case / "agent.stdout.txt").exists())

    def test_portable_skill_changes_are_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runs"; prepare(root, repetitions=1, case_ids=["N10"])
            (root / "runtime/SKILL.md").write_text("Instructions modifiées", encoding="utf-8")
            with self.assertRaises(BinderError):
                execute(root / "N10-1", [sys.executable, "-c", "pass"], "fixture-test", "fixture-test")

    def test_missing_agent_is_a_recorded_startup_failure_not_a_score(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runs"; prepare(root, repetitions=1, case_ids=["N10"])
            result = execute(root / "N10-1", [str(root / "agent_absent")], "fixture-test", "fixture-test")
            self.assertEqual(result["execution"]["code_agent"], 127)
            self.assertIsNone(result["automatique"])
            self.assertIsNone(result["humain"])
