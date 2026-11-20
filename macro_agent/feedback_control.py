"""Bounded main-Agent checkpoint branches. No algorithm generation or promotion.

The parent is immutable. Each candidate has the existing linear task controller,
independent workspaces and a shared campaign budget. The LLM requests each segment.
"""
from pathlib import Path
import copy, html, json, time,re
from . import main_task as task
from . import p1_perception as perception

VERSION='p1-feedback-v1'
FILE='feedback-campaign.json'
PAUSES={'export_def','legalization','drc'}
COORDINATORS={'remote_platform.py','remote_service.py','main_decisions.py','main_task.py','task_queries.py','knowledge.py','p1_perception.py','feedback_control.py'}
DENSITIES=(.50,.55,.60,.65,.70)

def apply_adjustment(work,adjustment):
    density=adjustment['density']
    if density not in DENSITIES:raise ValueError('UNREVIEWED_DENSITY')
    p=work/'config/pl_default_config.json';cfg=task.load(p)
    before=cfg['PL']['GP']['Density']['target_density']
    cfg['PL']['GP']['Density']['target_density']=density;task.save(p,cfg)
    return {'parameter':'PL.GP.Density.target_density','before':before,'requested':density,
        'config_before_execution':task.file_ref(p),'native_effect_scope':'configuration passed to native placer; behavioral change must be checked against output',
        'algorithm_changed':False,'constraints_changed':False}

def load(folder):
    p=Path(folder)/FILE
    return task.load(p) if p.exists() else None

def save(folder,c):task.save(Path(folder)/FILE,c)

def inspect(state,folder,kind,stage=None):
    if kind=='input':facts=perception.input_profile(state)
    elif kind=='stage':facts=perception.stage_observation(state,stage)
    elif kind=='quality':facts=perception.hotspots(state)
    else:raise ValueError('UNKNOWN_FEEDBACK_OBSERVATION')
    record={'kind':kind,'state_id':task.state_id(state),'facts':facts}
    eid=task.digest(record);d=Path(folder)/'feedback-evidence';d.mkdir(exist_ok=True)
    task.save(d/(eid+'.json'),record)
    # Keep decision facts outside the lossy conversation window. Full records
    # remain immutable and addressable by digest; only bounded summaries recur.
    index_path=Path(folder)/'feedback-observation-index.json'
    index=task.load(index_path) if index_path.exists() else {}
    key=kind+(':'+str(facts.get('stage',stage)) if kind=='stage' else '')
    index[key]={'kind':kind,'state_id':record['state_id'],'evidence_id':eid,
        'facts':{k:v for k,v in facts.items() if k in ('stage','status','metrics','risk','placement_parameter','count','by_rule','count_consistent','coverage','stage_accepted','gate_errors','reported_counts','recommended_action')},
        'full_record':str(d/(eid+'.json'))}
    task.save(index_path,index)
    return {**record,'evidence_id':eid}

def observation_index(folder,state):
    path=Path(folder)/'feedback-observation-index.json'
    return {k:{**v,'current':v['state_id']==task.state_id(state)} for k,v in (task.load(path) if path.exists() else {}).items()}

def begin(state,folder,req):
    existing=load(folder)
    if existing:return view(folder)
    if state.get('pending'):raise ValueError('PENDING_NATIVE_EXECUTION')
    if state['contract'].get('goal')!='full_backend':raise ValueError('FEEDBACK_REQUIRES_REGISTERED_FULL_BACKEND')
    if state['status'] not in ('running','target_met'):raise ValueError('STOPPED_HISTORY_NOT_MIGRATED')
    if 'fanout' not in state['completed']:raise ValueError('PREPLACEMENT_CHECKPOINT_REQUIRED: continue the original workflow to fanout first')
    if not req.get('reason','').strip():raise ValueError('CAMPAIGN_REASON_REQUIRED')
    c={'schema_version':VERSION,'created_at':time.time(),'status':'open','revision':0,
       'baseline_task':task.file_ref(Path(folder)/'task.json'),'baseline_state_id':task.state_id(state),
       'budget':{'branches':2,'executions':32,'wall_seconds':28800,'model_calls':40},
       'counts':{'branches':0,'executions':0,'model_calls':0},'branches':[], 'events':[],
       'reason':req['reason'],'algorithm_agent_enabled':False,'automatic_promotion_enabled':False}
    save(folder,c);return view(folder)

def guard(folder,c):
    if c['status']!='open':raise ValueError('CAMPAIGN_CLOSED')
    task.verify_refs([c['baseline_task']])
    if time.time()-c['created_at']>c['budget']['wall_seconds']:raise ValueError('CAMPAIGN_WALL_BUDGET')
    if c['counts']['executions']>=c['budget']['executions']:raise ValueError('CAMPAIGN_EXECUTION_BUDGET')

def child(folder,c,branch_id):
    b=next((b for b in c['branches'] if b['branch_id']==branch_id),None)
    if not b:raise ValueError('UNKNOWN_BRANCH')
    return b,task.ROOT/'runs'/b['branch_id']

def view(folder):
    c=load(folder)
    if not c:return {'status':'not_started'}
    branches=[]
    for b in c['branches']:
        _,p=child(folder,c,b['branch_id']);s=task.load(p/'task.json')
        v=task.view(s,p)
        failure=next((e for e in reversed(s.get('events',[])) if e.get('status')=='failed' and e.get('action') not in s['completed']),None)
        branches.append({**b,'status':s['status'],'state_id':task.state_id(s),'completed':s['completed'],
            'latest_failure':failure,
            'observations':observation_index(p,s),
            'allowed_actions':['inspect','compare','stop'] if failure else v['allowed_actions'],'next_stage':None if failure else next((x for x in v['allowed_actions'] if x not in ('stop','recover')),None),
            'latest_observation':task.load(p/'stage-observation.json') if (p/'stage-observation.json').exists() else None})
    baseline=task.load(Path(folder)/'task.json');config=Path(baseline['results']['fanout']['receipt_ref']).parent/'config/pl_default_config.json' if 'fanout' in baseline['results'] else None
    density=task.load(config)['PL']['GP']['Density']['target_density'] if config and config.exists() else None
    choices={'parameter':'PL.GP.Density.target_density','baseline_density':density,'registered_values':list(DENSITIES),
        'baseline_native_density':perception.density_evidence(baseline),
        'source':task.file_ref(config) if config and config.exists() else None,
        'scope':'current readback of preserved pre-placement configuration; new branch freezes these bytes',
        'constraints':['must differ from baseline/current branch','must not be below nominal input cell area/core area','same density is never rerun']}
    return {**c,'observations':observation_index(folder,baseline),'parameter_choices':choices,'events':c['events'][-6:],'branches':branches,'campaign_state_id':task.digest({'revision':c['revision'],'branches':[(b['branch_id'],b['state_id']) for b in branches]}),
            'next_step':'Inspect observations; select continue, another eligible branch, compare, or stop. No automatic retry.'}

def branch(state,folder,req):
    c=load(folder)
    if not c:raise ValueError('BEGIN_CAMPAIGN_FIRST')
    action=req.get('action_id')
    if not action:raise ValueError('ACTION_ID_REQUIRED')
    # Idempotence is checked before current-state rejection.
    fingerprint=task.digest({k:req.get(k) for k in ('source_branch','density','evidence_id','reason','expected_effect')})
    old=next((b for b in c['branches'] if b['action_id']==action),None)
    if old:
        if old['fingerprint']!=fingerprint:raise ValueError('BRANCH_IDENTITY_COLLISION')
        return view(folder)
    guard(folder,c)
    if req.get('campaign_state_id')!=view(folder)['campaign_state_id']:raise ValueError('STALE_CAMPAIGN')
    if c['counts']['branches']>=c['budget']['branches']:raise ValueError('BRANCH_BUDGET')
    if not req.get('reason','').strip() or not req.get('expected_effect','').strip():raise ValueError('BRANCH_RATIONALE_REQUIRED')
    density=req.get('density')
    if type(density) not in (int,float) or density not in DENSITIES:raise ValueError('UNREVIEWED_DENSITY: choose '+str(DENSITIES))
    source=Path(folder);source_state=state
    if req.get('source_branch'):
        _,source=child(folder,c,req['source_branch']);source_state=task.load(source/'task.json')
    if source_state.get('pending'):raise ValueError('SOURCE_PENDING')
    if not re.fullmatch('[a-f0-9]{64}',str(req.get('evidence_id'))):raise ValueError('INVALID_EVIDENCE_ID')
    evidence=source/'feedback-evidence'/(req['evidence_id']+'.json')
    if not evidence.is_file():raise ValueError('CURRENT_OBSERVATION_REQUIRED')
    e=task.load(evidence)
    if task.digest(e)!=req['evidence_id'] or e['state_id']!=task.state_id(source_state):raise ValueError('STALE_OR_CHANGED_OBSERVATION')
    if e['kind'] not in ('input','stage','quality'):raise ValueError('INVALID_BRANCH_EVIDENCE')
    backend=task.task_backend(source_state);stages=list(backend.STAGES);idx=stages.index('placement');prefix=stages[:idx]
    if any(s not in source_state['completed'] for s in prefix):raise ValueError('PREPLACEMENT_CHECKPOINT_REQUIRED')
    checkpoint=source_state['results'][prefix[-1]];work=Path(checkpoint['receipt_ref']).parent
    old_density=task.load(work/'config/pl_default_config.json')['PL']['GP']['Density']['target_density']
    previous_requested=source_state['contract'].get('branch_adjustment',{}).get('density',old_density)
    if density==previous_requested:raise ValueError('NO_PARAMETER_CHANGE')
    profile=perception.input_profile(state)
    lower=profile.get('metrics',{}).get('nominal_area_utilization',{}).get('value')
    if lower is None:raise ValueError('INPUT_AREA_UNVERIFIED')
    if density<lower:raise ValueError('DENSITY_BELOW_NOMINAL_INPUT_AREA: target must be at least '+str(lower))
    for old_branch in c['branches']:
        if old_branch['adjustment']['density']==density:raise ValueError('DENSITY_ALREADY_EVALUATED: inspect existing branch; no duplicate native run')
    if req.get('source_branch') and density==old_density:raise ValueError('ORIGINAL_DENSITY_ALREADY_EVALUATED: preserve/reuse baseline instead of rerunning')
    # All original non-coordinator inputs, native producers and native binaries
    # must still match. A platform/LLM interface upgrade is explicitly recorded.
    verify=[r for r in source_state['input_refs'] if Path(r['path']).name not in COORDINATORS and '/dsh/knowledge/' not in r['path'].replace('\\','/')]
    task.verify_refs(verify)
    for s in prefix:
        r=source_state['results'][s];task.verify_refs(r['artifact_refs'])
        if task.load(Path(r['receipt_ref']))!=r:raise ValueError('CHECKPOINT_RECEIPT_CHANGED')
    bid='remote-'+task.digest({'campaign':str(folder),'action':action})[:24];dest=task.ROOT/'runs'/bid
    if dest.exists():raise ValueError('ORPHAN_BRANCH_DIRECTORY: inspect before retry')
    dest.mkdir()
    # Admission/start validates the current tool contract; only the accepted
    # prefix is imported. No downstream placements/routes are seeded or reused.
    task.start(dest,state['contract']['case_id'],goal=state['contract']['goal'])
    s=task.load(dest/'task.json');baseline_physical=perception.physical_sources(state)[2];candidate_physical=perception.physical_sources(s)[2]
    if [(Path(r['path']).name,r['sha256']) for r in baseline_physical]!=[(Path(r['path']).name,r['sha256']) for r in candidate_physical]:raise ValueError('BRANCH_INPUT_MISMATCH')
    adjustment={'schema_version':VERSION,'parent_task':task.file_ref(source/'task.json'),'parent_stage':prefix[-1],
        'checkpoint_receipt':task.file_ref(Path(checkpoint['receipt_ref'])),'density':density,'baseline_density':previous_requested,
        'restart_stage':'placement','invalidated_stages':stages[idx:],'retained_stages':prefix,
        'evidence':task.file_ref(evidence),'reason':req['reason'],'expected_effect_hypothesis':req['expected_effect'],
        'uncertainties':req.get('uncertainties','DRC improvement not guaranteed; timing/signoff unknown')}
    task.save(dest/'branch-adjustment.json',adjustment)
    s['contract']['branch_adjustment']=adjustment;s['input_refs'].append(task.file_ref(dest/'branch-adjustment.json'))
    # Freeze the complete seed workspace now, including config and scripts that
    # old stage receipts did not hash. No writable links are shared downstream.
    seed_refs=[task.file_ref(p) for p in task.workspace_files(work)]
    task.save(dest/'checkpoint-snapshot.json',{'scope':'branch-time complete workspace snapshot','files':seed_refs})
    s['input_refs']+=seed_refs+[task.file_ref(dest/'checkpoint-snapshot.json')]
    s['contract']['all_inputs_hash']=task.digest(s['input_refs']);s['completed']=prefix
    s['results']={k:copy.deepcopy(source_state['results'][k]) for k in prefix};s['accepted_work']=str(work)
    s['events'].append({'action':'import_verified_checkpoint','parent':adjustment['parent_task'],'retained_stages':prefix,'source_contract':source_state['contract']['backend_version']})
    task.save(dest/'task.json',s)
    c['counts']['branches']+=1;c['revision']+=1
    if req.get('source_branch'):
        old,_=child(folder,c,req['source_branch']);old['disposition']='superseded_preserved'
        c['events'].append({'action':'return_to_preplacement_checkpoint','from_branch':req['source_branch'],'to_branch':bid,'reason':req['reason']})
    c['branches'].append({'branch_id':bid,'action_id':action,'fingerprint':fingerprint,'adjustment':adjustment,'created_at':time.time()})
    c['events'].append({'action':'branch_created','branch_id':bid,'executed_stages':[]});save(folder,c)
    return view(folder)

def execute_segment(folder,req):
    c=load(folder);guard(folder,c);b,p=child(folder,c,req['branch_id']);s=task.load(p/'task.json')
    if b.get('disposition'):raise ValueError('BRANCH_SUPERSEDED_PRESERVED')
    if req.get('state_id')!=task.state_id(s):raise ValueError('STALE_BRANCH')
    if not req.get('reason','').strip():raise ValueError('CONTINUE_REASON_REQUIRED')
    if s['status']!='running' or s.get('pending'):raise ValueError('BRANCH_NOT_RUNNABLE')
    if any(e.get('status')=='failed' and e.get('action') not in s['completed'] for e in s.get('events',[])):raise ValueError('CANDIDATE_STAGE_FAILED_REVIEW_REQUIRED: no implicit native retry')
    executed=[]
    while True:
        guard(folder,c);s=task.load(p/'task.json');v=task.view(s,p)
        allowed=[a for a in v['allowed_actions'] if a not in ('stop','recover')]
        if len(allowed)!=1:raise ValueError('NO_UNIQUE_NEXT_BRANCH_STAGE')
        action=allowed[0];c['counts']['executions']+=int(action!='finish');c['revision']+=1
        c['events'].append({'action':'stage_requested','branch_id':p.name,'stage':action,'reason':req['reason'],'time':time.time()});save(folder,c)
        result=task.dispatch({'run':str(p),'operation':'act','action':action,'state_id':v['state_id'],
            'action_id':req['action_id']+'-'+action,'reason':req['reason']})
        if result.get('action_error'):raise RuntimeError(result['action_error'])
        executed.append(action);s=task.load(p/'task.json')
        observation=perception.stage_observation(s);task.save(p/'stage-observation.json',observation)
        history=p/'observations';history.mkdir(exist_ok=True);record=history/(task.digest(observation)+'.json');task.save(record,observation)
        c['events'].append({'action':'stage_observed','branch_id':p.name,'stage':action,'observation':task.file_ref(record),
            'risk':observation.get('risk'),'metrics':observation.get('metrics')});save(folder,c)
        if action in PAUSES or action=='finish' or observation.get('risk',{}).get('status')=='review_required':break
    c['events'].append({'action':'segment_paused','branch_id':p.name,'executed':executed,'next_decision':'inspect then continue/branch/compare/stop'});save(folder,c)
    return view(folder)

def compare(state,folder,branch_id):
    c=load(folder);task.verify_refs([c['baseline_task']]);b,p=child(folder,c,branch_id);candidate=task.load(p/'task.json')
    base=perception.hotspots(state);trial=perception.hotspots(candidate)
    comparable=(base.get('count_consistent') is True and trial.get('count_consistent') is True and base.get('coverage')==trial.get('coverage'))
    # Coverage status changes with violation count; compare rule/check scope only.
    scope=lambda x:{k:x.get('coverage',{}).get(k) for k in ('checked','unsupported','skipped','check_profile')}
    comparable=base.get('count_consistent') is True and trial.get('count_consistent') is True and scope(base)==scope(trial)
    physical_equal=[r['sha256'] for r in perception.physical_sources(state)[2]]==[r['sha256'] for r in perception.physical_sources(candidate)[2]]
    comparable=comparable and physical_equal
    regressions=[k for k in set(base.get('by_rule',{}))|set(trial.get('by_rule',{})) if trial.get('by_rule',{}).get(k,0)>base.get('by_rule',{}).get(k,0)] if comparable else []
    improved=comparable and trial['count']<base['count'] and not regressions
    conclusion='unverified_candidate' if not comparable else 'quality_regression_reject' if regressions else 'supported_drc_improvement_review_required' if improved else 'no_drc_improvement_keep_baseline'
    if trial.get('stage_accepted') is False:conclusion='candidate_evaluation_failed_reject'
    report={'schema_version':VERSION,'branch_id':branch_id,'baseline':base,'candidate':trial,'physical_inputs_equal':physical_equal,
        'same_rule_scope':scope(base)==scope(trial),'drc_comparable':comparable,'regressed_rules':regressions,
        'supported_drc_improvement':improved,'conclusion':conclusion,'full_candidate_completed':candidate['status']=='target_met',
        'baseline_stage':perception.stage_observation(state,'placement'),'candidate_stage':perception.stage_observation(candidate,'placement') if 'placement' in candidate['completed'] else {'status':'not_accepted'},
        'native_density':{'baseline':perception.density_evidence(state),'candidate':perception.density_evidence(candidate)},
        'parameter_effect':candidate['results'].get('placement',{}).get('parameter_effect'),
        'production_modified':False,'adopted':False,'signoff_clean':False,
        'promotion_blockers':['electrical connectivity signoff unavailable','routed timing unavailable','full foundry DRC coverage unavailable'],
        'baseline_task':c['baseline_task'],'candidate_task':task.file_ref(p/'task.json')}
    task.save(p/'feedback-comparison.json',report)
    c['events'].append({'action':'compared','branch_id':branch_id,'conclusion':conclusion,'evidence':task.file_ref(p/'feedback-comparison.json')});c['revision']+=1;save(folder,c)
    return report

def report(folder):
    c=view(folder);data={'campaign':{**c,'events':load(folder)['events']},'comparisons':[]}
    for b in c.get('branches',[]):
        p=task.ROOT/'runs'/b['branch_id']/'feedback-comparison.json'
        if p.exists():data['comparisons'].append(task.load(p))
    task.save(Path(folder)/'feedback-report.json',data)
    content=html.escape(json.dumps(data,ensure_ascii=False,indent=2))
    (Path(folder)/'feedback-report.html').write_text('<!doctype html><meta charset="utf-8"><title>阶段观察与检查点调整</title><style>body{font:16px system-ui;margin:40px;max-width:1200px}pre{white-space:pre-wrap;word-break:break-word;background:#f0f5fa;padding:20px}</style><h1>主 Agent：输入感知、阶段观察与调整分支</h1><p>iEDA 仅在服务器执行。候选与原任务分离，原结果保持；Algorithm Agent 未启用。DRC 改善与签核是不同结论。</p><pre>'+content+'</pre>',encoding='utf-8')
    return {'report':task.file_ref(Path(folder)/'feedback-report.html'),'campaign':c}

def rpc(state,folder,req):
    op=req['operation']
    if op=='feedback_begin':return begin(state,folder,req)
    if op=='feedback_status':return view(folder)
    if op=='feedback_inspect':
        if req.get('branch_id'):
            c=load(folder);_,folder=child(folder,c,req['branch_id']);state=task.load(folder/'task.json')
        return inspect(state,folder,req['kind'],req.get('stage'))
    if op=='feedback_branch':return branch(state,folder,req)
    if op=='feedback_compare':return compare(state,folder,req['branch_id'])
    if op=='feedback_report':return report(folder)
    if op=='feedback_stop':
        c=load(folder);c['status']='stopped';c['revision']+=1;c['events'].append({'action':'stop_preserve','reason':req.get('reason')});save(folder,c);return report(folder)
    raise ValueError('UNKNOWN_FEEDBACK_OPERATION')
