"""Independent post-run direction audit, additional to endpoint contraction.

It does not modify the producer or its outputs, and is not RTL/LVS proof.
Every ordinary signal net must have exactly one driver using frozen LEF and
DEF top-port directions. Reversed buffer insertion must fail this audit.
"""
import argparse,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from macro_agent.def_validation import read_def

def directions(lefs):
    result={}
    for path in lefs:
        text=Path(path).read_text(encoding='utf-8')
        for m in re.finditer(r'^MACRO (\S+)\s*$(.*?)^END \1\s*$',text,re.M|re.S):
            pins={}
            for p in re.finditer(r'^\s*PIN\s+(\S+)\s*$(.*?)^\s*END\s+\1\s*$',m[2],re.M|re.S):
                d=re.search(r'\bDIRECTION\s+(INPUT|OUTPUT|INOUT)\s*;',p[2])
                if d:pins[p[1]]=d[1]
            if m[1] in result:raise ValueError('Duplicate LEF master')
            result[m[1]]=pins
    return result

def audit(design,masters,allowed_empty_nets=frozenset()):
    errors=[];seen={}
    empty={n for n,terms in design['nets'].items() if not terms}
    if empty!=set(allowed_empty_nets):errors.append('declared_empty_nets_changed')
    for net,terms in design['nets'].items():
        if not terms and net in allowed_empty_nets:continue
        drivers=[]
        for inst,pin in terms:
            term=(inst,pin)
            if term in seen:errors.append('terminal_reused:'+inst+'/'+pin)
            seen[term]=net
            if inst=='PIN':
                match=re.search(r'\+ DIRECTION (INPUT|OUTPUT|INOUT)\b',design['pins'].get(pin,''))
                direction=match[1] if match else None
                driver=direction=='INPUT'
            else:
                master=design['components'].get(inst,{}).get('master')
                direction=masters.get(master,{}).get(pin)
                driver=direction=='OUTPUT'
            if direction not in ('INPUT','OUTPUT'):errors.append('unsupported_signal_direction:'+inst+'/'+pin)
            if driver:drivers.append(term)
        if len(drivers)!=1:errors.append('signal_driver_count:'+net+':'+str(len(drivers)))
    return {'passed':not errors,'errors':errors[:50],'error_count':len(errors),'signal_nets_checked':len(design['nets'])-len(empty),'declared_empty_nets':sorted(empty),
        'scope':'Exactly one driver per ordinary signal net; known LEF/DEF directions; no endpoint reuse; complements original-endpoint contraction; not RTL/LVS signoff'}

def run(folder,reference):
    m=json.loads((reference/'manifest.json').read_text(encoding='utf-8'))
    masters=directions([reference/p for p in m['cell_lefs']]);results={}
    # The independently verified original import defines the unused wires.
    # This exemption never applies to a net with any electrical terminal.
    imported=read_def(folder/'result/import_netlist.def')
    allowed_empty_nets={n for n,terms in imported['nets'].items() if not terms}
    for stage in ('import_netlist','floorplan','fanout','placement','export_def','cts','to_drv','to_hold','legalization','routing','filler','drc','timing','routed_readback'):
        p=folder/'result'/(stage+'.def')
        if not p.is_file():results[stage]={'passed':False,'error':'missing_stage_artifact'}
        else:results[stage]=audit(read_def(p),masters,allowed_empty_nets)
    return {'passed':all(r['passed'] for r in results.values()),'stages':results}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--run',required=True);ap.add_argument('--case',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
    result=run(Path(a.run),ROOT/'cases/ibench'/a.case)
    Path(a.output).write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
