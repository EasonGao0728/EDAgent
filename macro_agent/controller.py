from __future__ import annotations

import copy
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .common import digest, read_json, write_json
from .context_api import DesignContext
from .evaluator import evaluate
from .geometry import metrics
from .memory import RunStore
from .perception import PLAN_SCHEMA, QUERY_SCHEMA, observe, validate_plan
from .reporting import write_report
from .synthesis import CODE_SCHEMA, OPERATOR_API, check_code


@dataclass(frozen=True)
class RunConfig:
    max_rounds: int = 3
    max_evaluations: int = 12
    max_model_calls: int = 12
    candidates_per_operator: int = 4
    seed: int = 7

    def __post_init__(self):
        for key in ("max_rounds", "max_evaluations", "max_model_calls", "candidates_per_operator"):
            value = getattr(self, key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 1000:
                raise ValueError(f"invalid budget: {key}")


class BudgetExhausted(Exception):
    pass


class OperatorExecutionError(ValueError):
    def __init__(self, result):
        super().__init__(result.get("error", "invalid operator output"))
        self.details = {k: result[k] for k in ("error", "traceback", "elapsed_seconds") if k in result}


class Controller:
    def __init__(self, case, provider, sandbox, directory, config=None):
        self.baseline = copy.deepcopy(case)
        self.best = copy.deepcopy(case)
        self.provider, self.sandbox = provider, sandbox
        self.config = config or RunConfig()
        self.store = RunStore(directory)
        self.counts = {"model_calls": 0, "evaluations": 0, "operator_versions": 0,
                       "design_queries": 0, "operator_executions": 0, "legal_candidates": 0}
        self.usage, self.rounds, self.feedback = [], [], []
        self.last_source = ""
        self.contract = {"case_id": case["case_id"], "initial_state_id": digest(case),
                         "adapter": "toy", "interface_version": "move_batch_v1",
                         "budget": asdict(self.config), "acceptance": "legal and strictly lower weighted_hpwl",
                         "evaluation_stage": "toy_macro_center_proxy", "units": case["units"],
                         "constraints": {"core": case["core"], "min_spacing": case["min_spacing"],
                                         "grid": case["grid"], "fixed_macros": [m for m in case["macros"] if m["fixed"]]},
                         "model": getattr(provider, "model", "test-fixture"),
                         "provider": getattr(provider, "provider_name", "test-fixture"),
                         "sandbox": "windows_appcontainer"}
        self.contract_hash = digest(self.contract)

    def _check_contract(self):
        if digest(read_json(self.store.directory / "contract.json")) != self.contract_hash:
            raise RuntimeError("frozen contract integrity violation")

    def _ask(self, label, system, prompt, schema):
        if self.counts["model_calls"] >= self.config.max_model_calls:
            raise BudgetExhausted("model-call budget exhausted")
        self.counts["model_calls"] += 1
        call_id = f"call_{self.counts['model_calls']:03d}"
        self.store.save(f"model/{call_id}_request.json", {"phase": label, "system": system,
                         "prompt": prompt, "schema": schema, "seed": self.config.seed + self.counts["model_calls"]})
        print(f"[{label}] model request {self.counts['model_calls']}", flush=True)
        start = time.monotonic()
        try:
            result, usage = self.provider.generate(system, prompt, schema,
                                                   self.config.seed + self.counts["model_calls"])
        except Exception as exc:
            usage = {"provider": "failed_request", "wall_seconds": round(time.monotonic() - start, 4),
                     "prompt_tokens": None, "output_tokens": None, "error": str(exc)}
            self.usage.append(usage)
            self.store.save(f"model/{call_id}_response.json", {"error": str(exc), "usage": usage})
            raise
        self.usage.append(usage)
        self.store.save(f"model/{call_id}_response.json", {"response": result, "usage": usage})
        self._check_contract()
        if not isinstance(result, dict):
            raise ValueError("model must return a JSON object")
        return result

    def run(self):
        started = time.monotonic()
        self.store.save("contract.json", self.contract)
        self.store.save("baseline/case.json", self.baseline)
        self.store.save("baseline/metrics.json", metrics(self.baseline))
        self.store.save("best_case.json", self.best)
        self.store.save("tool_registry.json", [])
        stop, fatal = "round budget exhausted", None
        try:
            for round_number in range(1, self.config.max_rounds + 1):
                if self.counts["evaluations"] >= self.config.max_evaluations:
                    stop = "candidate-evaluation budget exhausted"
                    break
                round_id = f"r{round_number:02d}"
                record = {"round": round_number, "parent_state_id": digest(self.best)}
                self.rounds.append(record)
                summary = DesignContext(self.best).summary()
                if not summary["movable_ids"]:
                    stop = "no movable macros"
                    break
                self.store.save(f"states/{digest(self.best)}.json", self.best)
                try:
                    query = self._ask(round_id + ".inspect",
                        "You inspect a chip macro-layout teaching database. Choose ONE useful query from actual state. "
                        "Do not invent report values. Connectivity and region queries return geometry. Use English concise explanations.",
                        {"summary": summary, "last_feedback": self.feedback[-2:],
                         "available_tools": {"query_connectivity": "set macro_ids to 1..12 known macro identifiers; region=[]",
                            "query_region": "set region=[x,y,width,height]; macro_ids=[]",
                            "query_report": "returns available stage metrics only; both arrays=[]"}}, QUERY_SCHEMA)
                    evidence = observe(self.best, query, f"q_{round_id}")
                    self.counts["design_queries"] += 1
                    self.store.save(f"queries/{round_id}.json", evidence)
                    self.store.event("query", **evidence)
                    plan = self._ask(round_id + ".diagnose",
                        "Diagnose the current design from measured evidence. Separate facts from hypotheses. "
                        "Every fact MUST cite the supplied exact query_id. Identify a capability gap and request a new executable "
                        "local-move/search operator tailored to this design. Never claim routing or timing quality from HPWL. "
                        "Target only distinct movable macro ids. Respond with concise English.",
                        {"summary": summary, "evidence": evidence, "last_feedback": self.feedback[-2:],
                         "verified_tools": [{"operator_id": x["operator_id"], "description": x["description"]}
                                            for x in self.store.retrieve()]}, PLAN_SCHEMA)
                    insight, request = validate_plan(plan, self.best, [evidence], round_id)
                    record["problem"] = request["problem"]
                    self.store.save(f"insights/{round_id}.json", insight)
                    self.store.save(f"tool_requests/{round_id}.json", request)
                    self.store.event("tool_request", **request)
                    slots = min(self.config.candidates_per_operator,
                                self.config.max_evaluations - self.counts["evaluations"])
                    generated = self._ask(round_id + ".generate", OPERATOR_API,
                        {"task": "Write the complete runnable Python function now. The source field must contain Python code, never an interface identifier.",
                         "tool_request": {k: request[k] for k in ("problem", "capability_gap", "requested_behavior", "target_macro_ids")},
                         "summary": summary, "evidence": evidence,
                         "budget": {"max_candidates": slots, "target_macro_ids": request["target_macro_ids"]},
                         "feedback": self.feedback[-2:],
                         "previous_source": self.last_source[-12000:], "verified_tools": self.store.retrieve()}, CODE_SCHEMA)
                    self.counts["operator_versions"] += 1
                    operator_dir = self.store.directory / "operators" / round_id
                    operator_dir.mkdir(parents=True)
                    self.last_source = str(generated.get("source", ""))
                    (operator_dir / "operator.py").write_text(self.last_source, encoding="utf-8")
                    source, source_hash = check_code(generated)
                    artifact = {"operator_id": round_id, "case_id": self.best["case_id"],
                                "state_id": digest(self.best), "tool_request_id": request["tool_request_id"],
                                "description": generated["description"], "source_sha256": source_hash,
                                "source_file": f"operators/{round_id}/operator.py",
                                "target_macro_ids": request["target_macro_ids"],
                                "change_type": "model_generated_logic_not_a_claim_of_academic_novelty",
                                "parent_operator_id": f"r{round_number-1:02d}" if round_number > 1 else None}
                    self.store.save(f"operators/{round_id}/artifact.json", artifact)
                    print(f"[{round_id}.execute] running generated operator in AppContainer", flush=True)
                    execution = self.sandbox.run({"case": self.best, "source": source,
                                 "budget": {"max_candidates": slots, "target_macro_ids": request["target_macro_ids"]},
                                 "seed": self.config.seed + round_number})
                    self.counts["operator_executions"] += 1
                    self.store.save(f"operators/{round_id}/execution.json", execution)
                    self._check_contract()
                    candidates = execution.get("candidates")
                    if execution.get("ok") is not True or not isinstance(candidates, list) or len(candidates) > slots:
                        raise OperatorExecutionError(execution)
                    evaluations, selected, selected_record = [], None, None
                    for index, batch in enumerate(candidates):
                        self.counts["evaluations"] += 1
                        candidate, evaluation = evaluate(self.best, batch, request["target_macro_ids"])
                        evaluation.update(operator_id=round_id, case_id=self.best["case_id"],
                                          evaluation_id=f"eval_{self.counts['evaluations']:03d}", candidate_index=index)
                        evaluations.append(evaluation)
                        if evaluation["legal"]:
                            self.counts["legal_candidates"] += 1
                        if evaluation.get("improved") and (selected_record is None or
                                evaluation["after"]["weighted_hpwl"] < selected_record["after"]["weighted_hpwl"]):
                            selected, selected_record = candidate, evaluation
                    if selected is not None:
                        selected_record["accepted"] = True
                        self.best = selected
                        self.store.register(artifact, selected_record)
                    for evaluation in evaluations:
                        self.store.save(f"evaluations/{evaluation['evaluation_id']}.json", evaluation)
                        self.store.event("evaluation", **evaluation)
                    feedback = {"round": round_number, "operator_id": round_id,
                                "selected": selected_record, "candidate_count": len(evaluations),
                                "errors": [e["error"] for e in evaluations if not e["legal"]][:4],
                                "best_metrics": metrics(self.best),
                                "action": "revise diagnosis or search logic using actual feedback"}
                except BudgetExhausted:
                    stop = "model-call budget exhausted"
                    record["feedback"] = {"error": stop}
                    break
                except Exception as exc:
                    feedback = {"round": round_number, "error": f"{type(exc).__name__}: {exc}",
                                "action": "repair the tool or revise the evidence-based diagnosis"}
                    if getattr(exc, "abort_run", False):
                        stop, fatal = "model provider failed", feedback["error"]
                        feedback["action"] = "resolve model authorization, service, or transport failure before retrying"
                    if isinstance(exc, OperatorExecutionError):
                        feedback["execution_details"] = exc.details
                record["feedback"] = feedback
                self.feedback.append(feedback)
                self.store.save(f"feedback/{round_id}.json", feedback)
                self.store.event("feedback", **feedback)
                self.store.save("best_case.json", self.best)
                self.store.save("progress.json", {"round": round_number, **self.counts,
                                "best_metrics": metrics(self.best), "last_feedback": feedback})
                print(f"[{round_id}.review] best weighted HPWL={metrics(self.best)['weighted_hpwl']:g}; "
                      f"feedback={feedback.get('error', 'measured')}", flush=True)
                if fatal:
                    break
        except Exception as exc:
            stop, fatal = "host execution failed", f"{type(exc).__name__}: {exc}"
        summary = {"status": "failed" if fatal else "completed", "stop_reason": stop,
                   "error": fatal, "case_id": self.best["case_id"], "model": self.contract["model"],
                   "baseline": metrics(self.baseline), "best": metrics(self.best),
                   **self.counts, "verified_tools": len(self.store.registry),
                   "completed_feedback_rounds": len(self.feedback),
                   "functional_path_completed": bool(self.counts["design_queries"] and
                       self.counts["operator_executions"] and self.counts["legal_candidates"] and len(self.feedback) >= 2),
                   "model_usage": self.usage, "wall_seconds": round(time.monotonic() - started, 3),
                   "validation_level": "toy_geometry_and_macro_center_proxy",
                   "llm_calls_are_real": getattr(self.provider, "is_test_fixture", False) is False,
                   "output_directory": str(self.store.directory)}
        self.store.save("best_case.json", self.best)
        self.store.save("run_summary.json", summary)
        write_report(self.store.directory, self.baseline, self.best, summary, self.rounds)
        return summary
