"""Trusted worker copied into an OS sandbox. Never run generated code on the host."""
from __future__ import annotations

import ast
import json
import random
import sys
import traceback
from pathlib import Path

from context_api import DesignContext


def main():
    input_path, output_path = map(Path, sys.argv[1:3])
    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
        source = data["source"]
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                if any(n.split(".")[0] not in {"math", "random", "itertools", "statistics", "collections"}
                       for n in names):
                    raise ValueError("operator imports are limited to numerical standard-library modules")
        namespace = {}
        exec(compile(tree, "<generated_operator>", "exec"), namespace)
        func = namespace.get("propose_moves")
        if not callable(func):
            raise ValueError("missing callable propose_moves(context, budget, rng)")
        result = func(DesignContext(data["case"]), dict(data["budget"]), random.Random(data["seed"]))
        if not isinstance(result, list) or len(result) > data["budget"]["max_candidates"]:
            raise ValueError("return a list with at most budget['max_candidates'] batches")
        output = {"ok": True, "candidates": result}
        # Serialize before reporting success: catches NaN, generators and invalid object types.
        text = json.dumps(output, ensure_ascii=False, allow_nan=False)
        if len(text.encode("utf-8")) > 1024 * 1024:
            raise ValueError("operator output exceeds 1 MiB")
    except BaseException as exc:
        text = json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}",
                           "traceback": traceback.format_exc(limit=5)[-6000:]}, ensure_ascii=False)
    output_path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
