"""ChatGPT-authorized Responses API adapter for the existing three-stage controller."""
from __future__ import annotations

import copy
import json
import time

from .chatgpt_auth import ChatGPTAuth
from .common import loads
from .openai_http import API, OpenAIError, OpenAIHTTP, remote_code


def portable_schema(value):
    """Keep shape strict; value constraints remain in the prompt and host validators.

    Pattern/length/range constraints are not accepted by every reasoning model.
    Only transform actual schema nodes (never fields named e.g. 'pattern').
    """
    result = copy.deepcopy(value)
    for key in ("minLength", "maxLength", "pattern", "format", "minimum", "maximum",
                "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minItems", "maxItems", "uniqueItems"):
        result.pop(key, None)
    if "properties" in result:
        result["properties"] = {key: portable_schema(schema) for key, schema in result["properties"].items()}
        result["required"] = list(result["properties"])
        result["additionalProperties"] = False
    if isinstance(result.get("items"), dict):
        result["items"] = portable_schema(result["items"])
    for keyword in ("anyOf", "oneOf", "allOf"):
        if keyword in result:
            result[keyword] = [portable_schema(schema) for schema in result[keyword]]
    return result


def completed_response(response, timeout=180, max_bytes=4 * 1024 * 1024):
    """Parse bounded SSE and require the successful terminal event, not just text."""
    deadline, total, lines = time.monotonic() + timeout, 0, []
    done_items, done_parts = {}, {}
    while True:
        try:
            raw = response.readline(512 * 1024 + 1)
        except (OSError, TimeoutError):
            raise OpenAIError("stream_interrupted") from None
        if time.monotonic() >= deadline:
            raise OpenAIError("stream_timeout")
        if not raw:
            raise OpenAIError("stream_ended_without_completion")
        total += len(raw)
        if total > max_bytes or len(raw) > 512 * 1024:
            raise OpenAIError("stream_too_large")
        try:
            line = raw.decode("utf-8").rstrip("\r\n")
        except UnicodeError:
            raise OpenAIError("invalid_stream_encoding") from None
        if line:
            if line.startswith("data:"):
                lines.append(line[5:].lstrip(" "))
            continue
        if not lines:
            continue
        text, lines = "\n".join(lines), []
        if text == "[DONE]":
            raise OpenAIError("stream_ended_without_completion")
        try:
            event = loads(text)
            kind = event["type"]
        except (ValueError, TypeError, KeyError):
            raise OpenAIError("invalid_stream_event") from None
        if kind == "response.completed":
            result = event.get("response", {})
            if result.get("status") != "completed":
                raise OpenAIError("invalid_completion_status")
            # store=false streams can omit the assembled output in the terminal
            # response. Rebuild from completed items/parts, never text deltas alone.
            if not result.get("output"):
                output = []
                indices = set(done_items) | {index for index, _ in done_parts}
                for index in sorted(indices):
                    item = dict(done_items.get(index, {"type": "message"}))
                    parts = [part for (output_index, _), part in sorted(done_parts.items()) if output_index == index]
                    if parts:
                        item["content"] = parts
                    output.append(item)
                result = {**result, "output": output}
            return result
        if kind in {"response.failed", "response.incomplete", "error"}:
            error = event.get("response", {}).get("error") or event.get("error") or event
            code = error.get("code") if isinstance(error, dict) else None
            raise OpenAIError(remote_code(code) if isinstance(code, str) else kind.replace(".", "_"))
        if kind == "response.output_item.done" and isinstance(event.get("item"), dict):
            done_items[event["output_index"]] = event["item"]
        elif kind == "response.content_part.done" and isinstance(event.get("part"), dict):
            done_parts[(event["output_index"], event["content_index"])] = event["part"]
        elif kind == "response.output_text.done" and isinstance(event.get("text"), str):
            done_parts[(event["output_index"], event["content_index"])] = {"type": "output_text", "text": event["text"]}
        elif kind == "response.refusal.done":
            done_parts[(event["output_index"], event["content_index"])] = {"type": "refusal"}


def response_text(response):
    texts = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "refusal":
                raise OpenAIError("model_refusal")
            if content.get("type") == "output_text":
                texts.append(content.get("text", ""))
    if not texts:
        raise OpenAIError("empty_model_output")
    return "".join(texts)


class ChatGPTProvider:
    provider_name = "chatgpt"

    def __init__(self, model=None, *, auth=None, http=None, timeout=180):
        self.http, self.timeout = http or OpenAIHTTP(timeout), timeout
        self.auth = auth or ChatGPTAuth(http=self.http)
        self.model = model

    def models(self):
        result = self.http.json(API + "/models", token=self.auth.access_token())
        catalog = result.get("models")
        if not isinstance(catalog, list):
            raise OpenAIError("invalid_model_catalog")
        return [{"slug": item["slug"], "display_name": item.get("display_name", item["slug"])}
                for item in catalog if item.get("visibility") == "list" and isinstance(item.get("slug"), str)]

    def resolve_model(self):
        models = self.models()
        if not models:
            raise OpenAIError("no_models_available_for_account")
        if self.model is None:
            self.model = models[0]["slug"]  # Preserve the account catalog's default ordering.
        if self.model not in {item["slug"] for item in models}:
            raise OpenAIError("model_not_available_for_account")
        return self.model

    def generate(self, system, prompt, schema, seed, reasoning_effort=None):
        if self.model is None:
            self.resolve_model()
        body = {"model": self.model, "instructions": system,
                "input": [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)
                           + "\nReturn a concise JSON object matching: " + json.dumps(schema)}],
                "store": False, "stream": True,
                "text": {"format": {"type": "json_schema", "name": "macro_agent_result", "strict": True,
                                    "schema": portable_schema(schema)}}}
        if reasoning_effort is not None:
            if reasoning_effort not in ('low','medium','high','xhigh','max'):
                raise ValueError('unsupported reasoning effort')
            body['reasoning']={'effort':reasoning_effort}
        start = time.monotonic()
        with self.http.open(API + "/responses", token=self.auth.access_token(), body=body, stream=True) as stream:
            content_type = stream.headers.get("Content-Type")
            # Some HTTP intermediaries omit this header; validate the actual SSE
            # framing and terminal event in all cases instead of trusting a header.
            if content_type and "text/event-stream" not in content_type.lower():
                raise OpenAIError("expected_sse_response")
            response = completed_response(stream, self.timeout)
        try:
            result = loads(response_text(response))
            if not isinstance(result, dict):
                raise ValueError()
        except ValueError:
            raise OpenAIError("invalid_model_json") from None
        usage = response.get("usage") or {}
        return result, {"provider": "chatgpt", "auth_mode": "official_oauth", "model": response.get("model", self.model),
                        "prompt_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                        "total_tokens": usage.get("total_tokens"), "wall_seconds": round(time.monotonic() - start, 4),
                        "done_reason": "completed", "seed_applied": False, "model_weights_trained": False}
