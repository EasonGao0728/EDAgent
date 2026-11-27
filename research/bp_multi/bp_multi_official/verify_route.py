"""Read-only qualification of an official-port route and its independent physical audit."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from functools import lru_cache
from pathlib import Path
import re
import sys

ROOT = Path('/srv/edagent/main-agent-remote-v1')
LOCAL = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT if (ROOT/'macro_agent').is_dir() else LOCAL))
from macro_agent.aes_transforms import check
from macro_agent.def_validation import read_def, section
from def_conductors import PhysicalLibrary, independent_graph

MODULES = [('PinAccessor', 'access'), ('SupplyAnalyzer', 'analyze'), ('TopologyGenerator', 'generate'),
           ('LayerAssigner', 'assign'), ('SpaceRouter', 'route'), ('TrackAssigner', 'assign'),
           ('DetailedRouter', 'route'), ('ViolationReporter', 'report')]
AUDITOR_SHA = '4a88f975c6e6d31f252a6b8d88bc011ac097497fff98f96480f9665173f95c1c'

def sha(path):
    with Path(path).open('rb') as stream:
        h = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

def log_check(log, total):
    pattern = r'\b(\w+)\.cpp:\d+ Info (\w+)\] (Starting\.\.\.|Completed \(elapsed =)'
    events = [(m[1], m[3].split(' ')[0]) for m in re.finditer(pattern, log) if (m[1], m[2]) in MODULES]
    expected = [(name, event) for name, _ in MODULES for event in ('Starting...', 'Completed')]
    counts = {}
    for name, func in [('TopologyGenerator', 'generateTGModel'), ('LayerAssigner','routeLAModel')]:
        batches = re.findall(name + r'\.cpp:\d+ Info ' + func + r'\] Routed (\d+)/(\d+)\(', log)
        counts[name] = [list(map(int, x)) for x in batches]
    policy_round = re.findall(r'DetailedRouter\.cpp:\d+ Info routeDRModel\] \*+ (Begin iteration|End Iteration) (\d+)/(\d+)\(', log)
    all_nets = all(seq and seq[-1] == [total, total] and all(den == total for _, den in seq) and
                   all(0 < a <= total for a, _ in seq) and all(a[0] < b[0] for a, b in zip(seq, seq[1:]))
                   for seq in counts.values())
    return dict(passed=events==expected and all_nets and policy_round==[('Begin iteration','1','1'),('End Iteration','1','1')],
                module_events=events, observed_batches=counts, dr_iterations=policy_round)

def track_grid(records):
    grid = defaultdict(list)
    for row in records:
        axis, start, count, pitch, layers = re.fullmatch(r'([XY]) (-?\d+) DO ([1-9]\d*) STEP ([1-9]\d*) LAYER (\S+(?: \S+)*)', row).groups()
        for layer in layers.split():
            grid[layer,axis].append(tuple(map(int,(start,count,pitch))))
    return grid

def on_grid(lines, coord):
    return any(start <= coord <= start+(count-1)*pitch and (coord-start)%pitch == 0 for start,count,pitch in lines)

POINT = r'\(\s*([*]|-?\d+)\s+([*]|-?\d+)(?:\s+(-?\d+))?\s*\)'
def measure_paths(text, expected, tracks, port_shapes=None):
    """Measure Manhattan centreline alignment; non-native DEF syntax remains unqualified."""
    seen, counts, examples = set(), Counter(), []
    via_counts, offset_counts = Counter(), Counter()
    for row in section(text, 'NETS'):
        name = row.split()[0]
        if name not in expected:
            continue
        groups = re.split(r'\+\s+(?:ROUTED|FIXED|COVER|SHIELD)\s+',row)
        if len(groups)==1:
            counts['missing_route_record']+=1
            if len(examples)<12:examples.append([name,'missing_route_record'])
            continue
        has_metal=False
        for group in groups[1:]:
            for path in re.split(r'\bNEW\s+',group):
                layer,body = path.strip().split(None,1)
                if (layer,'X') not in tracks or (layer,'Y') not in tracks:
                    raise ValueError(f'unknown routing layer {layer!r}')
                x=y=None
                while (m:=re.match(POINT,body)):
                    nx=x if m[1]=='*' else int(m[1])
                    ny=y if m[2]=='*' else int(m[2])
                    if nx is None or ny is None:raise ValueError('wildcard before initial DEF route coordinate')
                    if x is not None and (x,y)!=(nx,ny):
                        if x!=nx and y!=ny:raise ValueError('unsupported diagonal centreline')
                        axis,coord=('X',x) if x==nx else ('Y',y)
                        has_metal=True
                        counts['nonzero_segments']+=1
                        if not on_grid(tracks[layer,axis],coord):
                            # An access centreline fully inside the same terminal metal is physically explained.
                            covered = port_shapes is not None and any(
                                l==layer and a<=2*min(x,nx) and c>=2*max(x,nx) and b<=2*min(y,ny) and d>=2*max(y,ny)
                                for l,a,b,c,d in port_shapes(name))
                            if covered:
                                counts['off_track_inside_terminal']+=1
                            else:
                                offset_counts[layer,axis]+=1
                                if len(examples)<12:examples.append([name,layer,axis,coord,[x,y],[nx,ny]])
                    x,y=nx,ny
                    body=body[m.end():].strip()
                if x is None:raise ValueError('missing DEF route coordinates')
                if body:
                    if re.fullmatch(r'RECT\s+\(\s*-?\d+\s+-?\d+\s+-?\d+\s+-?\d+\s*\)',body):
                        counts['patches']+=1
                    elif re.fullmatch(r'[a-zA-Z_][\w.\-/]*',body):
                        via_counts[body]+=1
                        counts['via_placements']+=1
                        has_metal=True
                    else:raise ValueError(f'unsupported DEF route tail on {name}: {body[:100]}')
        if has_metal:seen.add(name)
    return dict(passed=seen==expected and not offset_counts, expected_nets=len(expected), nets_with_conductors=len(seen),
                missing_net_examples=sorted(expected-seen)[:12], measurements=dict(counts), via_counts=dict(via_counts),
                off_track_by_layer_axis={f'{layer}/{axis}':count for (layer,axis),count in sorted(offset_counts.items())},
                examples=examples,scope='Unclassified off-track segments require separate pin-access geometry review; they are not counted as DRC.')

def read_json(p):
    return json.loads(Path(p).read_bytes())

def graph_check(directory, routed_sha, expected):
    """Require separate frozen-DEF auditor outputs, its exit, identity and unchanged input/output hashes."""
    receipt=read_json(directory/'receipt.json')
    auditfile=directory/'connectivity_audit.json'
    audit=read_json(auditfile)
    valid_receipt=(receipt.get('returncode')==0 and receipt.get('input_sha256')==receipt.get('input_sha256_after')==routed_sha
                   and receipt.get('binary_sha256')==AUDITOR_SHA and receipt.get('audit_sha256')==sha(auditfile))
    clean=lambda name: name.lstrip('\\').replace('\\[','[').replace('\\]',']')
    expects={clean(name):len(pins) for name,pins in expected.items()}
    if len(expects)!=len(expected):raise ValueError('ambiguous canonical names')
    rows=audit.get('per_net',[])
    errors=[]
    observed=set()
    ids=set()
    for row in rows:
        name=clean(row['name'])
        i=row.get('net_idx')
        if (name in observed or type(i) is not int or i in ids or row.get('pins')!=expects.get(name)
            or row.get('physical_pin_connected') is not True or row.get('floating_primitives')!=0
            or type(row.get('wire_via_primitives')) is not int or row['wire_via_primitives']<1):
            if len(errors)<12:errors.append(name)
        observed.add(name)
        ids.add(i)
    ok=(valid_receipt and not errors and observed==set(expects) and audit.get('non_mutating') is True and audit.get('includes_patches') is True
        and audit.get('all_physical_pins_connected') is True and audit.get('schema_version')==1
        and audit.get('model')=='closed_same_layer_real_metal_contact_LEF_vias_and_pin_ports_epsilon_zero'
        and all(audit.get(key)==[] for key in ('disconnected_net_ids','unknown_pin_model_net_ids','floating_patches')))
    return dict(passed=ok, matched_receipt=valid_receipt, audited_nets=len(rows), expected_nets=len(expected),
                missing_examples=sorted(set(expects)-observed)[:12],extra_examples=sorted(observed-set(expects))[:12],
                failed_net_examples=errors, audit_sha256=sha(auditfile))

def validate(work,checkpoint,binary_hash,audit,tech=None,lefs=()):
    before=read_def(checkpoint)
    out=work/'result/routing.def'
    receipt=read_json(work/'receipt.json')
    log=(work/'result/rt/rt.log').read_text(errors='replace')
    result=dict(input_sha256=sha(checkpoint),artifact_sha256=sha(out),binary_sha256=binary_hash)
    expected={name:pins for name,pins in before['nets'].items() if len(pins)>=2}
    witness=work/'pa.tsv'
    result['run']=dict(passed=receipt.get('returncode')==0 and receipt.get('stage_marker') is True
            and receipt.get('input_sha256')==result['input_sha256'] and receipt.get('binary_sha256')==binary_hash
            and receipt.get('pa',{}).get('passed') is True and witness.is_file()
            and receipt['pa'].get('ap_witness_sha256')==sha(witness)
            and receipt.get('cpus')==4 and receipt.get('address_space_gib')==8
            and 'SWERV_STAGE_OK routing' in (work/'stdout.log').read_text(errors='replace'))
    result['log']=log_check(log,len(expected))
    after=read_def(out)
    result['transformation']=check(before,after,'routing')
    result['physical']=dict(passed=before['physical']==after['physical'],
                            changed_sections=[k for k in before['physical'] if before['physical'][k]!=after['physical'].get(k)])
    text=out.read_text()
    lib=PhysicalLibrary(tech,lefs,after['units']) if tech and lefs else None
    @lru_cache(maxsize=1)
    def port_shapes(name):
        return tuple(r for p in expected[name] for r in lib.pin(after,*p))
    result['paths']=measure_paths(text,set(expected),track_grid(before['physical']['TRACKS']),port_shapes if lib else None)
    graphs=[]
    if lib:
        result['offline_graph']=independent_graph(text,after,expected,lib)
        result['offline_graph']['lef_sha256']={str(p):sha(p) for p in [tech,*lefs]}
        graphs.append(result['offline_graph'])
    if audit:
        result['native_readback_graph']=graph_check(audit,result['artifact_sha256'],expected)
        graphs.append(result['native_readback_graph'])
    result['pin_conductors']={'passed':bool(graphs) and all(g['passed'] for g in graphs),
                              'graph_sources':len(graphs)}
    result['passed']=all(result[k]['passed'] for k in ('run','log','transformation','physical','paths','pin_conductors'))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--checkpoint',type=Path,required=True)
    parser.add_argument('--binary-hash',required=True)
    parser.add_argument('--audit',type=Path)
    parser.add_argument('--tech',type=Path)
    parser.add_argument('--cell',type=Path,action='append',default=[])
    a=parser.parse_args()
    try:
        result=validate(a.work,a.checkpoint,a.binary_hash,a.audit,a.tech,a.cell)
    except (OSError,KeyError,ValueError,AttributeError,TypeError) as exc:
        result={'passed':False,'error':str(exc)}
    print(json.dumps(result,indent=2))
    sys.exit(0 if result['passed'] else 1)
