from __future__ import annotations

import hashlib
from pathlib import Path

from .common import read_json, write_json


class RunStore:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=False)
        self.sequence = 0
        self.registry = []

    def save(self, relative, value):
        path = (self.directory / relative).resolve()
        if not path.is_relative_to(self.directory):
            raise ValueError("artifact path escapes run")
        write_json(path, value)
        return str(path)

    def event(self, kind, **values):
        import json
        self.sequence += 1
        event = {"sequence": self.sequence, "kind": kind, **values}
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")

    def register(self, artifact, evaluation):
        """A registry entry requires actual valid, improving execution evidence."""
        source = (self.directory / artifact["source_file"]).read_text(encoding="utf-8")
        if hashlib.sha256(source.encode("utf-8")).hexdigest() != artifact["source_sha256"]:
            raise ValueError("operator source integrity mismatch")
        if not evaluation.get("legal") or not evaluation.get("improved"):
            raise ValueError("cannot register an unverified operator")
        self.registry.append({**artifact, "evidence": evaluation})
        self.save("tool_registry.json", self.registry)

    def retrieve(self):
        # V0.1 retrieves verified tools from THIS run. Cross-design reuse is deferred.
        return [{"operator_id": r["operator_id"], "description": r["description"],
                 "source": (self.directory / r["source_file"]).read_text(encoding="utf-8"),
                 "scope": r["target_macro_ids"], "state_id": r["state_id"]}
                for r in self.registry[-2:]]
