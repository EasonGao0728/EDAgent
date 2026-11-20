"""Deterministic toy geometry. Units are abstract; pins are macro centers.

This module is also copied read-only into the sandbox Python runtime.
"""
from __future__ import annotations

import copy
import math


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def rect_overlap(a, b, gap=0):
    return (a["x"] < b["x"] + b["width"] + gap - 1e-9
            and b["x"] < a["x"] + a["width"] + gap - 1e-9
            and a["y"] < b["y"] + b["height"] + gap - 1e-9
            and b["y"] < a["y"] + a["height"] + gap - 1e-9)


def legality(case):
    errors = []
    core, gap, grid = case["core"], case["min_spacing"], case["grid"]
    macros = case["macros"]
    for m in macros:
        if not all(number(m.get(k)) for k in ("x", "y", "width", "height")):
            errors.append(f"non-finite or missing geometry: {m.get('id')}")
            continue
        if (m["x"] < core["x"] - 1e-9 or m["y"] < core["y"] - 1e-9
                or m["x"] + m["width"] > core["x"] + core["width"] + 1e-9
                or m["y"] + m["height"] > core["y"] + core["height"] + 1e-9):
            errors.append(f"outside core: {m['id']}")
        if m.get("orientation", "R0") not in m["allowed_orientations"]:
            errors.append(f"illegal orientation: {m['id']}")
        if any(abs((m[k] - core[k]) / grid - round((m[k] - core[k]) / grid)) > 1e-7
               for k in ("x", "y")):
            errors.append(f"off grid: {m['id']}")
    if errors:
        return errors
    for i, a in enumerate(macros):
        for b in macros[i + 1:]:
            if rect_overlap(a, b, gap):
                errors.append(f"overlap/spacing: {a['id']} / {b['id']}")
        for b in case.get("blockages", []):
            if rect_overlap(a, b, gap):
                errors.append(f"blocked area: {a['id']}")
    return errors


def apply_moves(case, moves):
    """Construct the ENTIRE final state before checking a joint swap."""
    if not isinstance(moves, list) or not moves or len(moves) > len(case["macros"]):
        raise ValueError("moves must be a non-empty bounded list")
    result = copy.deepcopy(case)
    by_id = {m["id"]: m for m in result["macros"]}
    seen = set()
    for move in moves:
        if not isinstance(move, dict) or set(move) - {"macro_id", "x", "y", "orientation"}:
            raise ValueError("invalid move fields")
        key = move.get("macro_id")
        if not isinstance(key, str) or key not in by_id or key in seen:
            raise ValueError(f"unknown or repeated macro: {key}")
        seen.add(key)
        m = by_id[key]
        if m["fixed"]:
            raise ValueError(f"fixed macro cannot be moved: {key}")
        if not number(move.get("x")) or not number(move.get("y")):
            raise ValueError("move coordinates must be finite numbers")
        m.update(x=move["x"], y=move["y"],
                 orientation=move.get("orientation", m["orientation"]))
    errors = legality(result)
    if errors:
        raise ValueError("; ".join(errors))
    return result


def hpwl(case):
    points = {m["id"]: (m["x"] + m["width"] / 2, m["y"] + m["height"] / 2)
              for m in case["macros"]}
    points.update({p["id"]: (p["x"], p["y"]) for p in case.get("ports", [])})
    total = 0.0
    for net in case["nets"]:
        coordinates = [points[key] for key in net["nodes"]]
        xs, ys = zip(*coordinates)
        total += net["weight"] * (max(xs) - min(xs) + max(ys) - min(ys))
    return total


def metrics(case):
    return {"stage": "toy_macro_center_proxy", "unit": case["units"],
            "weighted_hpwl": hpwl(case), "power": None, "wns": None,
            "tns": None, "routing_overflow": None,
            "unavailable_reason": "Toy adapter has no standard-cell, routing or timing flow"}
