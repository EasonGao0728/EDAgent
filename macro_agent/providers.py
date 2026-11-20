from __future__ import annotations

import json
import time
import urllib.request
from urllib.parse import urlparse

from .common import loads


class OllamaProvider:
    """Actual local model calls, with schema-constrained output and recorded usage."""
    provider_name = "ollama"
    def __init__(self, model, endpoint="http://127.0.0.1:11434", timeout=180):
        if urlparse(endpoint).hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("v0.1 Ollama endpoint must be local")
        self.model, self.endpoint, self.timeout = model, endpoint.rstrip("/"), timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def generate(self, system, prompt, schema, seed):
        max_tokens = 2500 if "source" in schema.get("properties", {}) else (900 if "facts" in schema.get("properties", {}) else 300)
        body = {"model": self.model, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)
             + "\nReturn JSON matching: " + json.dumps(schema)}],
            "stream": False, "think": False, "format": schema,
            "options": {"temperature": 0.2, "seed": seed, "num_ctx": 8192, "num_predict": max_tokens},
            "keep_alive": "10m"}
        request = urllib.request.Request(self.endpoint + "/api/chat",
                    data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
        start = time.monotonic()
        with self.opener.open(request, timeout=self.timeout) as response:
            raw = loads(response.read().decode("utf-8"))
        content = raw.get("message", {}).get("content", "")
        usage = {"provider": "ollama", "model": raw.get("model", self.model),
                 "prompt_tokens": raw.get("prompt_eval_count"), "output_tokens": raw.get("eval_count"),
                 "wall_seconds": round(time.monotonic() - start, 4),
                 "done_reason": raw.get("done_reason"), "model_weights_trained": False}
        if not raw.get("done") or raw.get("done_reason") == "length":
            raise ValueError("model response incomplete or truncated")
        return loads(content), usage


def local_models(endpoint="http://127.0.0.1:11434"):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(endpoint.rstrip("/") + "/api/tags", timeout=3) as response:
        return [m["name"] for m in json.load(response).get("models", [])]
