"""Register a catalog profile only after its complete native qualification."""
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

from qualify_catalog_nangate import prepare, load_stage_engine


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def promote(args):
    project = args.project.resolve()
    sys.path.insert(0, str(project))
    from macro_agent import remote_service, swerv_backend
    from macro_agent.swerv_screening import active_jobs
    remote_service.init()
    case = next(c for c in json.loads(args.catalog.read_bytes()) if c["id"] == args.case)
    engine = load_stage_engine(project, args.candidate)
    suffix = "-" + args.variant if args.variant else ""
    parent = project / "runs" / ("bringup-" + args.case + suffix)
    matches = list(parent.glob("attempt-*/progress.json"))
    if len(matches) != 1:
        raise ValueError("An unambiguous completed qualification is required")
    work = matches[0].parent
    progress = json.loads(matches[0].read_bytes())
    stages = [s for s in swerv_backend.STAGES if s != "import_netlist" and
              (s != "macro_placement" or case["macros"])]
    if progress["completed"] != stages:
        raise ValueError("Not every backend stage has passed")
    results = {}
    for stage in stages:
        source = work / ("validation.json" if stage == "validate" else stage + "-evidence.json")
        value = json.loads(source.read_bytes())
        if value["passed"] is not True:
            raise ValueError("Unaccepted stage " + stage)
        if "artifact" in value and sha(Path(value["artifact"])) != value["artifact_sha256"]:
            raise ValueError("Stage output changed " + stage)
        results[stage] = value
    if not results["routed_readback"]["readback_equal"]:
        raise ValueError("DEF readback failed")
    destination = project / "cases/ibench" / args.case
    with remote_service.gate():
        if active_jobs():
            raise ValueError("Server is busy")
        if destination.exists():
            raise ValueError("A registered profile exists; preserve it")
        with tempfile.TemporaryDirectory(dir=destination.parent, prefix="catalog-profile-") as temporary:
            ref = Path(temporary)
            imported = project / "runs" / ("structural-" + args.case)
            if not (imported / "import.json").is_file():
                imported = project / "runs" / ("qualification-" + args.case)
            m = prepare(project, args.benchmarks, args.pdks, case, imported, ref, engine,args.floorplan_scale)
            binding = {str(p.relative_to(ref)): sha(p) for p in ref.rglob("*") if p.is_file()}
            binding.update({"import.def": sha(imported / "import.def"),
                            "stage_engine": sha(args.candidate)})
            if binding != progress["binding"]:
                raise ValueError("Qualified profile inputs changed")
            m.update(schema_version="ieda_case_v1", backend="iEDA",
                     format_id="catalog_nangate45:" + args.case, hidden_reference_coordinates=False,
                     scripts_dir="script", config_dir="config", foundry_dir="data",
                     allowed_physical_insertions=[], allowed_power_pins={}, logical_only_pdn_pins=[],
                     scope="Hash-bound normalized source and public Nangate45 libraries",
                     budget={"executions":24, "model_calls":64, "wall_seconds":7200,
                             "cpu_threads":4,"memory_gb":8,"container_seconds":5400,"host_seconds":5420},
                     full_backend_policy={"stages":stages,"physical_quality":"Native DRC reported separately",
                                          "timing":"Diagnostic cell-delay STA",
                                          "gds":"Abstract geometry export",
                                          "unavailable":["extracted RC timing","manufacturing signoff"]},
                     provenance=["source-proof.json","qualification.json"])
            (ref / "script").mkdir()
            (ref / "manifest.json").write_text(json.dumps(m, indent=2))
            qualified_inputs = {str(p.relative_to(ref)): sha(p) for p in ref.rglob("*") if p.is_file()}
            implementations = {str(p.relative_to(project)): sha(p) for p in
                               [project / "macro_agent" / (n + ".py") for n in
                                ("catalog_backend","swerv_backend","def_io_compat","aes_netlist","aes_transforms","liberty_buses","macro_stages")]}
            receipt = {"case_id":args.case,"status":"passed","input_sha256":qualified_inputs,
                       "implementation_sha256":implementations,
                       "evidence":{"path":str(matches[0]),"sha256":sha(matches[0])},
                       "drc_count":results["drc"]["drc_gate"]["violation_count"],
                       "retained_qualification_artifacts":True}
            (ref / "qualification.json").write_text(json.dumps(receipt, indent=2))
            shutil.copytree(ref, destination)
    print(json.dumps({"case":args.case,"registered":True,"drc":receipt["drc_count"]}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("project","benchmarks","pdks","catalog","candidate"):
        p.add_argument("--"+name, type=Path, required=True)
    p.add_argument("case")
    p.add_argument("--variant",default="")
    p.add_argument("--floorplan-scale",type=float,default=1.0)
    promote(p.parse_args())
