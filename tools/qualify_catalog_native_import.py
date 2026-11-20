"""Qualify native netlist import for one catalog design inside the existing remote worker.

This is the first physical stage. Evidence remains independent of the full-flow
registry until placement, routing and post-route checks have passed.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from audit_catalog_flow_inputs import resolve_inputs


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            sha.update(block)
    return sha.hexdigest()


def run(project, case, bench, pdks):
    sys.path.insert(0,str(project))
    from macro_agent import remote_service
    from macro_agent.portable_ieda import ENV, IMAGE, BINARY_SHA256
    from macro_agent.def_validation import read_def
    from macro_agent.swerv_screening import active_jobs
    row=resolve_inputs(case,bench,project,pdks)
    if row["missing"]:
        raise ValueError("missing physical inputs: "+", ".join(row["missing"]))
    design=json.loads((bench/"designs"/case["id"]/"design.json").read_bytes())
    inputs=design["inputs"]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*",design["top"]):
        raise ValueError("unsupported top name")
    remote_service.init()
    # Hold the same lock as the dispatcher throughout a synchronous qualification.
    with remote_service.gate():
        if active_jobs():
            raise ValueError("active remote job; wait before qualification")
        folder=project/"runs"/("qualification-"+case["id"])
        folder.mkdir(exist_ok=True)
        paths={key:Path(name) for key,name in row["sources"].items()}
        identity={key:digest(p) for key,p in paths.items()}
        if identity[inputs["netlist"]]!=case["assets"]["netlist"]["sha256"] or identity[inputs["sdc"]]!=case["assets"]["sdc"]["sha256"]:
            raise ValueError("catalog inputs changed")
        receipt=folder/"import.json"
        if receipt.exists():
            old=json.loads(receipt.read_bytes())
            if old["inputs"]==identity and old["binary"]==BINARY_SHA256 and old["def_hash"]==digest(folder/"import.def"):
                return old
            raise ValueError("previous qualification differs; preserve and review")
        attempt=Path(tempfile.mkdtemp(prefix="import-",dir=folder))
        (attempt/"logs").mkdir()
        (attempt/"result").mkdir()
        config=project/"cases/ibench/swerv_nangate45/config"
        for name in ("flow_config.json","db_default_config.json"):
            shutil.copyfile(config/name,attempt/name)
        references={}
        with tempfile.TemporaryDirectory(dir=folder,prefix="inputs-") as ref:
            for ix,(key,path) in enumerate(paths.items()):
                suffix=path.suffix if path.suffix in (".v",".lef",".tlef",".sdc",".lib") else ".dat"
                name=f"input{ix}{suffix}"
                shutil.copyfile(path,Path(ref)/name)
                references[key]="/reference/"+name
            lefs=inputs.get("cells_lefs") or [inputs["cells_lef"]]
            lib=inputs.get("libs") or [inputs["lib"]]
            lines=["flow_init -config /work/flow_config.json","db_init -config /work/db_default_config.json",
                   "tech_lef_init -path "+references[inputs["tech_lef"]],
                   "lef_init -path [list "+" ".join(references[v] for v in lefs)+"]",
                   "db_init -lib_path [list "+" ".join(references[v] for v in lib)+"]",
                   "db_init -sdc_path "+references[inputs["sdc"]],
                   "verilog_init -path "+references[inputs["netlist"]]+" -top {"+design["top"]+"}",
                   "def_save -path /work/result/import.def"]
            (attempt/"import.tcl").write_text("if {[catch {\n"+"\n".join(lines)+"\n} msg]} {puts stderr $msg; exit 1}\nflow_exit\n")
            cmd=[sys.executable,"-B","-m","macro_agent.remote_native","run","--rm","--pull=never","--name","aieda-catalog-import",
                 "--network","none","--cpus","4","--memory","8g","--pids-limit","256","--workdir","/work",
                 "--mount",f"type=bind,source={ref},target=/reference,readonly",
                 "--mount",f"type=bind,source={attempt},target=/work"]
            for k,v in {**ENV,"OMP_NUM_THREADS":"4","CONFIG_DIR":"/work","RESULT_DIR":"/work/result"}.items():
                cmd+=["--env",k+"="+v]
            cmd += [IMAGE,"timeout","--kill-after=5","600","iEDA","-script","/work/import.tcl"]
            with (attempt/"logs/import.log").open("w") as log:
                cp=subprocess.run(cmd,cwd=project,env={**os.environ,"AIEDA_NATIVE_HANDLES":str(attempt/"handles")},stdout=log,stderr=subprocess.STDOUT)
            if cp.returncode:
                raise RuntimeError(f"native import exited {cp.returncode}; see {attempt.name}/logs/import.log")
        artifact=attempt/"result/import.def"
        db=read_def(artifact)
        expected=case["cells"]+case["macros"]
        if db["design"]!=design["top"] or len(db["components"])!=expected or not db["nets"]:
            raise ValueError(f"import structural discrepancy: top={db['design']}, instances={len(db['components'])}/{expected}, nets={len(db['nets'])}; {attempt.name}")
        result=dict(case=case["id"],stage="import_netlist",inputs=identity,binary=BINARY_SHA256,instances=expected,nets=len(db["nets"]),def_hash=digest(artifact))
        receipt_tmp=attempt/"receipt.json"
        receipt_tmp.write_text(json.dumps(result,indent=2))
        artifact.replace(folder/"import.def")
        receipt_tmp.replace(receipt)
        return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ("project","benchmarks","catalog","pdks"):
        parser.add_argument("--"+key,type=Path,required=True)
    parser.add_argument("case")
    args=parser.parse_args()
    cases=json.loads(args.catalog.read_bytes())
    selected=next(c for c in cases if c["id"]==args.case and c.get("assets"))
    print(json.dumps(run(args.project.resolve(),selected,args.benchmarks,args.pdks)))
