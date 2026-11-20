"""Main-agent decisions over immutable EDA evidence, separate from native stages.

The model selects a registered action; the host validates it. No Maker, shell,
arbitrary parameters, implicit retries, or production candidate promotion.
"""
from pathlib import Path
import time
from . import main_task as task
from .common import digest
from .route_quality import context_feedback

VERSION = 'main-decision-v1'
CHECKPOINTS = ('macro_placement', 'placement', 'to_hold', 'routing', 'timing', 'finish')


def implementation():
    return {name:task.file_ref(Path(__file__).with_name(name))['sha256']
            for name in ('main_decisions.py','decision_experiments.py','route_quality.py')}


def store(folder):
    p = Path(folder)/'main-decisions.json'
    return task.load(p) if p.exists() else {
        'schema_version': VERSION, 'revision': 0, 'plans': [], 'observations': [],
        'events': [], 'status': 'open', 'created_at': time.time(),
        'budget': {'decisions': 16, 'experiments': 1, 'wall_seconds': 7200},
        'experiments': 0, 'model_calls': 0, 'model_call_limit': 40,
        'workflow_gates_enabled': False}


def write(folder, d):
    task.save(Path(folder)/'main-decisions.json', d)


def enable(folder):
    d = store(folder); d['workflow_gates_enabled'] = True; write(folder, d)


def token(state, d):
    return digest({'state_id': task.state_id(state), 'revision': d['revision']})


def current_plan(state, d):
    return next((p for p in reversed(d['plans']) if p['state_id'] == task.state_id(state)
                 and p['status'] == 'planned'), None)


def needs_decision(state, folder):
    d = store(folder)
    if not d['workflow_gates_enabled']: return False
    view = task.view(state, folder)
    next_stage = next((a for a in view['allowed_actions'] if a not in ('stop','recover')), None)
    p=current_plan(state,d)
    return next_stage in CHECKPOINTS and not (p and p['tool_card'].get('native_stage')==next_stage)


def context(state, folder):
    d = store(folder)
    from .quality_backend import observation
    return {'schema_version': VERSION, 'decision_state_id': token(state, d),
            'status': d['status'], 'decision_required': needs_decision(state, folder),
            'current_plan': current_plan(state, d), 'recent_events': d['events'][-3:],
            'remaining_decisions': max(0,d['budget']['decisions']-len(d['plans'])),
            'remaining_experiments': max(0,d['budget']['experiments']-d['experiments']),
            'latest_observation': d['observations'][-1] if d['observations'] else None,
            'maker_enabled': False, 'production_promotion_enabled': False,'pre_route_quality_gate':observation(state),
            'fact_policy': 'observations are host facts; expected_effect and uncertainties are model hypotheses'}


def inspect(state, folder, kind='summary', cursor=0, limit=10, name=None):
    from .task_queries import query, features
    d = store(folder); backend = task.task_backend(state)
    task.verify_refs([r for r in state['input_refs'] if Path(r['path']).suffix.lower() in ('.lef','.lib','.v','.sdc')])
    if kind == 'summary':
        # Use artifact hashes rather than silently trusting an old mirror.
        if state['completed']: task.verify_refs(state['results'][state['completed'][-1]]['artifact_refs'])
        result = {'features': features(state, backend) if state.get('accepted_work') else None,
                  **context_feedback(state), 'completed_stages': state['completed'],
                  'unknowns':['electrical connectivity signoff','routed timing','full PDK DRC coverage']}
    elif kind in ('terminals','tracks','blockages','route_branches'):
        result = query(state, backend, kind, cursor, limit, name=name)
    elif kind in ('local_short','prior_comparison','experiment_result'):
        from .decision_experiments import evidence
        result = evidence(state, folder, kind, cursor, limit)
    elif kind=='episodes':
        from .task_queries import page
        rows=[]
        for path in sorted(task.ROOT.glob('runs/*/main-decisions.json')):
            other=task.load(path.parent/'task.json')
            if (other['contract']['case_id'],other['contract']['backend_version'])!=(state['contract']['case_id'],state['contract']['backend_version']):continue
            for e in task.load(path)['events']:
                rows.append({'task_id':path.parent.name,'historical':True,'not_current_measurement':True,
                             'source_ref':task.file_ref(path),'event':e})
        result=page(rows,cursor,limit)
    else: raise ValueError('Unsupported decision observation')
    result = {'state_id':task.state_id(state),'kind':kind,'facts':result}
    eid = digest(result); directory = Path(folder)/'decision-evidence'; directory.mkdir(exist_ok=True)
    task.save(directory/(eid+'.json'), result)
    if not any(x['evidence_id']==eid for x in d['observations']):
        d['observations'].append({'evidence_id':eid,'state_id':result['state_id'],'kind':kind})
        d['revision'] += 1; write(folder,d)
    return {**result,'evidence_id':eid,'decision_state_id':token(state,d)}


def catalog(state, folder):
    d = store(folder); v = task.view(state,folder)
    nxt = next((a for a in v['allowed_actions'] if a not in ('stop','recover')),None)
    rows = [{'tool_id':'inspect_design','purpose':'Read current summary or paginated physical facts',
             'eligible':True,'cost':'read only; no iEDA rerun'},
            {'tool_id':'stop_preserve','purpose':'Stop decision search and preserve the accepted production artifact',
             'eligible':True,'cost':'no native computation'},
            {'tool_id':'execute_next_stage','purpose':'Execute only the next frozen, incomplete iEDA stage',
             'eligible':bool(nxt) and v['status']=='running','stage':nxt,
             'native_stage':nxt,
             'cost':'original contract stage budget; previous stages never repeated'}]
    if nxt in ('macro_placement','placement'):
        from .task_queries import features
        from .placement_registry import select_tool
        backend=task.task_backend(state);facts=features(state,backend)
        contract=state['contract'];budget=contract['budget']
        selection=select_tool(stage='macro_placement' if nxt=='macro_placement' else 'standard_cell_placement',
            format_id=contract['case_manifest']['format_id'],required_constraints=['fixed_instances','die_bounds','nonoverlap'],
            movable_hard_macros=facts['movable_hard_macros'],state_id=task.state_id(state),
            budget={'cpu_threads':budget['cpu_threads'],'memory_gb':budget['memory_gb'],
                    'timeout_seconds':max(180,budget.get('container_seconds',180))})
        rows[-1]['eligible']=False
        if selection['selected']:
            rows.append({**selection['selected'],'eligible':True,'native_stage':nxt,'stage':nxt,
                         'purpose':'Execute bounded first case qualification' if selection['selected'].get('experimental_admission') else 'Use this verified case-bound iEDA placement adapter',
                         'admission_evidence':selection['decision_id']})
    from .decision_experiments import availability
    scope = availability(state)
    rows.extend([
        {'tool_id':'reuse_prior_comparison','eligible':scope['available'],
         'purpose':'Revalidate and compare the existing met4 candidate; no rerouting', 'cost':'read and hash existing evidence'},
        {'tool_id':'route_top_met3','eligible':scope['available'] and d['experiments']<d['budget']['experiments'],
         'purpose':'New one-factor top-layer met3 routing experiment on frozen 308-net neighborhood; not full-chip repair',
         'cost':{'threads':4,'address_space_gib':8,'route_seconds':1800,'check_seconds':180},
         'scope':scope,'promotion_allowed':False}])
    from .quality_backend import observation
    quality=observation(state)
    if quality.get('status')=='review_required':
        for row in rows:
            if row.get('native_stage'):
                row.update(eligible=False,blocked_by='HOLD_COST_REVIEW_REQUIRED',quality_evidence=quality)
    if d['status']!='open' or time.time()-d['created_at']>d['budget']['wall_seconds']:
        for row in rows: row['eligible'] = row['tool_id']=='stop_preserve'
    return {'state_id':task.state_id(state),'decision_state_id':token(state,d),'tools':rows,
            'selection_owner':'main_agent','ranking':'none; model must justify choice using a host observation',
            'capability_gap': 'No full-chip automatic repair or Maker; experimental scope must not be generalized'}


def plan(state, folder, req):
    d = store(folder)
    # Retransmission of the same model tool call is read-only.
    if not isinstance(req.get('action_id'),str) or not 1<=len(req['action_id'])<=160:raise ValueError('Decision idempotency key required')
    fingerprint=digest({k:req.get(k) for k in ('decision_state_id','tool_id','evidence_id','reason','expected_effect','uncertainties')})
    prior=next((p for p in d['plans'] if p['action_id']==req.get('action_id')),None)
    if prior:
        if prior['fingerprint']!=fingerprint: raise ValueError('DECISION_IDENTITY_COLLISION')
        return prior
    if req.get('decision_state_id')!=token(state,d): raise ValueError('STALE_DECISION: inspect/discover again')
    if d['status']!='open' or (len(d['plans'])>=d['budget']['decisions'] and req.get('tool_id')!='stop_preserve'):
        raise ValueError('DECISION_BUDGET_OR_CLOSED')
    evidence=next((e for e in d['observations'] if e['evidence_id']==req.get('evidence_id') and e['state_id']==task.state_id(state)),None)
    if not evidence: raise ValueError('CURRENT_OBSERVATION_REQUIRED')
    path=Path(folder)/'decision-evidence'/(evidence['evidence_id']+'.json')
    if digest(task.load(path))!=evidence['evidence_id']: raise ValueError('OBSERVATION_CHANGED')
    card=next((c for c in catalog(state,folder)['tools'] if c['tool_id']==req.get('tool_id') and c['eligible']),None)
    if not card: raise ValueError('TOOL_NOT_ELIGIBLE')
    if req['tool_id']=='route_top_met3' and not all(any(e['kind']==k and e['state_id']==task.state_id(state) for e in d['observations']) for k in ('local_short','prior_comparison')):
        raise ValueError('EXPERIMENT_REQUIRES_LOCAL_AND_PRIOR_EVIDENCE')
    for field in ('reason','expected_effect','uncertainties'):
        if not isinstance(req.get(field),str) or not 1<=len(req[field])<=2000: raise ValueError('Bounded '+field+' required')
    if current_plan(state,d): raise ValueError('PENDING_PLAN: execute or explicitly cancel it first')
    p={k:req[k] for k in ('tool_id','evidence_id','reason','expected_effect','uncertainties','action_id')}
    p.update(plan_id='plan-'+fingerprint[:24],fingerprint=fingerprint,status='planned',
             state_id=task.state_id(state),objective=state['contract']['goal'],tool_card=card,
             task_constraints='unchanged frozen contract',implementation=implementation(),created_at=time.time())
    d['plans'].append(p);d['revision']+=1;write(folder,d)
    return p


def selected(state, folder, plan_id):
    d=store(folder);p=next((p for p in d['plans'] if p['plan_id']==plan_id),None)
    if not p: raise ValueError('Unknown plan')
    if p['state_id']!=task.state_id(state): raise ValueError('STALE_PLAN')
    if p['status']=='planned':
        if p.get('implementation')!=implementation():raise ValueError('PLAN_IMPLEMENTATION_CHANGED: cancel and replan; no native execution')
        card=next((c for c in catalog(state,folder)['tools'] if c['tool_id']==p['tool_id'] and c['eligible']),None)
        if not card:raise ValueError('TOOL_NO_LONGER_ELIGIBLE')
        if card.get('native_stage')!=p['tool_card'].get('native_stage'):raise ValueError('TOOL_STAGE_CHANGED')
    return d,p


def finish_plan(folder, plan_id, result, status='completed'):
    d=store(folder);p=next(p for p in d['plans'] if p['plan_id']==plan_id)
    p.update(status=status,result=result,finished_at=time.time())
    d['events'].append({'plan_id':plan_id,'tool_id':p['tool_id'],'status':status,'result':result})
    d['revision']+=1;write(folder,d)


def cancel_plan(state,folder,plan_id,reason):
    # Cancellation must remain possible after admission or implementation changed.
    # It cannot execute anything or promote a stale artifact.
    p=next((p for p in store(folder)['plans'] if p['plan_id']==plan_id),None)
    if not p:raise ValueError('Unknown plan')
    if p['status']!='planned':raise ValueError('Only unexecuted plans can be cancelled here; use job_cancel for active work')
    finish_plan(folder,plan_id,{'cancel_reason':str(reason)[:2000]},'cancelled')
    return context(state,folder)


def execute(state, folder, plan_id):
    d,p=selected(state,folder,plan_id)
    if p['status'] in ('completed','failed','cancelled'):return {'replayed':True,'plan':p}
    if p['status']!='planned':raise ValueError('PLAN_IN_FLIGHT: query job; no duplicate execution')
    tool=p['tool_id']
    if tool=='execute_next_stage':raise ValueError('Use the persistent stage executor for this approved plan')
    if tool=='stop_preserve':
        result={'stopped':True,'production_modified':False,'quality':context_feedback(state)['quality_feedback']}
        if state['status']=='running':
            task.dispatch({'run':str(folder),'operation':'act','action':'stop','action_id':p['plan_id']+'-stop',
                           'state_id':task.state_id(state),'reason':p['reason']})
            state=task.load(Path(folder)/'task.json')
        d['status']='stopped';write(folder,d)
    elif tool=='inspect_design':result=inspect(state,folder)
    elif tool=='reuse_prior_comparison':
        from .decision_experiments import evidence
        result=evidence(state,folder,'prior_comparison',0,10)
    elif tool=='route_top_met3':
        if d['experiments']>=d['budget']['experiments']:raise ValueError('EXPERIMENT_BUDGET')
        d['experiments']+=1;p['status']='running';d['revision']+=1;write(folder,d)
        from .decision_experiments import run
        try:result=run(state,folder,plan_id)
        except BaseException as exc:
            finish_plan(folder,plan_id,{'error':str(exc),'production_modified':False},'failed');raise
    else:raise ValueError('Unregistered tool')
    finish_plan(folder,plan_id,result)
    return {'plan_id':plan_id,'tool_id':tool,'result':result,'decision':context(state,folder)}


def report(state,folder):
    from html import escape
    d=store(folder)
    data={'decision':d,'task_id':Path(folder).name,'completed_stages':state['completed'],
          'final_def':state.get('final_def'),'quality':context_feedback(state),
          'native_stages_replayed':False,'maker_enabled':False,
          'scope':'Main-agent decision trace; no whole-chip repair or aggregate P1 certification'}
    task.save(Path(folder)/'decision-report.json',data)
    text='<html lang="zh-CN"><meta charset="utf-8"><title>主 Agent 决策闭环</title><style>body{font:16px/1.7 sans-serif;max-width:1100px;margin:40px auto}pre{white-space:pre-wrap;background:#eef3f8;padding:20px}</style><h1>主 Agent 决策闭环</h1><p>感知 → 主侧选择工具 → 服务器执行／证据复用 → 独立质量反馈 → 保留基线或停止。Algorithm Agent 关闭。</p><p>原流程阶段与独立实验分别记录；本报告不代表版图签核。</p><pre>'+escape(__import__('json').dumps(data,ensure_ascii=False,indent=2))+'</pre></html>'
    target=Path(folder)/'decision-report.html';target.write_text(text,encoding='utf-8')
    return {'report':task.file_ref(target),'decision':context(state,folder),'download_via':'mp_task_download'}
