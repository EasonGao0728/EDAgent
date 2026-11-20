import copy
import json
from pathlib import Path
import tempfile
import unittest

from macro_agent.adapters.toy import load_case, validate_case
from macro_agent.common import digest, loads
from macro_agent.context_api import DesignContext
from macro_agent.controller import Controller, RunConfig
from macro_agent.evaluator import evaluate
from macro_agent.geometry import apply_moves, hpwl, metrics
from macro_agent.perception import observe, validate_plan
from macro_agent.synthesis import check_code

ROOT = Path(__file__).resolve().parents[1]


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case(ROOT / "cases/toy/connected_groups.json")

    def test_hand_calculated_baseline(self):
        # Eight weighted nets, independently hand-computed from the fixture.
        self.assertEqual(hpwl(self.case), 600 + 432 + 414 + 355 + 75 + 174 + 48 + 47)

    def test_nonzero_core_origin_preserves_geometry_and_hpwl(self):
        shifted = copy.deepcopy(self.case)
        for item in [shifted["core"], *shifted["macros"], *shifted["ports"]]:
            item["x"] += 10
            item["y"] += 20
        self.assertEqual(hpwl(validate_case(shifted)), 2145)
        apply_moves(shifted, [{"macro_id": "a", "x": 10, "y": 20}])

    def test_fixed_and_outside_and_overlap_rejected(self):
        for move in ({"macro_id": "hub", "x": 30, "y": 30},
                     {"macro_id": "a", "x": -1, "y": 0},
                     {"macro_id": "a", "x": 45, "y": 45}):
            with self.subTest(move=move), self.assertRaises(ValueError):
                apply_moves(self.case, [move])

    def test_atomic_swap_is_legal(self):
        swapped = apply_moves(self.case, [{"macro_id": "a", "x": 80, "y": 12},
                                          {"macro_id": "b", "x": 8, "y": 10}])
        self.assertEqual(swapped["macros"][1]["x"], 80)
        self.assertEqual(self.case["macros"][1]["x"], 8)

    def test_nonfinite_and_boolean_coordinates(self):
        for value in (float("nan"), float("inf"), True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                apply_moves(self.case, [{"macro_id": "a", "x": value, "y": 10}])

    def test_grid_spacing_orientation_and_duplicates(self):
        bad = [[{"macro_id": "a", "x": 8.5, "y": 10}],
               [{"macro_id": "a", "x": 34, "y": 45}],
               [{"macro_id": "a", "x": 8, "y": 10, "orientation": "R90"}],
               [{"macro_id": "a", "x": 8, "y": 10}] * 2]
        for moves in bad:
            with self.subTest(moves=moves), self.assertRaises(ValueError):
                apply_moves(self.case, moves)

    def test_blockages_are_enforced(self):
        case = load_case(ROOT / "cases/toy/blocked_channel.json")
        with self.assertRaises(ValueError):
            apply_moves(case, [{"macro_id": "small_1", "x": 46, "y": 3}])

    def test_evaluator_checks_scope_and_ignores_self_score(self):
        _, record = evaluate(self.case, {"moves": [{"macro_id": "b", "x": 60, "y": 10}]}, ["a"])
        self.assertFalse(record["legal"])
        _, record = evaluate(self.case, {"moves": [{"macro_id": "a", "x": 30, "y": 30}], "score": -999}, ["a"])
        self.assertFalse(record["legal"])

    def test_missing_physical_metrics_are_null(self):
        result = metrics(self.case)
        for key in ("power", "wns", "tns", "routing_overflow"):
            self.assertIsNone(result[key])

    def test_readonly_context_returns_copies(self):
        context = DesignContext(self.case)
        context.macros()[0]["x"] = -999
        self.assertEqual(context.macros()[0]["x"], 45)

    def test_unplaced_input_gets_deterministic_legal_initialization(self):
        raw = copy.deepcopy(self.case)
        raw["macros"][1].pop("x")
        raw["macros"][1].pop("y")
        first, second = validate_case(raw), validate_case(raw)
        self.assertEqual(first, second)

    def test_duplicate_json_and_nan_rejected(self):
        for text in ('{"a":1,"a":2}', '{"x":NaN}'):
            with self.assertRaises(ValueError):
                loads(text)

    def test_bad_net_node_rejected(self):
        self.case["nets"][0]["nodes"].append("unknown")
        with self.assertRaises(ValueError):
            validate_case(self.case)


class EvidenceTests(unittest.TestCase):
    def test_hallucinated_context_api_is_rejected_before_execution(self):
        with self.assertRaisesRegex(ValueError, "unsupported context.core"):
            check_code({"description": "bad API", "source": "def propose_moves(context, budget, rng):\n    return context.core()\n"})

    def test_stale_evidence_rejected(self):
        case = load_case(ROOT / "cases/toy/connected_groups.json")
        evidence = observe(case, {"tool": "query_report", "reason": "check", "macro_ids": [], "region": []}, "q1")
        case = apply_moves(case, [{"macro_id": "a", "x": 30, "y": 30}])
        plan = {"facts": [{"statement": "observed", "evidence_refs": ["q1"]}],
                "hypotheses": [], "unknowns": [], "tool_request": {}}
        with self.assertRaisesRegex(ValueError, "stale"):
            validate_plan(plan, case, [evidence], "r1")

    def test_unknown_query_objects_rejected(self):
        case = load_case(ROOT / "cases/toy/connected_groups.json")
        with self.assertRaises(ValueError):
            observe(case, {"tool": "query_connectivity", "reason": "check", "macro_ids": ["ghost"]}, "q")


class FixtureProvider:
    model = "explicit-test-fixture"
    is_test_fixture = True

    def generate(self, system, prompt, schema, seed):
        if "tool" in schema["properties"]:
            result = {"tool": "query_connectivity", "macro_ids": ["a"], "region": [], "reason": "check connections"}
        elif "facts" in schema["properties"]:
            result = {"facts": [{"statement": "a has a weighted connection to hub",
                                  "evidence_refs": [prompt["evidence"]["query_id"]]}],
                      "hypotheses": ["closer placement may help"], "unknowns": ["routing unavailable"],
                      "tool_request": {"problem": "reduce connection cost", "capability_gap": "local proposal",
                                       "requested_behavior": "move a legally", "target_macro_ids": ["a"]}}
        else:
            result = {"description": "TEST FIXTURE, not model discovery",
                      "source": "def propose_moves(context, budget, rng):\n    return []\n"}
        return result, {"provider": "test-fixture"}


class FixtureSandbox:
    def run(self, payload):
        return {"ok": True, "candidates": [
            {"moves": [{"macro_id": "a", "x": 30, "y": 30}]},
            {"moves": [{"macro_id": "hub", "x": 0, "y": 0}]}]}


class ControllerTests(unittest.TestCase):
    def test_requested_scope_is_available_inside_generated_program(self):
        class RecordingSandbox(FixtureSandbox):
            def run(self, payload):
                self.seen = payload
                return super().run(payload)
        sandbox = RecordingSandbox()
        case = load_case(ROOT / "cases/toy/connected_groups.json")
        with tempfile.TemporaryDirectory() as directory:
            Controller(case, FixtureProvider(), sandbox, Path(directory) / "run", RunConfig(max_rounds=1)).run()
            self.assertEqual(sandbox.seen["budget"]["target_macro_ids"], ["a"])

    def test_execution_traceback_is_preserved_for_model_repair(self):
        class BrokenSandbox:
            def run(self, payload):
                return {"ok": False, "error": "bad index", "traceback": "<generated_operator> line 59"}
        case = load_case(ROOT / "cases/toy/connected_groups.json")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            Controller(case, FixtureProvider(), BrokenSandbox(), output, RunConfig(max_rounds=1)).run()
            feedback = json.loads((output / "feedback/r01.json").read_text(encoding="utf-8"))
            self.assertIn("line 59", feedback["execution_details"]["traceback"])

    def test_end_to_end_records_and_external_acceptance(self):
        case = load_case(ROOT / "cases/toy/connected_groups.json")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            summary = Controller(case, FixtureProvider(), FixtureSandbox(), output, RunConfig(max_rounds=1)).run()
            self.assertEqual(summary["verified_tools"], 1)
            self.assertLess(summary["best"]["weighted_hpwl"], 2145)
            self.assertFalse(summary["llm_calls_are_real"])
            self.assertEqual(summary["evaluations"], 2)
            self.assertTrue((output / "report.html").exists())
            self.assertEqual(len(list((output / "evaluations").glob("*.json"))), 2)

    def test_model_budget_keeps_baseline(self):
        case = load_case(ROOT / "cases/toy/connected_groups.json")
        with tempfile.TemporaryDirectory() as directory:
            summary = Controller(case, FixtureProvider(), FixtureSandbox(), Path(directory) / "run",
                                 RunConfig(max_rounds=3, max_model_calls=1)).run()
            self.assertEqual(summary["model_calls"], 1)
            self.assertEqual(summary["evaluations"], 0)
            self.assertEqual(summary["best"], summary["baseline"])
            self.assertIn("budget", summary["stop_reason"])

    def test_provider_failure_stops_without_spending_remaining_calls(self):
        from macro_agent.openai_http import OpenAIError
        class UnavailableProvider:
            model = "explicit-unavailable-test-fixture"
            is_test_fixture = True
            def generate(self, *args):
                raise OpenAIError("subscription_sharing_usage_limit_exceeded")
        case = load_case(ROOT / "cases/toy/connected_groups.json")
        with tempfile.TemporaryDirectory() as directory:
            summary = Controller(case, UnavailableProvider(), FixtureSandbox(), Path(directory) / "run",
                                 RunConfig(max_rounds=3, max_model_calls=12)).run()
            self.assertEqual(summary["model_calls"], 1)
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["stop_reason"], "model provider failed")
            self.assertEqual(summary["best"], summary["baseline"])

    def test_all_invalid_candidates_preserve_baseline(self):
        class InvalidSandbox:
            def run(self, payload):
                return {"ok": True, "candidates": [{"moves": [{"macro_id": "a", "x": float('nan'), "y": 0}]}]}
        case = load_case(ROOT / "cases/toy/connected_groups.json")
        with tempfile.TemporaryDirectory() as directory:
            summary = Controller(case, FixtureProvider(), InvalidSandbox(), Path(directory) / "run",
                                 RunConfig(max_rounds=1)).run()
            self.assertEqual(summary["best"], summary["baseline"])
            self.assertEqual(summary["verified_tools"], 0)


if __name__ == "__main__":
    unittest.main()
