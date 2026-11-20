"""Resolve the benchmark's declared physical inputs inside explicitly supplied roots.

Run on the iEDA server. The catalog is trusted project data. No benchmark Tcl
is executed and no archived DEF is used. Missing files remain visible per case.
"""
import argparse
import hashlib
import json
from pathlib import Path


def within(root, name):
    root = root.resolve()
    path = (root / name).resolve()
    return path if path.is_relative_to(root) and path.is_file() and path.stat().st_size else None


def resolve_inputs(case, benchmarks, project, pdks):
    directory = benchmarks / "designs" / case["id"]
    design_path = within(directory, case["assets"]["design"]["file"])
    if not design_path or hashlib.sha256(design_path.read_bytes()).hexdigest() != case["assets"]["design"]["sha256"]:
        raise ValueError("design.json missing or changed")
    design = json.loads(design_path.read_bytes())
    pdk = design["pdk"]
    inputs = design["inputs"]
    fallbacks = {"nangate45": project / "cases/ibench/swerv_nangate45/pdk",
                 "sky130": project / "cases/ibench/gcd_legacy/pdk"}
    roots = [pdks / pdk]
    if pdk in fallbacks:
        roots.append(fallbacks[pdk])
    missing, found = [], {}
    for role in ("netlist", "sdc", "tech_lef", "cells_lef", "cells_lefs", "lib", "libs"):
        entries = inputs.get(role, [])
        for name in entries if isinstance(entries, list) else [entries]:
            if name in found or name in missing:
                continue
            if name.startswith("$PDK/"):
                relative = name[5:]
                candidates = [(r, relative) for r in roots]
                candidates.append((benchmarks / "common/2d_pdk" / pdk, relative))
            elif name.startswith("../../common/2d_pdk/" + pdk + "/"):
                relative = name.split("/" + pdk + "/", 1)[1]
                candidates = [(benchmarks / "common/2d_pdk" / pdk, relative)]
            else:
                candidates = [(directory, name)] if not Path(name).is_absolute() else []
            source = next((path for root, rel in candidates if (path := within(root,rel))), None)
            if source:
                found[name] = str(source)
            else:
                missing.append(name)
    for required in ("tech_lef","netlist","sdc"):
        if not inputs.get(required):
            missing.append("design.inputs."+required)
    for single, multi in (("cells_lef","cells_lefs"),("lib","libs")):
        if not inputs.get(single) and not inputs.get(multi):
            missing.append("design.inputs."+multi)
    return {"id":case["id"], "pdk":pdk, "top":design["top"], "macros":case["macros"],
            "status":"missing_inputs" if missing else "inputs_located",
            "missing":missing, "sources":found}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("catalog","benchmarks","project","pdks"):
        parser.add_argument("--"+arg,required=True,type=Path)
    args = parser.parse_args()
    result = []
    for case in json.loads(args.catalog.read_bytes()):
        if case.get("assets"):
            try:
                row = resolve_inputs(case,args.benchmarks,args.project,args.pdks)
            except (OSError, ValueError, KeyError) as exc:
                row = {"id":case["id"], "status":"invalid_package", "error":str(exc)}
        else:
            row = {"id":case["id"],"status":"registered_"+case["goal"]}
        result.append(row)
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
