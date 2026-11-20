"""Check a retained catalog DEF against its hash-bound normalized source, without running iEDA."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

from audit_catalog_flow_inputs import resolve_inputs
from qualify_catalog_native_import import digest, normalized_netlist, inspect_def


def check(project,bench,pdks,catalog,case_id,artifact,checker=None):
    project=project.resolve()
    if not artifact.resolve(strict=True).is_relative_to((project/"runs").resolve()):
        raise ValueError("expected retained artifact in worker runs directory")
    sys.path.insert(0,str(project))
    from macro_agent.def_validation import lef_cells
    from macro_agent.liberty_buses import read_buses
    from macro_agent import aes_netlist
    if checker:
        spec=importlib.util.spec_from_file_location("macro_agent.qualification_verifier",checker)
        aes_netlist=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(aes_netlist)
    case=next(c for c in json.loads(catalog.read_bytes()) if c["id"]==case_id)
    row=resolve_inputs(case,bench,project,pdks)
    if row["missing"]:raise ValueError("missing declared physical inputs")
    directory=bench/"designs"/case_id
    source,record,report=normalized_netlist(directory,case)
    inputs=json.loads((directory/"design.json").read_bytes())["inputs"]
    paths={k:Path(v) for k,v in row["sources"].items()}
    if digest(paths[inputs["netlist"]])!=case["assets"]["netlist"]["sha256"]:raise ValueError("original netlist changed")
    cells={}
    for name in inputs.get("cells_lefs") or [inputs["cells_lef"]]:
        cells.update(lef_cells(paths[name],2000))
    buses=read_buses([paths[k] for k in inputs.get("libs") or [inputs["lib"]]],cells)
    top,count,nets=inspect_def(artifact)
    if top!=case["top"] or count!=record["cells"] or not nets:raise ValueError("DEF design or instance count mismatch")
    proof=aes_netlist.verify(source,artifact,buses)
    return dict(case=case_id,stage="endpoint_recheck",checker=digest(Path(aes_netlist.__file__)),
                normalized_import=proof,source_sha256=case["assets"]["netlist"]["sha256"],def_hash=digest(artifact),
                normalization_record=digest(report),normalized_netlist=digest(source),instances=count,nets=nets)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ["project","benchmarks","pdks","catalog","def"]:
        parser.add_argument("--"+field,dest="artifact" if field=="def" else field,type=Path,required=True)
    parser.add_argument("--checker",type=Path)
    parser.add_argument("case")
    a=parser.parse_args()
    result=check(a.project,a.benchmarks,a.pdks,a.catalog,a.case,a.artifact,a.checker)
    print(json.dumps(result))
    sys.exit(0 if result["normalized_import"]["passed"] else 1)
