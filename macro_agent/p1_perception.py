"""Evidence-backed input, stage and final-quality observations (no native tools).

Geometric proxies are explicitly estimates, not calibrated routability predictors.
Unknown pin directions, timing and rule coverage never become invented numbers.
"""
from collections import Counter
from pathlib import Path
import json, math, re
from . import main_task as task
from .def_validation import read_def, lef_cells

VERSION='p1-perception-v1'

def measurement(value,unit,kind='measured',scope=None):
    return dict(value=value,unit=unit,kind=kind if value is not None else 'unknown',scope=scope)

def physical_sources(state):
    from .ieda_stages import REGISTERED_CASES
    m=state['contract']['case_manifest']
    root=Path(state['contract'].get('input_root') or REGISTERED_CASES[state['contract']['case_id']][0])
    paths=[root/m[k] for k in ('netlist','tech_lef','sdc')]+[root/p for p in m['cell_lefs']+m['libs']]
    refs={r['path']:r for r in state['input_refs']}
    selected=[]
    for p in paths:
        if str(p) not in refs:raise ValueError('PROFILE_INPUT_NOT_FROZEN: '+str(p))
        selected.append(refs[str(p)])
    task.verify_refs(selected)
    return root,m,selected

def input_profile(state):
    from .aes_netlist import parse
    root,m,refs=physical_sources(state)
    result={'schema_version':VERSION,'sources':refs,'state_id':task.state_id(state),
        'functional_type':{'value':m['case_id'],'kind':'declared_metadata','inferred_from_name':False},
        'unknowns':['functional classification is not verified from gate topology','pin-direction fanout','timing closure']}
    try:
        buses=None
        if 'expected_macro_masters' in m:
            from .swerv_backend import cells_and_buses
            _,buses=cells_and_buses(root,m)
        n=parse(root/m['netlist'],buses)
    except ValueError as exc:
        return {**result,'status':'unsupported_netlist','reason':str(exc),'metrics':{}}
    cells={}
    for path in m['cell_lefs']:cells.update(lef_cells(root/path,1000))
    masters=Counter(n['components'].values());missing=sorted(set(masters)-set(cells))
    area=sum(cells[k]['size'][0]*cells[k]['size'][1]*v/1e6 for k,v in masters.items() if k in cells)
    macroarea=sum(cells[k]['size'][0]*cells[k]['size'][1]*v/1e6 for k,v in masters.items() if k in cells and cells[k]['hard_macro'])
    macrocount=sum(v for k,v in masters.items() if k in cells and cells[k]['hard_macro'])
    seq=set()
    # Balanced Liberty cell blocks, not a name-based flip-flop guess.
    for lib in m['libs']:
        text=(root/lib).read_text(encoding='utf-8')
        for match in re.finditer(r'\bcell\s*\(\s*"?([^\s"()]+)"?\s*\)\s*\{',text):
            depth=1;i=match.end();start=i
            while i<len(text) and depth:
                depth+=(text[i]=='{')-(text[i]=='}');i+=1
            if re.search(r'\b(?:ff|latch)\s*\(',text[start:i]):seq.add(match[1])
    degrees=sorted(len(partition) for partition,multiplicity in n['partitions'].items() for _ in range(multiplicity))
    core=m['core_area_microns'];corearea=(core[2]-core[0])*(core[3]-core[1])
    clocks=[];sdc=(root/m['sdc']).read_text(encoding='utf-8')
    for line in sdc.splitlines():
        if line.strip().startswith(('create_clock','create_generated_clock')):clocks.append(line.strip())
    metrics={'instances':measurement(len(n['components']),'count'), 'hard_macros':measurement(macrocount if not missing else None,'count'),
        'cell_area':measurement(area if not missing else None,'um^2'), 'macro_area':measurement(macroarea if not missing else None,'um^2'),
        'core_area':measurement(corearea,'um^2','declared'),
        'nominal_area_utilization':measurement(area/corearea if not missing and corearea>0 else None,'ratio','estimated','LEF cell area/core rectangle; ignores row/blockage availability'),
        'sequential_instances':measurement(sum(masters[k] for k in seq),'count','measured','Liberty ff/latch membership'),
        'net_degree_p95':measurement(degrees[min(len(degrees)-1,math.ceil(.95*len(degrees))-1)] if degrees else 0,'endpoints/net'),
        'net_degree_max':measurement(max(degrees,default=0),'endpoints/net'),
        'electrical_fanout':measurement(None,'loads/net')}
    return {**result,'status':'partial' if missing else 'observed','metrics':metrics,'unresolved_masters':missing,
        'clock_statements':clocks,'clock_constraints_executed':False,'case_reuse_key':task.digest({'physical_inputs':refs,'case':m['case_id']})}

def stage_observation(state,stage=None):
    if not state['completed']:return {'status':'no_accepted_stage','state_id':task.state_id(state)}
    stage=stage or state['completed'][-1]
    if stage not in state['completed']:raise ValueError('STAGE_NOT_ACCEPTED')
    r=state['results'][stage];task.verify_refs(r['artifact_refs'])
    if task.load(Path(r['receipt_ref']))!=r:raise ValueError('STAGE_RECEIPT_CHANGED')
    artifact=Path(r.get('artifact',''))
    result={'schema_version':VERSION,'stage':stage,'state_id':task.state_id(state),'receipt':task.file_ref(Path(r['receipt_ref'])),
        'metrics':{},'risk':{'status':'unknown','calibrated_failure_probability':None,'actions':['inspect','continue','branch','stop']},
        'unknowns':['routed timing','pin-access routability','electrical route connectivity'],'gates':{k:v for k,v in r.items() if k in ('drc_gate','routing_gate','geometry','quality_feedback','transformation')}}
    if artifact.suffix!='.def' or not artifact.exists():return result
    root,m,_=physical_sources(state);d=read_def(artifact);cells={}
    for p in m['cell_lefs']:cells.update(lef_cells(root/p,d['units']))
    pos={};area=0;missing=[];bins=Counter();die=d['die'];u=d['units']
    for name,c in d['components'].items():
        if c['master'] not in cells or not c['placement']:missing.append(name);continue
        cell=cells[c['master']];w,h=cell['size'];_,x,y,o=c['placement']
        if o in ('E','W','FE','FW'):w,h=h,w
        pos[name]=(x+w/2,y+h/2);area+=w*h
        if die and die[2]>die[0] and die[3]>die[1]:
            ix=max(0,min(7,int(8*(x+w/2-die[0])/(die[2]-die[0]))));iy=max(0,min(7,int(8*(y+h/2-die[1])/(die[3]-die[1]))))
            bins[(ix,iy)]+=w*h
    hpwl=0;included=0
    for terminals in d['nets'].values():
        # Exclude nets with IO/unknown endpoints rather than fabricate pin locations.
        if len(terminals)<2 or any(inst not in pos for inst,pin in terminals):continue
        pts=[pos[inst] for inst,pin in terminals];hpwl+=max(x for x,y in pts)-min(x for x,y in pts)+max(y for x,y in pts)-min(y for x,y in pts);included+=1
    diearea=(die[2]-die[0])*(die[3]-die[1]) if die else 0
    result['metrics']={'instances':measurement(len(d['components']),'count'),
        'unplaced_or_unknown_master':measurement(len(missing),'count'),
        'cell_area_over_die':measurement(area/diearea if diearea else None,'ratio','estimated','includes fillers/taps; not placer target density'),
        'center_hpwl_subset':measurement(hpwl/u,'um','estimated','instance centers; excludes all nets with IO; not pin HPWL'),
        'center_hpwl_nets':measurement(included,'count'),
        'max_center_bin_area_ratio':measurement(max(bins.values(),default=0)*64/diearea if diearea else None,'ratio','estimated','8x8 center-assigned bin proxy; may exceed 1; not geometric overlap density'),
        'routing_overflow':measurement(None,'count')}
    notices=[]
    if missing:notices.append('unplaced_or_unknown_master: validate before expensive downstream work')
    if any(isinstance(v,dict) and v.get('passed') is False for v in result['gates'].values()):notices.append('failed_native_or_independent_gate')
    result['risk'].update(status='review_required' if notices else 'no_known_hard_failure',signals=notices,
        interpretation='No known failure does not predict routability; proxies are advisory only.')
    result['artifact']=task.file_ref(artifact)
    result['placement_parameter']=density_evidence(state)
    return result

def density_evidence(state):
    r=state.get('results',{}).get('placement')
    if not r or not r.get('log'):return {'status':'not_observed'}
    log=Path(r['log']);effect=r.get('parameter_effect') or {}
    if effect.get('native_log'):task.verify_refs([effect['native_log']])
    if not log.is_file():return {'status':'log_unavailable'}
    matches=re.findall(r'Target Density\s*:\s*([0-9.]+)',log.read_text(errors='replace'))
    cfg=Path(r['receipt_ref']).parent/'config/pl_default_config.json'
    requested=effect.get('requested')
    if requested is None and cfg.is_file():requested=task.load(cfg)['PL']['GP']['Density']['target_density']
    observed=float(matches[-1]) if matches else None
    return {'status':'observed' if observed is not None else 'unknown','requested':requested,'native_reported':observed,
        'request_matches_native_report':abs(observed-requested)<1e-6 if observed is not None and requested is not None else None,
        'log_source':task.file_ref(log),'source_scope':'current preserved native log; candidate log additionally verified against execution receipt',
        'interpretation':'If actual value differs, do not claim requested value took effect; compare output geometry. No inferred universal clamp rule.'}

# Shared strict streaming reader; large marker files stay outside model context.
from .drc_counts import marker_stream


def hotspots(state):
    if 'drc' not in state['completed']:return failed_drc_observation(state)
    r=state['results']['drc'];path=Path(r['receipt_ref']).parent/'result/report/violations.json'
    refs={v['path']:v for v in r['artifact_refs']}
    if str(path) not in refs:return {'status':'unsupported','reason':'canonical marker artifact not frozen'}
    task.verify_refs([refs[str(path)]])
    byrule=Counter();bylayer=Counter();regions=Counter();examples=[];count=0;located=0
    for kind,obj in marker_stream(path):
        if kind=='header':header=obj;continue
        count+=1;rule=obj.get('type',obj.get('rule',obj.get('violation_type','unknown')));layer=obj.get('layer',obj.get('layer_name','unknown'))
        byrule[str(rule)]+=1;bylayer[str(layer)]+=1
        if len(examples)<3:examples.append(obj)
        box=obj.get('bbox',obj.get('bounding_box'))
        if isinstance(box,list) and len(box)==4 and all(isinstance(v,(int,float)) for v in box):
            units=header.get('dbu_per_micron');
            if isinstance(units,(int,float)) and units>0:
                # 10um grid, one marker per center. This locates symptoms, not root cause.
                x=math.floor((box[0]+box[2])/2/units/10);y=math.floor((box[1]+box[3])/2/units/10)
                regions[(x,y)]+=1;located+=1
    consistent=count==header.get('count')==header.get('summary',{}).get('total')==r['drc_gate'].get('violation_count')
    return {'schema_version':VERSION,'status':'observed' if consistent else 'inconsistent','source':refs[str(path)],
        'count':count,'canonical_summary':header.get('summary'),'coverage':header.get('coverage'),
        'by_rule':dict(byrule),'by_layer':dict(bylayer),'located_markers':located,'unlocated_markers':count-located,
        'hotspots':[{'tile_10um':list(k),'markers':v} for k,v in regions.most_common(10)],'examples':examples,
        'localization':'marker centers on fixed 10um grid; no pin/OBS root-cause attribution',
        'root_cause':'unknown','signoff_clean':False,'count_consistent':consistent}

def failed_drc_observation(state):
    event=next((e for e in reversed(state.get('events',[])) if e.get('action')=='drc' and e.get('status')=='failed'),None)
    if not event:return {'status':'not_measured','reason':'DRC stage not accepted'}
    work=Path(event['work']).resolve()
    if not work.is_relative_to((task.ROOT/'runs').resolve()) or work.parent.name!='attempts':raise ValueError('FAILED_STAGE_PATH_OUTSIDE_RUNS')
    checks=work/'backend-checks.json';markers=work/'result/report/violations.json'
    if not checks.is_file():return {'status':'failed_stage_diagnostic','stage_accepted':False,'error':event.get('error'),'count':None,'count_consistent':False,'reason':'No native checks artifact'}
    data=task.load(checks);gate=data.get('drc_gate',{});refs=[task.file_ref(checks)]
    header={};marker_count=None
    if markers.is_file():
        refs.append(task.file_ref(markers));marker_count=0
        for kind,obj in marker_stream(markers):
            if kind=='header':header=obj
            else:marker_count+=1
    per_rule={k:v.get('violation_count') for k,v in gate.get('runtime',{}).get('per_rule',{}).items()}
    # Historical failure remains immutable. Reinterpretation is a separate, read-only
    # diagnosis, not an accepted receipt or authorization to resume this branch.
    reanalysis=None
    native_summary=work/'result/report/drc_summary.json'
    if native_summary.is_file():
        from .drc_counts import reconcile, runtime_identity
        from .portable_ieda import IMAGE
        from . import ieda_runtime
        producer=None
        if state.get('contract',{}).get('image')==IMAGE:
            try:producer=runtime_identity(ieda_runtime)
            except (ValueError,RuntimeError,OSError):pass
        reanalysis=reconcile(task.load(native_summary),markers.parent,producer)
        reanalysis['producer_binding']='Frozen task image identity plus current verified pinned server runtime; historical native binary was not separately hashed in the failed-stage artifact.'
        refs+=reanalysis['sources']
    task.verify_refs(refs)
    return {'schema_version':VERSION,'status':'failed_stage_diagnostic','stage_accepted':False,
        'error':event.get('error'),'gate_errors':gate.get('errors',[]),'count':None,'count_consistent':False,
        'reported_counts':{'gate':gate.get('violation_count'),'canonical':header.get('count'),'marker_records':marker_count,
            'runtime_per_rule':per_rule,'runtime_rule_sum':sum(v for v in per_rule.values() if isinstance(v,int))},
        'coverage':header.get('coverage',{}),'sources':refs,'count_reanalysis':reanalysis,
        'provenance':'Current hash-verified readback of failed attempt named in task events; not an accepted stage receipt.',
        'localization':'Runtime candidates are not coordinates. No hotspot fabricated; consult count_reanalysis for final evidence.',
        'root_cause':'counter_scope_mismatch_in_agent_gate' if reanalysis and reanalysis['different_scopes_explain_counts'] else 'unknown',
        'signoff_clean':False,'recommended_action':'preserve_historical_failure_review_reanalysis_before_any_new_execution'}
