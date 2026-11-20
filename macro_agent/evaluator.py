from __future__ import annotations

from .common import digest
from .geometry import apply_moves, metrics


def evaluate(case, batch, target_ids):
    """Trusted host-side evaluator; never imports the generated module."""
    parent_id = digest(case)
    try:
        if not isinstance(batch, dict) or set(batch) != {"moves"}:
            raise ValueError("a candidate must contain exactly the moves field")
        moves = batch["moves"]
        if not isinstance(moves, list):
            raise ValueError("moves must be a list")
        if any(not isinstance(m, dict) or m.get("macro_id") not in target_ids for m in moves):
            raise ValueError("candidate moves outside the frozen ToolRequest scope")
        candidate = apply_moves(case, moves)
        before, after = metrics(case), metrics(candidate)
        improved = after["weighted_hpwl"] < before["weighted_hpwl"] - 1e-9
        record = {"parent_state_id": parent_id, "state_id": digest(candidate),
                  "legal": True, "improved": improved, "accepted": False,
                  "before": before, "after": after, "moves": moves,
                  "validation_level": "toy_geometry_and_macro_center_proxy"}
        return candidate, record
    except (ValueError, KeyError, TypeError) as exc:
        return None, {"parent_state_id": parent_id, "legal": False,
                      "accepted": False, "improved": False, "error": str(exc)}
