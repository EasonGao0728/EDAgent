"""Evidence-only routing capabilities and fail-closed candidate admission.

No native command, repair, retry, or production promotion is performed here.
An experimental improvement is distinct from a validated repair and signoff.
"""
import copy
import hashlib
import json
import math
import re
from pathlib import Path
from .def_validation import read_def, section

VERSION = 'route-quality-v1'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def routing_capabilities(log, requested, before=None, after=None):
    begins=re.findall(r'DetailedRouter[^\n]*Begin iteration (\d+)/(\d+)',log)
    ends=re.findall(r'DetailedRouter[^\n]*End Iteration (\d+)/(\d+)',log)
    cap=requested.get('max_dr_iterations')
    expected=[str(i) for i in range(1,len(begins)+1)]
    verified=(type(cap) is int and 1<=cap<=9 and bool(begins) and begins==ends
              and [i for i,_ in begins]==expected and len(begins)<=cap
              and all(int(n)==cap for _,n in begins))
    tracks_equal=None
    if before is not None and after is not None:
        tracks_equal=before['physical']['TRACKS']==after['physical']['TRACKS']
    return {'schema_version':VERSION,'passed':verified,'required_observations_passed':verified,
        'requested':copy.deepcopy(requested),
        'observed':{'iteration_limit':cap if verified else None,'completed_iterations':len(ends),
                    'iterations':begins,'input_tracks_preserved':tracks_equal,
                    'native_layer_tracks':None,'native_graph':None,'internal_memory_limit_mb':None},
        'native_layer_tracks':None,'native_graph':None,
        'unverified':['native_layer_tracks','native_graph','internal_memory_limit_mb'],
        'repair_actions_enabled':[],
        'scope':'Iteration schedule is log-observed; environment requests do not establish other capabilities'}

def preservation(before_path, after_path):
    before=read_def(before_path);after=read_def(after_path)
    checks={k:before[k]==after[k] for k in ('design','units','die','components','nets','pins')}
    for k in ('ROWS','SPECIALNETS','BLOCKAGES','REGIONS','GROUPS'):
        checks[k]=before['physical'][k]==after['physical'][k]
    routed={r.split()[0]:bool(re.search(r'\bROUTED\b',r)) for r in section(Path(after_path).read_text(),'NETS')}
    checks['multipin_route_records']=all(routed.get(n) for n,ts in after['nets'].items() if len(ts)>1)
    return {'passed':all(checks.values()),'checks':checks,
        'electrical_connectivity_verified':False,
        'not_checked':['full pin/via electrical connectivity','antenna','timing','signoff'],
        'tracks_changed':before['physical']['TRACKS']!=after['physical']['TRACKS']}

def quality_feedback(drc_gate):
    count=drc_gate.get('violation_count')
    reliable=(drc_gate.get('passed') is True and type(count) is int and count>=0)
    clean=reliable and count==0 and drc_gate.get('quality_clean') is True
    return {'schema_version':VERSION,'execution_verified':reliable,
        'supported_drc_clean':clean,'violation_count':count,
        'status':'supported_drc_clean' if clean else 'residual_drc' if reliable else 'unverified',
        'signoff_clean':False,'automatic_repair_enabled':False,'automatic_promotion_enabled':False,
        'next_action':'bounded_isolated_experiment' if reliable and not clean else 'review_missing_evidence' if not reliable else 'verify_connectivity_and_other_quality',
        'unsupported_rules':drc_gate.get('unsupported',[])}

def compare_candidates(baseline,candidate):
    """Both records must be produced from hashed files, never a model estimate.

    A producer change is allowed as the declared experimental factor. Input,
    checker, rule coverage, other controls and resource contracts must match.
    """
    errors=[]
    for key in ('input_sha256','checker_environment_sha256','checked_rules','controls','resource_budget','experiment_factor'):
        if not baseline.get(key) or baseline.get(key)!=candidate.get(key):errors.append('comparison_mismatch:'+key)
    for label,r in (('baseline',baseline),('candidate',candidate)):
        if r.get('execution_completed') is not True:errors.append(label+':execution_incomplete')
        if r.get('structure',{}).get('passed') is not True:errors.append(label+':structure_or_metadata_failed')
        if not r.get('artifact_sha256'):errors.append(label+':artifact_hash_missing')
        for key in ('input_sha256','checker_environment_sha256','artifact_sha256'):
            if not isinstance(r.get(key),str) or not re.fullmatch('[a-f0-9]{64}',r[key]):errors.append(label+':invalid_hash:'+key)
        d=r.get('drc',{});counts=d.get('by_type');total=d.get('total')
        if (type(total) is not int or total<0 or not isinstance(counts,dict)
            or any(type(v) is not int or v<0 for v in counts.values()) or sum(counts.values())!=total):
            errors.append(label+':invalid_drc_counts')
        sec=r.get('seconds');budget=r.get('resource_budget',{}).get('route_seconds')
        if (type(sec) not in (int,float) or not math.isfinite(sec) or sec<0
            or type(budget) not in (int,float) or not math.isfinite(budget) or budget<=0 or sec>budget):errors.append(label+':cost_missing_or_exceeded')
    comparable=not errors
    improved=False;regressions=[]
    if comparable:
        a,b=baseline['drc'],candidate['drc']
        regressions=[k for k in set(a['by_type'])|set(b['by_type']) if b['by_type'].get(k,0)>a['by_type'].get(k,0)]
        improved=b['total']<a['total'] and not regressions
    blockers=list(errors)
    if comparable and not improved:blockers.append('no_nonregressing_drc_improvement')
    if candidate.get('structure',{}).get('electrical_connectivity_verified') is not True:blockers.append('electrical_connectivity_unverified')
    if candidate.get('required_capabilities_verified') is not True:blockers.append('required_capabilities_unverified')
    return {'schema_version':VERSION,'comparable':comparable,'comparison_errors':errors,
        'experimental_improvement':improved,'regressed_rule_types':sorted(regressions),
        'eligible_for_reviewed_promotion':not blockers,'promotion_blockers':blockers,
        'supported_drc_clean':comparable and candidate['drc']['total']==0,
        'signoff_clean':False,'production_modified':False}

def audit_stage(stage,value,work,manifest):
    """Wrap the frozen native producer; correct observations before stage commit."""
    result=copy.deepcopy(value);work=Path(work)
    if stage=='routing':
        before=work/'result/legalization.def';after=work/'result/routing.def';log=work/'result/rt/rt.log'
        requested={'max_dr_iterations':manifest['routing_policy']['max_dr_iterations'],
            'native_layer_tracks':True,'native_graph':manifest['routing_graph'],'internal_memory_limit_mb':8192}
        profile=routing_capabilities(log.read_text(errors='replace'),requested,read_def(before),read_def(after))
        profile['evidence']={'native_log_sha256':sha(log),'binary_sha256':result.get('binary_sha256'),
                             'input_sha256':sha(before),'output_sha256':sha(after)}
        result['routing_profile']=profile
        result['route_preservation']=preservation(before,after)
        if not profile['passed'] or not result['route_preservation']['passed']:result['passed']=False
    elif stage=='drc':result['quality_feedback']=quality_feedback(result.get('drc_gate',{}))
    if stage in ('routing','drc'):
        (work/(stage+'-evidence.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

def context_feedback(state):
    results=state.get('results',{});r=results.get('routing',{}).get('routing_profile',{})
    if r.get('schema_version')!=VERSION:
        r={'schema_version':VERSION,'status':'historical_claim_not_reverified',
           'requested':{k:r.get(k) for k in ('max_dr_iterations','native_layer_tracks','native_graph')},
           'observed':{'native_layer_tracks':None,'native_graph':None},'repair_actions_enabled':[]}
    return {'routing_capabilities':r,'quality_feedback':quality_feedback(results.get('drc',{}).get('drc_gate',{}))}
