"""Read-only server inventory. Run over SSH stdin; no iEDA or Tcl execution.

Bounded static scans, explicit provenance, no private-directory symlink following.
Outputs one JSON line per case, allowing a local caller to persist progress.
"""
from pathlib import Path
from collections import Counter
import hashlib,json,re,os,resource,time

SHARED=Path('/srv/benchmarks/iBench/benchmarks')
OWN=Path('/srv/edagent/main-agent-remote-v1')
ALLOWED=(SHARED,OWN)
MAX_PARSE=25*1024*1024
IDENT=r'(?:\\[^\s]+|[A-Za-z_$][\w$]*)'

def safe(p):
    p=Path(p).resolve()
    if not any(p==r or r in p.parents for r in ALLOWED):raise ValueError('outside_authorized_roots')
    return p

def ref(p):
    p=safe(p);h=hashlib.sha256()
    with p.open('rb') as f:
        while data:=f.read(1024*1024):h.update(data)
    return {'path':str(p),'bytes':p.stat().st_size,'sha256':h.hexdigest()}

def load(p):return json.loads(safe(p).read_text(encoding='utf-8'))

def structural(text,top):
    """Structural module master histogram; not a full Verilog elaborator."""
    text=re.sub(r'/\*.*?\*/|//[^\n]*|\(\*.*?\*\)','',text,flags=re.S)
    modules={};issues=[]
    for m in re.finditer(r'\bmodule\s+('+IDENT+r')\s*\((.*?)\)\s*;(.*?)\bendmodule\b',text,re.S):
        name=m[1].lstrip('\\');body=m[3];counts=Counter();ports={};unparsed=[]
        if re.search(r'\b(?:input|output|inout)\b',m[2]):issues.append('unsupported_ANSI_port_header')
        for st in body.split(';'):
            st=st.strip()
            if not st:continue
            if re.match(r'^(wire|input|output|inout|tri|supply0|supply1)\b',st):
                z=re.match(r'^(input|output|inout)\s*(?:\[\s*(\d+)\s*:\s*(\d+)\s*\])?\s*(.*)$',st,re.S)
                if z:
                    width=abs(int(z[2])-int(z[3]))+1 if z[2] else 1
                    for n in z[4].split(','):
                        if re.fullmatch(IDENT,n.strip()):ports[n.strip()]=(z[1],width)
                        else:issues.append('unsupported_port_declaration')
                continue
            if st.startswith('assign '):continue
            z=re.fullmatch('('+IDENT+r')\s+('+IDENT+r')\s*\((.*)\)\s*',st,re.S)
            if z:counts[z[1].lstrip('\\')]+=1
            else:unparsed.append(st[:80])
        if unparsed:issues.append('unsupported_statements:'+name+':'+str(len(unparsed)))
        modules[name]={'masters':counts,'ports':ports,'unparsed_examples':unparsed[:2]}
    declared=len(re.findall(r'\bmodule\s',text))
    if len(modules)!=declared:issues.append('unsupported_module_header')
    if top not in modules:raise ValueError('top_not_parsed')
    cache={}
    def expand(name,seen=()):
        if name in seen:raise ValueError('recursive_hierarchy')
        if name in cache:return cache[name]
        c=Counter()
        for master,n in modules[name]['masters'].items():
            if master in modules:
                for leaf,k in expand(master,(*seen,name)).items():c[leaf]+=n*k
            else:c[master]+=n
        cache[name]=c;return c
    masters=expand(top)
    return {'status':'partial' if issues else 'supported_structural_scan','cell_count':sum(masters.values()),
            'masters':dict(masters),'modules':len(modules),'top_pin_bits':sum(v[1] for v in modules[top]['ports'].values()),
            'port_bits_by_direction':dict(Counter({d:sum(n for k,n in modules[top]['ports'].values() if k==d) for d in ('input','output','inout')})),
            'issues':issues,'scope':'named or positional structural instances; recursive module multiplicities; no RTL elaboration or equivalence'}

def sdc_profile(p):
    src=ref(p);t=safe(p).read_text(encoding='utf-8');t=re.sub(r'(?m)^\s*#.*$','',t).replace('\\\n',' ')
    commands=[x.strip() for x in re.split('[;\n]',t) if x.strip()]
    clocks=[x for x in commands if re.match(r'create_(generated_)?clock\b',x)]
    periods=[float(m[1]) for x in clocks if (m:=re.search(r'-period\s+([\d.]+)',x))]
    return {'source':src,'clock_commands':clocks,'literal_periods_ns':periods,'clock_commands_count':len(clocks),
            'has_generated_clock':any(x.startswith('create_generated_clock') for x in clocks),
            'constraint_command_counts':dict(Counter(x.split()[0] for x in commands if x.startswith(('set_input_delay','set_output_delay','set_false_path','set_multicycle_path','set_clock_uncertainty','set_clock_groups','set_min_delay','set_max_delay')))),
            'executed':False,'coverage':'static statements only; variable substitution, sourced files and timing coverage not evaluated'}

def expected_hash(z,relative):
    v=z.get('output_sha256');return v.get(relative) if isinstance(v,dict) else v

def inventory(folder,origin):
    own=origin=='registered';d=load(folder/('manifest.json' if own else 'design.json'))
    design=load(folder/'design.json') if (folder/'design.json').is_file() else {}
    inp=d if own else d['inputs'];top=d['top'];name=d.get('case_id',folder.name)
    base=OWN/'third_party/ieda-reference' if own and name=='sky130_gcd' else folder
    row={'case_id':name,'directory':str(folder),'origin':origin,'top':top,'pdk':d.get('pdk') or design.get('pdk'),
         'logical_design_declared':design.get('logical_design',design.get('top',top)),
         'declared_scale':design.get('scale'),'role_declared':design.get('role'),'description':design.get('description'),
         'manifest_source':ref(folder/('manifest.json' if own else 'design.json')),'issues':[]}
    p=safe(base/inp['netlist']);row['netlist']=ref(p)
    candidates=[]
    for filename in ('provenance/conversion.json','provenance/native_2d_preparation.json','provenance/dead_alias_cleanup.json'):
        f=folder/filename
        if f.is_file():
            z=load(f)
            if z.get('statistics'):candidates.append({'statistics':z['statistics'],'source':ref(f),'expected_netlist_sha256':expected_hash(z,inp['netlist'])})
    prep=design.get('input_preparation',{})
    for z in (prep.get('dead_alias_cleanup',{}),prep):
        if z.get('statistics'):candidates.append({'statistics':z['statistics'],'source':ref(folder/'design.json'),'expected_netlist_sha256':expected_hash(z,inp['netlist'])})
    for c in candidates:c['current_netlist_hash_matches']=c['expected_netlist_sha256']==row['netlist']['sha256']
    chosen=next((c for c in candidates if c['current_netlist_hash_matches']),candidates[0] if candidates else None)
    row['historical_statistics']=chosen
    stats=None
    if p.stat().st_size<=MAX_PARSE:
        try:
            scan=structural(p.read_text(encoding='utf-8'),top);row['netlist_scan']=scan
            if scan['status']=='supported_structural_scan':stats=scan;row['counts_kind']='measured_structural_scan'
        except Exception as exc:row['netlist_scan']={'status':'unsupported','reason':str(exc)}
    else:row['netlist_scan']={'status':'not_reparsed_size_budget','limit_bytes':MAX_PARSE}
    if stats is None and chosen:
        stats=chosen['statistics'];row['counts_kind']='hash_bound_historical_statistics' if chosen['current_netlist_hash_matches'] else 'unbound_historical_statistics'
    if stats:
        row['counts']={k:stats.get(k) for k in ('cell_count','modules','top_pin_bits','masters')}
        if chosen:
            old=chosen['statistics'];row['declared_count_matches_current_scan']=row['counts']['cell_count']==old.get('cell_count') if row['counts_kind']=='measured_structural_scan' else None
            macro_names=set(old.get('macros',{}));masters=stats.get('masters',{})
            row['macro_instances']=sum(masters.get(n,0) for n in macro_names)
            row['macro_masters']={n:masters.get(n,0) for n in sorted(macro_names)}
            row['macro_classification_kind']='provenance_macro_master_names_applied_to_counts'
            row['cell_area_um2_declared']=old.get('cell_area_um2')
            if row['declared_count_matches_current_scan'] is False:row['issues'].append('current_count_differs_from_provenance')
    else:row['counts_kind']='unknown';row['counts']={}
    row['statistics_sources']=[{k:v for k,v in c.items() if k!='statistics'} for c in candidates]
    try:row['sdc']=sdc_profile(base/inp['sdc'])
    except Exception as exc:row['issues'].append('SDC:'+str(exc))
    row['floorplan_declared']=design.get('floorplan',{}) if not own else {'core_area':d.get('core_area_microns'),'die_area':d.get('die_area_microns')}
    row['conversion_declared']=design.get('conversion',{})
    row['physical_design_declared']=design.get('physical_design',{})
    package=folder/'benchmark_package.json'
    if package.is_file():
        z=load(package);row['historical_package']={'source':ref(package),'updated_at':z.get('updated_at'),'result_status':z.get('result_status'),'stages':{k:v.get('status') for k,v in z.get('stages',{}).items()},'freshly_executed':False}
    # Only inspect explicit paths. Never execute or follow the private $PDK symlink.
    req=[]
    for key in ('tech_lef','cells_lefs','cell_lefs','libs'):
        values=inp.get(key,[]);values=[values] if isinstance(values,str) else values
        for value in values:
            if '$PDK' in value:
                req.append({'declared':value,'status':'external_PDK_unresolved','common_candidate_exists':False})
                candidate=SHARED/'common/2d_pdk'/str(row['pdk'])/value.replace('$PDK/','')
                try:
                    cp=safe(candidate)
                    if cp.is_file():req[-1].update(common_candidate_exists=True,common_candidate=ref(cp))
                except ValueError:pass
            else:
                try:
                    q=safe(base/value);req.append({'declared':value,'status':'available' if q.is_file() else 'missing','source':ref(q) if q.is_file() else None})
                except ValueError:req.append({'declared':value,'status':'outside_authorized_roots'})
    row['library_paths']=req
    row['unknowns']=['actual hold/setup violations before optimization','routed congestion and DRC for new candidates','calibrated optimal hold cap','electrical fanout and logic depth','signoff timing']
    return row

def main():
    assert os.getuid()==1015
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3));resource.setrlimit(resource.RLIMIT_CPU,(900,900))
    started=time.time();folders=[(p,'shared') for p in sorted((SHARED/'designs').iterdir()) if p.is_dir() and not p.is_symlink()]
    folders += [(p.parent,'registered') for p in sorted((OWN/'cases').rglob('manifest.json')) if '/pdk/' not in str(p)]
    for i,(p,origin) in enumerate(folders):
        try:r=inventory(safe(p),origin)
        except Exception as exc:r={'case_id':p.name,'directory':str(p),'origin':origin,'status':'failed','error':str(exc)}
        print(json.dumps(r,ensure_ascii=False),flush=True)
    print(json.dumps({'record_type':'summary','rows':len(folders),'seconds':time.time()-started,'native_executions':0,'server_writes':0,'source_roots':[str(p) for p in ALLOWED]}),flush=True)

if __name__=='__main__':main()
