"""Read-only workbench probe. The host supplies a trusted catalog and optional selection."""
import hashlib
import json
import re
import sys
from pathlib import Path

CATALOG = []  # injected on the host
SELECTED = None  # injected on the host
BENCHMARKS = Path("/srv/benchmarks/iBench/benchmarks")


def under(root, relative):
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("input outside allowed directory")
    return path


def files(package):
    directory = BENCHMARKS / "designs" / package["id"]
    return {role: under(directory, spec["file"]) for role, spec in package["assets"].items()}


def available(package):
    try:
        return all(p.stat().st_size == package["assets"][role]["bytes"]
                   for role, p in files(package).items())
    except (OSError, ValueError):
        return False


def audit(package):
    paths = files(package)
    hashes = {}
    for role, path in paths.items():
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        hashes[role] = digest.hexdigest()
        if hashes[role] != package["assets"][role]["sha256"]:
            raise ValueError("input hash mismatch: " + role)
    design = json.loads(paths["design"].read_text())
    if design["top"] != package["top"] or design["pdk"] != package["pdk"]:
        raise ValueError("design metadata changed")
    constraints = paths["sdc"].read_text(errors="replace")
    inputs = design.get("inputs", {})
    libraries = []
    for key in ("tech_lef", "cells_lef", "cells_lefs", "lib", "libs"):
        values = inputs.get(key, [])
        libraries.extend(values if isinstance(values, list) else [values])
    return dict(id=package["id"], hashes=hashes, top=design["top"], pdk=design["pdk"],
                clocks=len(re.findall(r"(?m)^\s*create_(?:generated_)?clock\b", constraints)),
                libraries=list(dict.fromkeys(libraries)))


if SELECTED:
    print(json.dumps(audit(next(p for p in CATALOG if p["id"] == SELECTED))))
else:
    sys.path.insert(0, str(Path.cwd()))
    from macro_agent.remote_native import runtime_status
    from macro_agent.ieda_stages import REGISTERED_CASES, input_files
    from macro_agent.swerv_screening import active_jobs

    packages = [p["id"] for p in CATALOG if available(p)]
    for case in REGISTERED_CASES:
        try:
            if all(p.is_file() for p in input_files(case)):
                packages.append(case)
        except (OSError, ValueError):
            continue
    readiness = {}
    for case in CATALOG:
        case_id = case["id"]
        if case["pdk"] == "ics55":
            readiness[case_id] = "等待 ICS55 工艺库授权"
            continue
        try:
            pilot=json.loads((Path("runs") / ("bringup-"+case_id) / "qualification.json").read_bytes())
            if (pilot["case"]==case_id and pilot["source_sha256"]==case["assets"]["netlist"]["sha256"]
                and pilot["gds_export"]["passed"] and pilot["routed_readback"]["semantic_match"]):
                count=pilot["drc"]["drc"]["violation_count"]
                readiness[case_id]=f"服务器全流程已验证 · DRC {count} 项"
                continue
        except (OSError, ValueError, KeyError):
            pass
        try:
            checked=json.loads((Path("runs")/("structural-"+case_id)/"endpoint-check.json").read_bytes())
            if (checked["case"]==case_id and checked["source_sha256"]==case["assets"]["netlist"]["sha256"]
                and checked["normalized_import"]["passed"] is True):
                readiness[case_id]="网表端点已核验"
                continue
        except (OSError, ValueError, KeyError):
            pass
        for prefix, label in (("structural-", "网表端点已核验"), ("qualification-", "已生成导入 DEF")):
            receipt = Path("runs") / (prefix+case_id) / "import.json"
            try:
                evidence = json.loads(receipt.read_bytes())
                if (evidence["case"] == case_id and evidence["stage"] == "import_netlist"
                        and case["assets"]["netlist"]["sha256"] in evidence["inputs"].values()):
                    readiness[case_id] = label
                    break
            except (OSError, ValueError, KeyError):
                continue
    print(json.dumps(dict(online=runtime_status()["available"], cases=packages, jobs=len(active_jobs()), readiness=readiness)))
