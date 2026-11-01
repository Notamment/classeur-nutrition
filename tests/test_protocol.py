"""Le protocole ne confond pas préparations, exécutions et revues humaines."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from test_binder import ROOT
sys.path.insert(0, str(ROOT / "evals"))
from core import BinderError, load_yaml
from protocol import RUBRIC, prepare, evaluate, execute, summarize, import_human_review


def human_fixture():
    return {"version": 1, "relecteur": "fixture_sans_humain_reel", "notes": dict.fromkeys(RUBRIC, 3),
            "defauts_critiques": [], "commentaire": "Fixture de régression, pas une revue réelle"}


def producing_agent():
    from test_selection import basic
    week = {"semaine": "S01", "recettes": [basic()]}
    script = ("from pathlib import Path; Path('weeks').mkdir(exist_ok=True); "
              f"Path('weeks/S01.json').write_text({json.dumps(week)!r}, encoding='utf-8'); "
              f"Path('human.json').write_text({json.dumps(human_fixture())!r}, encoding='utf-8')")
    return [sys.executable, "-c", script]


class TestEvaluationProtocol(unittest.TestCase):
    def test_truncated_agent_logs_never_report_partial_token_totals(self):
        from runner import LOG_LIMIT
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runs"; prepare(root, repetitions=1, case_ids=["N10"])
            case = root / "N10-1"
            script = ('import os; os.write(1,b\'{"type":"turn.completed","usage":{"output_tokens":5}}\\n\'); '
                      f'os.write(1, b"x" * {LOG_LIMIT + 100})')
            execute(case, [sys.executable, "-c", script], "fixture", "fixture")
            run = json.loads((case / "run.json").read_text(encoding="utf-8"))
            self.assertTrue(run["journaux"]["stdout"]["tronque"])
            self.assertIsNone(run["tokens"])
            self.assertEqual((case / "agent.stdout.txt").stat().st_size, LOG_LIMIT)

    def test_agent_human_file_and_forged_evaluation_never_count_as_human(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runs"; prepare(root, repetitions=1, case_ids=["N10"])
            case = root / "N10-1"
            result = execute(case, producing_agent(), "fixture", "fixture")
            self.assertTrue(result["execution"]["recettes_produites"])
            self.assertIsNone(result["humain"])
            result["humain"] = human_fixture()
            (case / "evaluation.json").write_text(json.dumps(result), encoding="utf-8")
            self.assertEqual(summarize(root)["revues_humaines"], 0)
            self.assertIsNone(evaluate(case)["humain"])

    def test_human_import_requires_external_explicit_action_and_tracks_exact_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runs"; prepare(root, repetitions=1, case_ids=["N10"])
            case = root / "N10-1"
            execute(case, producing_agent(), "fixture", "fixture")
            reviews = Path(temp) / "reviews"
            external = Path(temp) / "human.json"
            external.write_text(json.dumps(human_fixture()), encoding="utf-8")
            for file, destination in ((case / "human.json", reviews), (external, root / "reviews")):
                with self.assertRaises(BinderError):
                    import_human_review(case, file, destination)
            import_human_review(case, external, reviews)
            self.assertEqual(summarize(root)["revues_humaines"], 0)
            self.assertEqual(summarize(root, reviews)["revues_humaines"], 1)
            self.assertEqual(evaluate(case, reviews)["humain"], human_fixture())
            self.assertIsNone(json.loads((case / "evaluation.json").read_text())["humain"])
            with self.assertRaises(BinderError):
                import_human_review(case, external, reviews)
            (case / "weeks/S01.json").write_text('{"semaine":"S01","recettes":[]}', encoding="utf-8")
            self.assertEqual(summarize(root, reviews)["revues_humaines"], 0)

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
