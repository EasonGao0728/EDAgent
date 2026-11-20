"""Read-only convenience API. OS isolation, not this class, is the security boundary."""
from __future__ import annotations

import copy

try:
    from .geometry import apply_moves, hpwl, metrics
except ImportError:  # Standalone copy in the AppContainer runtime.
    from geometry import apply_moves, hpwl, metrics


class DesignContext:
    def __init__(self, case):
        self._case = copy.deepcopy(case)

    def summary(self):
        c = self._case
        return {"case_id": c["case_id"], "core": copy.deepcopy(c["core"]),
                "grid": c["grid"], "min_spacing": c["min_spacing"], "units": c["units"],
                "macro_count": len(c["macros"]), "net_count": len(c["nets"]),
                "fixed_ids": [m["id"] for m in c["macros"] if m["fixed"]],
                "movable_ids": [m["id"] for m in c["macros"] if not m["fixed"]],
                "macro_area_fraction": sum(m["width"] * m["height"] for m in c["macros"])
                                       / (c["core"]["width"] * c["core"]["height"]),
                "blockages": copy.deepcopy(c.get("blockages", [])), "metrics": metrics(c)}

    def macros(self, ids=None):
        return copy.deepcopy([m for m in self._case["macros"] if ids is None or m["id"] in ids])

    def ports(self):
        return copy.deepcopy(self._case.get("ports", []))

    def nets(self, ids=None):
        return copy.deepcopy([n for n in self._case["nets"]
                              if ids is None or set(ids).intersection(n["nodes"])])

    def region(self, bounds):
        x, y, width, height = bounds
        return [m for m in self.macros() if m["x"] < x + width and m["y"] < y + height
                and m["x"] + m["width"] > x and m["y"] + m["height"] > y]

    def hpwl(self, moves):
        return hpwl(apply_moves(self._case, moves))

    def is_legal(self, moves):
        try:
            apply_moves(self._case, moves)
            return True
        except (ValueError, TypeError, KeyError):
            return False
