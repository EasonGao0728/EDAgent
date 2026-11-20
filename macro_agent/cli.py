from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import uuid

from .adapters.toy import load_case
from .common import read_json
from .controller import Controller, RunConfig
from .providers import OllamaProvider, local_models
from .reporting import write_report
from .windows_sandbox import WindowsSandbox


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Macro Agent: Ollama or ChatGPT + isolated generated Python + toy evaluation")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check local model and Windows execution environment")
    auth = sub.add_parser("auth", help="independent official ChatGPT authorization")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    login = auth_sub.add_parser("login", help="Continue with ChatGPT in the system browser")
    login.add_argument("--new-account", action="store_true")
    login.add_argument("--profile")
    login.add_argument("--timeout", type=int, default=600)
    auth_sub.add_parser("status", help="show account status without printing tokens")
    logout = auth_sub.add_parser("logout", help="revoke and remove selected account credentials")
    logout.add_argument("--profile")
    select = auth_sub.add_parser("use", help="select a saved ChatGPT account")
    select.add_argument("profile")
    models = sub.add_parser("models", help="list currently available models")
    models.add_argument("--provider", choices=["ollama", "chatgpt"], default="chatgpt")
    models.add_argument("--profile")
    smoke = sub.add_parser("smoke", help="one small real ChatGPT request; no generated code execution")
    smoke.add_argument("--model")
    smoke.add_argument("--profile")
    report = sub.add_parser("report", help="re-render recorded results without any model or operator execution")
    report.add_argument("directory", type=Path)
    run = sub.add_parser("run", help="run an actual model-driven optimization loop")
    run.add_argument("--case", type=Path, default=root / "cases/toy/connected_groups.json")
    run.add_argument("--provider", choices=["ollama", "chatgpt"], default="ollama")
    run.add_argument("--model")
    run.add_argument("--profile")
    run.add_argument("--endpoint", default="http://127.0.0.1:11434")
    run.add_argument("--output", type=Path)
    run.add_argument("--max-rounds", type=int, default=3)
    run.add_argument("--max-evaluations", type=int, default=12)
    run.add_argument("--max-model-calls", type=int, default=12)
    run.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    try:
        return execute(args, root)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 1


def chatgpt_provider(args):
    from .chatgpt_auth import ChatGPTAuth
    from .chatgpt_provider import ChatGPTProvider
    provider = ChatGPTProvider(getattr(args, "model", None) or os.environ.get("MACRO_AGENT_CHATGPT_MODEL"),
                               auth=ChatGPTAuth(profile=getattr(args, "profile", None)))
    return provider


def execute(args, root):
    if args.command == "auth":
        from .chatgpt_auth import ChatGPTAuth
        client = ChatGPTAuth(profile=getattr(args, "profile", None))
        if args.auth_command == "login":
            if not 1 <= args.timeout <= 600:
                raise ValueError("--timeout must be between 1 and 600 seconds")
            result = client.login(new_account=args.new_account, timeout=args.timeout)
        elif args.auth_command == "logout":
            result = client.logout()
        elif args.auth_command == "use":
            client.select(args.profile)
            result = client.status()
        else:
            result = client.status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "models":
        result = chatgpt_provider(args).models() if args.provider == "chatgpt" else local_models()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "smoke":
        provider = chatgpt_provider(args)
        provider.resolve_model()
        result, usage = provider.generate("Return the requested JSON only.", {"task": "Set ok to true."},
            {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}, 0)
        if result != {"ok": True}:
            raise ValueError("smoke response did not match the expected result")
        print(json.dumps({"result": result, "usage": usage}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "report":
        directory = args.directory.resolve()
        summary = read_json(directory / "run_summary.json")
        records = []
        for path in sorted((directory / "feedback").glob("*.json")):
            request_path = directory / "tool_requests" / path.name
            request = read_json(request_path) if request_path.exists() else {}
            feedback = read_json(path)
            records.append({"round": feedback["round"], "problem": request.get("problem", "尚未形成有效需求"), "feedback": feedback})
        write_report(directory, read_json(directory / "baseline/case.json"), read_json(directory / "best_case.json"), summary, records)
        print(str(directory / "report.html"))
        return 0
    if args.command == "doctor":
        result = {"python": sys.executable, "version": sys.version, "windows": os.name == "nt",
                  "adapter": "toy", "sandbox": "windows_appcontainer", "providers": ["ollama", "chatgpt"]}
        import importlib.util
        result["chatgpt_dependencies_ready"] = importlib.util.find_spec("jwt") is not None
        try:
            result["ollama_models"] = local_models()
        except Exception as exc:
            result["ollama_error"] = str(exc)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    case = load_case(args.case)
    config = RunConfig(args.max_rounds, args.max_evaluations, args.max_model_calls, seed=args.seed)
    if args.provider == "chatgpt":
        provider = chatgpt_provider(args)
        print("ChatGPT account model: " + provider.resolve_model(), flush=True)
    else:
        model = args.model or os.environ.get("MACRO_AGENT_MODEL", "qwen3.5:4b")
        if model not in local_models(args.endpoint):
            raise ValueError(f"Ollama model not installed: {model}; select an existing model with --model")
        provider = OllamaProvider(model, args.endpoint)
    sandbox = WindowsSandbox(root)
    directory = args.output or root / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    summary = Controller(case, provider, sandbox, directory, config).run()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
