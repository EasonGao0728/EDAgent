"""Read-only admission for workbench cases with retained complete-flow evidence."""
import json
from pathlib import Path
from . import ieda_stages
from .swerv_backend import sha

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {"import_netlist","floorplan","fanout","placement","validate","export_def",
            "cts","to_drv","to_hold","legalization","routing","filler","drc","timing",
            "gds_export","routed_readback"}


def fits_budget(state, budget):
    """An extended historical run does not qualify a shorter default profile."""
    used=state["contract"]["budget"]
    for key in ("cpu_threads","memory_gb"):
        if used.get(key)!=budget.get(key):
            return False
    for key in ("container_seconds","host_seconds","routing_seconds"):
        if key in used and used[key]>budget.get(key,budget.get("container_seconds",0)):
            return False
    elapsed=sum(result.get("seconds",0) for result in state["results"].values())
    return elapsed<=budget["wall_seconds"]


def ready(case_id):
    from .catalog_backend import CASES, require_qualification
    if case_id in CASES:
        receipt = require_qualification(case_id)
        manifest=json.loads((ROOT/"cases/ibench"/case_id/"manifest.json").read_bytes())
        return {"qualified":True,"goal":"full_backend","drc_count":receipt["drc_count"],
                "evidence":receipt["evidence"],"source":"catalog_fullflow_qualification",
                "floorplan_adaptation":manifest.get("floorplan_adaptation")}
    if case_id not in ieda_stages.REGISTERED_CASES:
        raise ValueError("Full-flow adapter has not qualified")
    from .aes_backend import CASES as AES, require_qualification as aes_qualification
    if case_id in AES:
        receipt = aes_qualification(case_id)
        return {"qualified":True,"goal":"full_backend","evidence":receipt["evidence"],
                "source":"aes_native_baseline"}
    # Retain explicit production task proof for older registered GCD and SWERV.
    from .full_backend import for_case
    backend=for_case(case_id)
    current=backend.input_files()
    for path in sorted((ROOT/"runs").glob("remote-*/acceptance.json")):
        try:
            state=json.loads((path.parent/"task.json").read_bytes())
            if (state["contract"]["case_id"]!=case_id or state["contract"]["goal"]!="full_backend"
                or state["status"]!="target_met" or not REQUIRED.issubset(state["completed"])):
                continue
            acceptance=json.loads(path.read_bytes())
            if not acceptance.get("case_run_passed") or not acceptance.get("full_backend_workflow_completed"):
                continue
            if not fits_budget(state,backend.manifest()["budget"]):
                continue
            frozen={r["path"]:r["sha256"] for r in state["input_refs"]}
            if any(frozen.get(str(p))!=sha(p) for p in current):
                continue
            for field in ("final_def","final_gds"):
                artifact=state["deliverables"][field]
                target=Path(artifact["path"]).resolve()
                if not target.is_relative_to(path.parent.resolve()) or sha(target)!=artifact["sha256"]:
                    raise ValueError("Complete-flow delivery changed")
            return {"qualified":True,"goal":"full_backend","evidence":{"path":str(path),"sha256":sha(path)},
                    "drc_count":acceptance.get("drc",{}).get("violation_count"),
                    "source":"completed_main_agent_task"}
        except (OSError,ValueError,KeyError):
            continue
    raise ValueError("No intact complete-flow result for this input package")
