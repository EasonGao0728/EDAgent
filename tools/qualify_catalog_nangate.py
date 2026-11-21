"""Prepare an auditable Nangate45 case and qualify its stages with the existing EDAgent executor.

The pilot accepts one clock, frozen imported DEF and an independently matched
source netlist. It refuses process, connectivity and clock substitutions.
"""
import argparse
import importlib.util
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

from audit_catalog_flow_inputs import resolve_inputs
from qualify_catalog_native_import import digest, normalized_netlist


def load_stage_engine(project, candidate):
    if candidate is None:
        from macro_agent import swerv_backend
        return swerv_backend
    # The operator can test a new copy without editing code bound to old runs.
    spec=importlib.util.spec_from_file_location("macro_agent.catalog_qualification_engine",candidate)
    engine=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    engine.ROOT=project
    return engine


def clock(sdc):
    # The original SDC drives the timing engine. Catalog guesses can differ
    # in both clock name and period even when they identify the same port.
    commands=[line.strip() for line in sdc.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    lines=[line for line in commands if re.search(r"\bcreate_(?:generated_)?clock\b",line)]
    if len(lines)!=1:raise ValueError("single-clock binding unavailable")
    declaration=lines[0]
    if "$" in declaration:
        values={}
        for line in commands[:commands.index(declaration)]:
            binding=re.fullmatch(r"set\s+(\w+)\s+([a-zA-Z0-9_.]+)\s*;?",line)
            if not binding:raise ValueError("clock depends on unsupported Tcl preamble")
            values[binding[1]]=binding[2]
        declaration=re.sub(r"\$(\w+)",lambda match:values.get(match[1],match[0]),declaration)
    found=re.fullmatch(r"create_clock\s+-name\s+(\w+)\s+-period\s+([\d.]+)\s+\[get_ports\s+(\w+)\]\s*;?",declaration)
    if not found or float(found[2])<=0:raise ValueError("unsupported clock declaration")
    name,port=found[1],found[3]
    if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",v) for v in (name,port)):
        raise ValueError("unsupported clock identifier")
    return name,port


def prepare(project,bench,pdks,case,receipt_dir,ref,stage_engine,floorplan_scale=1.0,hold_guard=False):
    from macro_agent.aes_netlist import verify
    from macro_agent.def_validation import read_def
    row=resolve_inputs(case,bench,project,pdks)
    if row["missing"] or row["pdk"]!="nangate45":raise ValueError("requires complete Nangate45 profile")
    design=json.loads((bench/"designs"/case["id"]/"design.json").read_bytes())
    spec=design["inputs"]
    imported=json.loads((receipt_dir/"import.json").read_bytes())
    if digest(receipt_dir/"import.def")!=imported["def_hash"]:raise ValueError("imported DEF changed")
    paths={name:Path(f) for name,f in row["sources"].items()}
    for name,path in paths.items():
        if digest(path)!=imported["inputs"][name]:raise ValueError("input changed: "+name)
    if "normalized_verilog" in imported["inputs"]:
        paths[spec["netlist"]],record,_=normalized_netlist(bench/"designs"/case["id"],case)
        if record["output_sha256"]!=imported["inputs"]["normalized_verilog"]:raise ValueError("normalized identity changed")
    template=project/"cases/ibench/swerv_nangate45"
    aliases={}
    for idx,(name,path) in enumerate(paths.items()):
        dst=f"data/input{idx}{path.suffix}"
        (ref/"data").mkdir(exist_ok=True)
        shutil.copyfile(path,ref/dst)
        aliases[name]=dst
    fp=design["floorplan"]
    site=fp["core_site"]
    if site!="FreePDK45_38x28_10R_NP_162NW_34O" or (design.get("physical_design",{}).get("routing_layers") or ["metal2","metal6"])!=["metal2","metal6"]:
        raise ValueError("Nangate45 site or routing layer profile differs")
    def area(field):
        values=[float(v) for v in fp[field].split()]
        if len(values)!=4 or not (0<=values[0]<values[2] and 0<=values[1]<values[3]):raise ValueError("invalid "+field)
        return values
    name,port=clock(paths[spec["sdc"]].read_text())
    m=dict(case_id=case["id"],top=design["top"],clock_name=name,clock_port=port,
           core_site=site,die_area_microns=area("die_area"),core_area_microns=area("core_area"),
           expected_instances=imported["instances"],netlist=aliases[spec["netlist"]],sdc=aliases[spec["sdc"]],
           tech_lef=aliases[spec["tech_lef"]],cell_lefs=[aliases[k] for k in (spec.get("cells_lefs") or [spec["cells_lef"]])],
           libs=[aliases[k] for k in (spec.get("libs") or [spec["lib"]])])
    if floorplan_scale!=1.0:
        if not 1.0<floorplan_scale<=1.6:raise ValueError("floorplan expansion out of bounds")
        die,core=m["die_area_microns"],m["core_area_microns"]
        original={"die":die[:],"core":core[:]}
        for axis,pitch in [(0,.19),(1,1.4)]:
            width=math.ceil((core[axis+2]-core[axis])*floorplan_scale/pitch)*pitch
            margin=die[axis+2]-core[axis+2]
            core[axis+2]=round(core[axis]+width,6)
            die[axis+2]=round(core[axis+2]+margin,6)
        m["floorplan_adaptation"]={"scale":floorplan_scale,"original":original,
                                  "reason":"Native macro placement needs additional legal packing space"}
    if hold_guard:
        m['hold_compatibility_guard']='f881cd0b0118bbfdab115a1cd793f18a666a6148da0a755eb591851c88df6abd'
    cells,buses=stage_engine.cells_and_buses(ref,m)
    proof=verify(ref/m["netlist"],receipt_dir/"import.def",buses)
    if not proof["passed"]:raise ValueError("source endpoint mismatch "+str(proof["errors"]))
    db=read_def(receipt_dir/"import.def")
    macros={n:c["master"] for n,c in db["components"].items() if cells[c["master"]]["hard_macro"]}
    if len(macros)!=case["macros"] or port not in db["pins"]:raise ValueError("macro or clock-port count mismatch")
    m.update(expected_macro_masters=macros,macro_placement=dict(macros=sorted(macros),hmetis="tools/hmetis2.0pre1"))
    if macros:
        (ref/"tools").mkdir()
        shutil.copy2(template/"tools/hmetis2.0pre1",ref/"tools/hmetis2.0pre1")
    shutil.copytree(template/"config",ref/"config")
    for cfg in (ref/"config").glob("*.json"):
        value=json.loads(cfg.read_bytes())
        files=value.get("file_path",{})
        if files:
            files.update(lib_files=["/reference/"+k for k in m["libs"]],lef_files=["/reference/"+k for k in [m["tech_lef"],*m["cell_lefs"]]],sdc_file="/reference/"+m["sdc"])
            if not macros and files.get("def_file")=="/work/result/macro_placement.def":files["def_file"]="/work/result/floorplan.def"
            cfg.write_text(json.dumps(value,indent=2))
    (ref/"manifest.json").write_text(json.dumps(m,indent=2))
    (ref/"source-proof.json").write_text(json.dumps(proof,indent=2))
    return m


def main(args):
    project=args.project.resolve()
    sys.path.insert(0,str(project))
    from macro_agent import remote_service
    from macro_agent.swerv_screening import active_jobs
    remote_service.init()
    engine=load_stage_engine(project,args.candidate)
    io=None
    if args.io_adapter:
        spec=importlib.util.spec_from_file_location("macro_agent.qualification_io",args.io_adapter)
        io=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(io)
    catalog=json.loads(args.catalog.read_bytes());case=next(c for c in catalog if c["id"]==args.case)
    prefix="structural-" if args.structural else "qualification-"
    imported=project/"runs"/(prefix+args.case)
    with remote_service.gate():
        if active_jobs():raise ValueError("server busy")
        suffix="-"+args.variant if args.variant else ""
        if suffix and not re.fullmatch(r"-[a-z0-9-]{1,32}",suffix):raise ValueError("invalid qualification variant")
        parent=project/"runs"/("bringup-"+case["id"]+suffix);parent.mkdir(exist_ok=True)
        previous=list(parent.glob("attempt-*/progress.json"))
        if previous and not args.resume:
            raise ValueError("previous stages already accepted; continue the verified checkpoint instead of restarting")
        if args.resume:
            if len(previous)!=1:raise ValueError("resume requires one unambiguous prior checkpoint")
            work=previous[0].parent
        else:
            work=Path(tempfile.mkdtemp(dir=parent,prefix="attempt-"))
        (work/"logs").mkdir(exist_ok=True)
        print("attempt", work.name, flush=True)
        (work/"handles").mkdir(exist_ok=True)
        os.environ["AIEDA_NATIVE_HANDLES"]=str(work/"handles")
        with tempfile.TemporaryDirectory(dir=parent,prefix="refs-") as tmp:
            ref=Path(tmp);m=prepare(project,args.benchmarks,args.pdks,case,imported,ref,engine,args.floorplan_scale,args.hold_guard)
            stages=[s for s in engine.STAGES if s!="import_netlist" and (s!="macro_placement" or case["macros"])]
            binding={str(p.relative_to(ref)):digest(p) for p in ref.rglob("*") if p.is_file()}
            binding["import.def"]=digest(imported/"import.def")
            binding["stage_engine"]=digest(Path(engine.__file__))
            completed=[]
            if args.resume:
                saved=json.loads(previous[0].read_bytes())
                completed=saved["completed"]
                if binding!=saved['binding'] and args.hold_guard:
                    old_manifest=json.loads((work/'manifest.json').read_bytes())
                    expected=dict(old_manifest,hold_compatibility_guard=m['hold_compatibility_guard'])
                    changed={k for k in binding.keys()|saved['binding'].keys() if binding.get(k)!=saved['binding'].get(k)}
                    # Explicit tool substitution at the failed hold boundary;
                    # other sources and every accepted stage remain frozen.
                    if (m!=expected or changed!={'manifest.json','stage_engine'}
                        or completed!=stages[:stages.index('to_hold')]
                        or saved['binding']['stage_engine']!='bd0dc6b759815f79484bcd2b6efe5854bbbd450aac1e8f2fd61bac4f673a55c8'
                        or digest(args.candidate)!=digest(project/'macro_agent/swerv_backend.py')):
                        raise ValueError('Unreviewed hold compatibility amendment')
                    amendment=work/'hold-guard-amendment.json'
                    if amendment.exists():raise ValueError('Hold amendment already exists')
                    shutil.copy2(previous[0],work/'progress-before-hold-guard.json')
                    shutil.copy2(work/'manifest.json',work/'manifest-before-hold-guard.json')
                    amendment.write_text(json.dumps({'old_binding':saved['binding'],'new_binding':binding,
                        'preserved_completed':completed,'scope':'Existing isolated hold divisor guard; default stages unchanged'},indent=2))
                    (work/'manifest.json').write_text(json.dumps(m,indent=2))
                    saved['binding']=binding
                if (binding!=saved["binding"] or completed!=stages[:len(completed)]
                    or digest(work/"result/import_netlist.def")!=binding["import.def"]):
                    raise ValueError("checkpoint identity or stage ordering changed")
                if io:
                    amendment=work/"io-adapter-amendment.json"
                    identity={"source_sha256":digest(args.io_adapter),"first_stage":stages[len(completed)] if len(completed)<len(stages) else None,
                              "preserved_completed":completed,"scope":"equivalent IO syntax only"}
                    if amendment.exists():
                        if json.loads(amendment.read_bytes())["source_sha256"]!=identity["source_sha256"]:
                            raise ValueError("IO adapter amendment changed")
                    else:amendment.write_text(json.dumps(identity,indent=2))
                for name in completed:
                    proof=work/("validation.json" if name=="validate" else name+"-evidence.json")
                    evidence=json.loads(proof.read_bytes())
                    if not evidence["passed"] or ("artifact" in evidence and digest(Path(evidence["artifact"]))!=evidence["artifact_sha256"]):
                        raise ValueError("prior evidence changed: "+name)
            else:
                shutil.copyfile(ref/"manifest.json",work/"manifest.json")
                shutil.copyfile(ref/"source-proof.json",work/"source-proof.json")
                shutil.copytree(ref/"config",work/"config")
                for d in ("report","pl","cts","no","to","to_drv","to_hold","rt","drc","timing"):(work/"result"/d).mkdir(parents=True)
                shutil.copyfile(imported/"import.def",work/"result/import_netlist.def")
                (work/"run-start.json").write_text(json.dumps(dict(time=time.time(),case_id=case["id"])))
            for stage in stages[len(completed):]:
                if args.resume:
                    prior=[p for p in [work/"logs"/(stage+".log"),work/(stage+"-evidence.json"),work/"result"/(stage+".def")] if p.is_file()]
                    if prior:
                        archive=Path(tempfile.mkdtemp(dir=work,prefix="prior-"+stage+"-"))
                        for p in prior:shutil.copy2(p,archive/p.name)
                if io and stage in ("macro_placement","fanout","placement","export_def","cts","to_drv","to_hold","legalization","timing"):
                    result=io.execute(stage,work,ref,backend=engine)
                else:result=engine.execute(stage,work,ref)
                completed.append(stage)
                temporary=work/"progress.tmp"
                temporary.write_text(json.dumps({"case":case["id"],"binding":binding,"completed":completed,"last":result},indent=2))
                temporary.replace(work/"progress.json")
                print(stage,"passed",flush=True)
            print("qualification complete",case["id"],flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("project","benchmarks","pdks","catalog"):parser.add_argument("--"+name,required=True,type=Path)
    parser.add_argument("--candidate",type=Path)
    parser.add_argument("--structural",action="store_true")
    parser.add_argument("--resume",action="store_true",help="Verify source and stage receipts before continuing an interrupted qualification")
    parser.add_argument("--io-adapter",type=Path,help="Reviewed equivalent IO adapter, recorded as a checkpoint amendment")
    parser.add_argument("--variant",default="",help="Preserve a distinct qualification branch")
    parser.add_argument("--floorplan-scale",type=float,default=1.0)
    parser.add_argument('--hold-guard',action='store_true',help='Explicitly qualify the existing pinned hold division guard')
    parser.add_argument("case")
    main(parser.parse_args())
