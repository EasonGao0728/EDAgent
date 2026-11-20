from __future__ import annotations

import copy

from .common import digest, require_text
from .context_api import DesignContext
from .geometry import number


QUERY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "tool": {"type": "string", "enum": ["query_connectivity", "query_region", "query_report"]},
        "macro_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "region": {"type": "array", "items": {"type": "number"}, "maxItems": 4},
        "reason": {"type": "string"}},
    "required": ["tool", "macro_ids", "region", "reason"]}

PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "facts": {"type": "array", "minItems": 1, "maxItems": 5,
                  "items": {"type": "object", "properties": {
                      "statement": {"type": "string"},
                      "evidence_refs": {"type": "array", "minItems": 1, "items": {"type": "string"}}},
                      "required": ["statement", "evidence_refs"], "additionalProperties": False}},
        "hypotheses": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "unknowns": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "tool_request": {"type": "object", "additionalProperties": False, "properties": {
            "problem": {"type": "string"}, "capability_gap": {"type": "string"},
            "requested_behavior": {"type": "string"},
            "target_macro_ids": {"type": "array", "minItems": 1, "maxItems": 12, "items": {"type": "string"}}},
            "required": ["problem", "capability_gap", "requested_behavior", "target_macro_ids"]}},
    "required": ["facts", "hypotheses", "unknowns", "tool_request"]}


def observe(case, request, query_id):
    tool = request.get("tool")
    require_text(request.get("reason"), "query reason")
    context = DesignContext(case)
    if tool == "query_connectivity":
        ids = request.get("macro_ids")
        valid = {m["id"] for m in case["macros"]}
        if not isinstance(ids, list) or not 1 <= len(ids) <= 12 or any(i not in valid for i in ids):
            raise ValueError("connectivity query needs known macro_ids")
        nets = context.nets(ids)
        related = {key for n in nets for key in n["nodes"]}
        data = {"macros": context.macros(list(related))[:20], "ports": context.ports()[:20],
                "nets": sorted(nets, key=lambda n: -n["weight"])[:20],
                "total_matching_nets": len(nets), "truncated": len(nets) > 20 or len(related) > 20}
    elif tool == "query_region":
        bounds = request.get("region")
        if not isinstance(bounds, list) or len(bounds) != 4 or not all(number(v) for v in bounds) or min(bounds[2:]) <= 0:
            raise ValueError("region must be [x,y,positive_width,positive_height]")
        found = context.region(bounds)
        data = {"region": bounds, "macros": found[:20], "total_matching_macros": len(found),
                "truncated": len(found) > 20, "blockages": copy.deepcopy(case.get("blockages", []))}
    elif tool == "query_report":
        data = context.summary()["metrics"]
    else:
        raise ValueError("unknown perception tool")
    return {"query_id": query_id, "case_id": case["case_id"], "state_id": digest(case),
            "tool": tool, "arguments": copy.deepcopy(request), "data": data,
            "provenance": "deterministic toy database query"}


def validate_plan(plan, case, evidence, round_id):
    state_id = digest(case)
    allowed_refs = {e["query_id"] for e in evidence if e["state_id"] == state_id}
    facts = plan.get("facts")
    if not isinstance(facts, list) or not 1 <= len(facts) <= 5:
        raise ValueError("plan needs 1..5 evidence-backed facts")
    for fact in facts:
        require_text(fact.get("statement"), "fact")
        refs = fact.get("evidence_refs")
        if not isinstance(refs, list) or not refs or any(r not in allowed_refs for r in refs):
            raise ValueError("fact references missing or stale evidence")
    for name in ("hypotheses", "unknowns"):
        if not isinstance(plan.get(name), list) or len(plan[name]) > 5:
            raise ValueError(f"invalid {name}")
        for text in plan[name]:
            require_text(text, name)
    request = copy.deepcopy(plan.get("tool_request", {}))
    for name in ("problem", "capability_gap", "requested_behavior"):
        require_text(request.get(name), name)
    ids = request.get("target_macro_ids")
    movable = {m["id"] for m in case["macros"] if not m["fixed"]}
    if not isinstance(ids, list) or not ids or len(ids) > 12 or len(set(ids)) != len(ids) or any(i not in movable for i in ids):
        raise ValueError("tool scope must contain distinct movable macros")
    insight_id = f"insight_{round_id}"
    insight = {"case_id": case["case_id"], "state_id": state_id, "insight_id": insight_id,
               "facts": facts, "hypotheses": [{"statement": h, "status": "untested"} for h in plan["hypotheses"]],
               "unknowns": plan["unknowns"],
               "interpretation_source": "model-authored; evidence references checked, semantic claims not automatically proven"}
    request.update(case_id=case["case_id"], state_id=state_id, insight_id=insight_id,
                   tool_request_id=f"request_{round_id}", interface_version="move_batch_v1",
                   evidence_refs=sorted({ref for fact in facts for ref in fact["evidence_refs"]}),
                   constraints_ref="contract.json", acceptance_ref="contract.json")
    return insight, request
