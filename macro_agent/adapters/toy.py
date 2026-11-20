from __future__ import annotations

import copy
import re

from ..common import read_json, require_text
from ..geometry import legality, number, rect_overlap


def load_case(path):
    return validate_case(read_json(path))


def validate_case(raw):
    case = copy.deepcopy(raw)
    if not isinstance(case, dict) or case.get("adapter") != "toy":
        raise ValueError("v0.1 requires adapter='toy'; real EDA results are not simulated")
    require_text(case.get("case_id"), "case_id", 80)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", case["case_id"]):
        raise ValueError("case_id must be a safe identifier")
    require_text(case.get("units"), "units", 40)
    core = case.get("core", {})
    if not all(number(core.get(k)) for k in ("x", "y", "width", "height")):
        raise ValueError("invalid core")
    if core["width"] <= 0 or core["height"] <= 0:
        raise ValueError("core dimensions must be positive")
    case.setdefault("grid", 1)
    case.setdefault("min_spacing", 0)
    if not number(case["grid"]) or case["grid"] <= 0:
        raise ValueError("invalid grid")
    if not number(case["min_spacing"]) or case["min_spacing"] < 0:
        raise ValueError("invalid spacing")
    macros = case.get("macros")
    if not isinstance(macros, list) or not 1 <= len(macros) <= 100:
        raise ValueError("toy adapter supports 1..100 macros")
    case.setdefault("ports", [])
    case.setdefault("blockages", [])
    ids = set()
    for m in macros:
        key = require_text(m.get("id"), "macro id", 80)
        if key in ids:
            raise ValueError(f"duplicate id: {key}")
        ids.add(key)
        if not all(number(m.get(k)) and m[k] > 0 for k in ("width", "height")):
            raise ValueError("invalid macro size")
        m.setdefault("fixed", False)
        if not isinstance(m["fixed"], bool):
            raise ValueError("fixed must be boolean")
        m.setdefault("orientation", "R0")
        m.setdefault("allowed_orientations", ["R0", "MX", "MY", "R180"])
        if (not isinstance(m["allowed_orientations"], list) or not m["allowed_orientations"]
                or any(o not in ("R0", "MX", "MY", "R180") for o in m["allowed_orientations"])):
            raise ValueError("unsupported orientation; 90-degree rotations are not implemented")
        if (m.get("x") is None) != (m.get("y") is None):
            raise ValueError("provide both x and y, or omit both")
        if m["fixed"] and m.get("x") is None:
            raise ValueError("fixed macros require positions")
    for p in case["ports"]:
        key = require_text(p.get("id"), "port id", 80)
        if key in ids or not number(p.get("x")) or not number(p.get("y")):
            raise ValueError("duplicate id or invalid port")
        ids.add(key)
    for b in case["blockages"]:
        if not all(number(b.get(k)) for k in ("x", "y", "width", "height")):
            raise ValueError("invalid blockage")
        if b["width"] <= 0 or b["height"] <= 0:
            raise ValueError("invalid blockage size")
    if not isinstance(case.get("nets"), list):
        raise ValueError("nets must be a list")
    net_ids = set()
    for net in case["nets"]:
        key = require_text(net.get("id"), "net id", 80)
        if key in net_ids:
            raise ValueError("duplicate net id")
        net_ids.add(key)
        nodes = net.get("nodes")
        if (not isinstance(nodes, list) or len(nodes) < 2 or len(set(nodes)) != len(nodes)
                or any(n not in ids for n in nodes)):
            raise ValueError("net nodes must be known, distinct identifiers")
        net.setdefault("weight", 1)
        if not number(net["weight"]) or net["weight"] <= 0:
            raise ValueError("net weight must be positive")
    # Deterministic teaching-only initialization when coordinates are absent.
    placed = [m for m in macros if m.get("x") is not None]
    probes = 0
    for m in sorted((m for m in macros if m.get("x") is None),
                    key=lambda m: -m["width"] * m["height"]):
        found = False
        grid = case["grid"]
        for row in range(int(core["height"] / grid) + 1):
            for col in range(int(core["width"] / grid) + 1):
                probes += 1
                if probes > 100000:
                    raise ValueError("toy initialization budget exhausted")
                m.update(x=core["x"] + col * grid, y=core["y"] + row * grid)
                if (m["x"] + m["width"] > core["x"] + core["width"]
                        or m["y"] + m["height"] > core["y"] + core["height"]):
                    continue
                if not any(rect_overlap(m, b, case["min_spacing"])
                           for b in placed + case["blockages"]):
                    found = True
                    break
            if found:
                break
        if not found:
            raise ValueError("no legal toy initialization found")
        placed.append(m)
    errors = legality(case)
    if errors:
        raise ValueError("invalid baseline: " + "; ".join(errors))
    return case
