"""Account-scoped persistent task service; JSON RPC over existing SSH.

Only reviewed task operations are exposed. No LLM, credentials, shell endpoint,
unbounded command endpoint, or second agent loop lives on the server.
"""
from pathlib import Path
from contextlib import contextmanager, nullcontext
import base64
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
TERMINAL={'completed','failed','cancelled','lost'}
task=None


def init():
    global task
    # tmux may have been started by an older shell and does not necessarily
    # inherit this SSH client's PYTHONPATH. Use only our authorized own deps.
    sys.path.insert(0,'/srv/edagent/python')
    from .remote_platform import install
    task=install()


def valid_id(s):
    if not isinstance(s,str) or not re.fullmatch('[a-z0-9_-]{8,80}',s):raise ValueError('Invalid task/job identity')
    return s


def folder_for(s):return ROOT/'runs'/valid_id(s)


@contextmanager
def gate():
    with task.locked(ROOT/'scheduler'):yield


def jobs(folder):
    return sorted((folder/'jobs').glob('*.json'))


def active(folder):
    for p in jobs(folder):
        r=task.load(p)
        if r['status'] not in TERMINAL:return r
    return None


def snapshot(folder):
    if not (folder/'task.json').is_file():return None
    state=task.load(folder/'task.json');value=task.view(state,folder)
    job=active(folder)
    if job:
        value.update(job=job,allowed_actions=[],phase='SERVER_JOB_'+job['status'].upper())
    from .remote_platform import PROFILE
    from .route_quality import context_feedback
    value.update(context_feedback(state))
    from .main_decisions import context
    value['main_decision']=context(state,folder)
    if (folder/'quality-review.json').exists():
        from .quality_review import compact
        value['pre_route_quality_review']=compact(task.load(folder/'quality-review.json'))
    from .feedback_control import load as feedback_load, view as feedback_view
    if feedback_load(folder):value['feedback_campaign']=feedback_view(folder)
    if value.get('latest_evidence',{}):
        if 'routing_profile' in value['latest_evidence']:
            value['latest_evidence']['routing_profile']=value['routing_capabilities']
    value.update(execution_location='server',execution_profile=PROFILE,
        server_task_id=folder.name,local_docker_required=False)
    return value


def submit(folder,request):
    request={k:v for k,v in request.items() if k in ('operation','action','state_id','reason','action_id','plan_id','branch_id','evidence_id')}
    if not request.get('action_id'):raise ValueError('Idempotency key required')
    fingerprint=task.digest({k:v for k,v in request.items() if k!='action_id'})
    jid='job-'+hashlib.sha256((folder.name+':'+request['action_id']).encode()).hexdigest()[:24]
    p=folder/'jobs'/(jid+'.json');p.parent.mkdir(exist_ok=True)
    with gate():
        if p.exists():
            r=task.load(p)
            if r['fingerprint']!=fingerprint:raise ValueError('JOB_IDENTITY_COLLISION')
            return {'job':status_job(folder,jid,gate_held=True),'task':snapshot(folder),'replayed':True}
        for other in (ROOT/'runs').glob('*/jobs/*.json'):
            r=task.load(other)
            if r['status'] not in TERMINAL:raise ValueError('SERVER_BUSY: '+r['job_id']+'; query/cancel it before another native job')
        view=snapshot(folder)
        if request['operation']=='quality_execute':
            from .quality_review import validate
            if not isinstance(request.get('reason'),str) or not 1<=len(request['reason'])<=2000:raise ValueError('QUALITY_REVIEW_REASON_REQUIRED')
            validate(task.load(folder/'task.json'),folder,request['evidence_id'])
        elif request['operation']=='feedback_continue':
            from .feedback_control import load as feedback_load, guard, child
            c=feedback_load(folder);guard(folder,c);_,branch=child(folder,c,request['branch_id'])
            branch_state=task.load(branch/'task.json')
            if task.state_id(branch_state)!=request.get('state_id'):raise ValueError('STALE_BRANCH')
            if branch_state['status']!='running' or branch_state.get('pending'):raise ValueError('BRANCH_NOT_RUNNABLE')
        elif view['state_id']!=request.get('state_id'):raise ValueError('STALE_STATE')
        if request['operation'] in ('feedback_continue','quality_execute'):pass
        elif request['operation']=='local_execute':
            from .local_repair import selected
            plan=selected(task.load(folder/'task.json'),folder,request['plan_id'])
            if plan['status']!='planned':raise ValueError('LOCAL_ALREADY_ATTEMPTED')
        elif request['operation']=='decision_execute':
            from .main_decisions import selected
            _,plan=selected(task.load(folder/'task.json'),folder,request['plan_id'])
            if plan['status']!='planned':raise ValueError('PLAN_ALREADY_EXECUTED: inspect evidence; do not resubmit')
        elif request['operation']=='run':
            if view['status']!='running' or view['pending']:raise ValueError('Task is not runnable')
        elif request.get('action') not in view['allowed_actions']:raise ValueError('Action not allowed')
        if request['operation'] in ('run','act'):
            if view.get('feedback_campaign'):raise ValueError('BASELINE_FROZEN_BY_FEEDBACK_CAMPAIGN')
            if view.get('main_decision',{}).get('decision_required'):
                raise ValueError('MAIN_DECISION_REQUIRED: inspect, discover and submit an evidence-backed plan')
        r={'job_id':jid,'task_id':folder.name,'status':'queued','request':request,
            'fingerprint':fingerprint,'submitted_at':time.time(),'execution_location':'server'}
        task.save(p,r)
        # tmux survives SSH/desktop disconnects. No user-controlled shell text.
        import shlex
        command='cd '+shlex.quote(str(ROOT))+' && exec '+shlex.quote(sys.executable)+' -B -m macro_agent.remote_service worker '+folder.name+' '+jid
        proc=subprocess.run(['tmux','new-session','-d','-s',jid,command],capture_output=True,text=True,timeout=10)
        if proc.returncode:
            r.update(status='failed',error='Worker launch failed: '+proc.stderr[-500:]);task.save(p,r)
        return {'job':r,'task':snapshot(folder),'poll_after_seconds':15,
            'note':'Submission is not completion. Reconnect using the same job_id; no duplicate submission.'}


def status_job(folder,jid,gate_held=False):
    from .remote_native import identity
    p=folder/'jobs'/(valid_id(jid)+'.json');r=task.load(p)
    if r['status']=='running' and identity(r.get('pid',0))!=r.get('start_ticks'):
        # Never treat a missing worker as success or automatically restart it.
        with nullcontext() if gate_held else gate():
            r=task.load(p)
            if r['status']=='running' and identity(r.get('pid',0))!=r.get('start_ticks'):
                r.update(status='lost',error='Worker exited without a terminal receipt; explicit recovery required')
                task.save(p,r)
    if r['status']=='queued' and time.time()-r['submitted_at']>60:
        check=subprocess.run(['tmux','has-session','-t',r['job_id']],capture_output=True,timeout=5)
        if check.returncode:
            r.update(status='lost',error='Queued worker session not found');task.save(p,r)
    return r


def cancel(folder,jid,reason):
    from .remote_native import identity
    p=folder/'jobs'/(valid_id(jid)+'.json')
    with gate():
        r=task.load(p)
        if r['status'] in TERMINAL:return {'job':r,'task':snapshot(folder)}
        task.save(folder/'jobs'/(jid+'.cancel'),{'reason':reason,'time':time.time()})
        if r['status']=='running' and identity(r['pid'])==r['start_ticks']:
            if os.getpgid(r['pid'])!=r['pid']:raise ValueError('Unexpected job process group; refused cancellation')
            os.killpg(r['pid'],signal.SIGTERM)
    # Job worker catches TERM only after its child has exited; bounded escalation
    # addresses the owned group even if the leader has just exited.
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        current=task.load(p)
        if current['status'] in TERMINAL:break
        time.sleep(.15)
    if r.get('pid') and identity(r['pid'])==r.get('start_ticks'):
        os.killpg(r['pid'],signal.SIGKILL)
    with gate():
        current=task.load(p)
        if current['status'] not in TERMINAL:
            current.update(status='cancelled',finished_at=time.time(),reason=reason);task.save(p,current)
        with task.locked(folder):
            state=task.load(folder/'task.json')
            if state['status']!='target_met':
                state.update(status='stopped_with_best',stop_reason=reason,revision=state['revision']+1)
                state['events'].append({'action':'remote_cancel','job_id':jid,'reason':reason,'pending_preserved':True})
                task.save(folder/'task.json',state)
    return {'job':task.load(p),'task':snapshot(folder)}


def worker(task_id,jid):
    from .remote_native import identity
    folder=folder_for(task_id);p=folder/'jobs'/(valid_id(jid)+'.json')
    # tmux's exec process is normally a process-group leader. Establish a new
    # owned group if needed; never cancel tmux's server or other sessions.
    if os.getpgrp()!=os.getpid():os.setpgid(0,0)
    os.environ['AIEDA_NATIVE_HANDLES']=str(folder/'jobs'/jid)
    Path(os.environ['AIEDA_NATIVE_HANDLES']).mkdir(exist_ok=True)
    def interrupted(signum,frame):raise InterruptedError('Explicit remote job cancellation')
    signal.signal(signal.SIGTERM,interrupted)
    with gate():
        r=task.load(p)
        if r['status']!='queued':return
        if (folder/'jobs'/(jid+'.cancel')).exists():
            r.update(status='cancelled',finished_at=time.time());task.save(p,r);return
        r.update(status='running',pid=os.getpid(),start_ticks=identity(os.getpid()),started_at=time.time());task.save(p,r)
    try:
        req=r['request']
        if req['operation']=='quality_execute':
            from .quality_review import run
            result=run(task.load(folder/'task.json'),folder,req)
        elif req['operation']=='local_execute':
            from .local_repair import run
            result=run(task.load(folder/'task.json'),folder,req['plan_id'])
        elif req['operation']=='feedback_continue':
            from .feedback_control import execute_segment
            result=execute_segment(folder,{**req,'action_id':jid})
        elif req['operation']=='decision_execute':
            from .main_decisions import selected,execute,finish_plan
            state=task.load(folder/'task.json');_,plan=selected(state,folder,req['plan_id'])
            if plan['tool_card'].get('native_stage'):
                result=task.dispatch({'run':str(folder),'operation':'act','action':plan['tool_card']['stage'],
                    'state_id':plan['state_id'],'action_id':jid+'-stage','reason':plan['reason']})
                failed=bool(result.get('action_error'))
                finish_plan(folder,plan['plan_id'],{'stage':plan['tool_card']['stage'],
                    'state_id':result['state_id'],'action_error':result.get('action_error')},'failed' if failed else 'completed')
                if failed:raise RuntimeError(result['action_error'])
            else:result=execute(state,folder,req['plan_id'])
        elif req['operation']=='run':
            # Deterministic approved recipe, not a second LLM/Agent loop.
            while True:
                v=snapshot(folder)
                if v['status']!='running':raise RuntimeError('Task stopped: '+v['status'])
                state=task.load(folder/'task.json');plain=task.view(state,folder)
                from .main_decisions import needs_decision,current_plan,store,finish_plan,selected
                if needs_decision(state,folder):
                    r['pause_reason']='main_agent_decision_required';break
                approved=current_plan(state,store(folder))
                if approved:_,approved=selected(state,folder,approved['plan_id'])
                choices=[a for a in plain['allowed_actions'] if a not in ('stop','recover')]
                if len(choices)!=1:raise RuntimeError('No unique approved next stage; stop without guessing')
                action=choices[0]
                result=task.dispatch({'run':str(folder),'operation':'act','action':action,
                    'state_id':plain['state_id'],'action_id':jid+'-'+action,
                    'reason':'Execute user-requested registered server workflow'})
                if result.get('action_error'):raise RuntimeError(result['action_error'])
                if approved and approved['tool_card'].get('native_stage'):
                    finish_plan(folder,approved['plan_id'],{'stage':action,'state_id':result['state_id']})
                if action=='finish':break
        else:
            from .main_decisions import current_plan,store,finish_plan,selected,needs_decision
            state=task.load(folder/'task.json')
            if needs_decision(state,folder):raise ValueError('MAIN_DECISION_REQUIRED')
            approved=current_plan(state,store(folder))
            if approved:_,approved=selected(state,folder,approved['plan_id'])
            result=task.dispatch({**req,'run':str(folder)})
            if approved and approved['tool_card'].get('native_stage')==req.get('action'):
                finish_plan(folder,approved['plan_id'],{'stage':req['action'],'state_id':result['state_id'],
                    'action_error':result.get('action_error')},'failed' if result.get('action_error') else 'completed')
            if result.get('action_error'):raise RuntimeError(result['action_error'])
        with gate():
            r.update(status='completed',finished_at=time.time());task.save(p,r)
    except BaseException as exc:
        with gate():
            r.update(status='cancelled' if (folder/'jobs'/(jid+'.cancel')).exists() else 'failed',
                finished_at=time.time(),error=str(exc));task.save(p,r)
    finally:
        # Receipt is small. Full native logs remain in the task workspaces.
        task.save(folder/'jobs'/(jid+'.result'),{'job':r,'task':snapshot(folder)})


def artifacts(folder):
    state=task.load(folder/'task.json')
    if state['status']!='target_met':
        # An unsuccessful quality review is deliverable evidence, never a
        # certified final DEF. Only these exact reports may leave this branch.
        names=('quality-review.json','quality-review.html')
        if not all((folder/n).is_file() for n in names):raise ValueError('Final artifacts are not accepted')
        review=task.load(folder/'quality-review.json')
        if review.get('status') not in ('review_required','accepted_for_pre_route','failed'):raise ValueError('QUALITY_REVIEW_NOT_FINISHED')
        refs=[{**task.file_ref(folder/n),'name':n,'bytes':(folder/n).stat().st_size} for n in names]
        return {'files':refs,'deliverables':{'quality_review_report':task.file_ref(folder/'quality-review.html')},'status':state['status'],'goal_certified':False}
    refs=[]
    # Exact small package + final outputs; no arbitrary directory download.
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.name not in ('controller.lock','task.json') and p.suffix in ('.html','.svg','.json','.def','.gds','.v'):
            refs.append({**task.file_ref(p),'name':p.name,'bytes':p.stat().st_size})
    delivery=dict(state['deliverables'])
    if (folder/'decision-report.html').exists():delivery['decision_report']=task.file_ref(folder/'decision-report.html')
    if (folder/'feedback-report.html').exists():delivery['feedback_report']=task.file_ref(folder/'feedback-report.html')
    if (folder/'local-repair-report.html').exists():delivery['local_repair_report']=task.file_ref(folder/'local-repair-report.html')
    if (folder/'quality-review.html').exists():delivery['quality_review_report']=task.file_ref(folder/'quality-review.html')
    return {'files':refs,'deliverables':delivery,'status':'target_met'}


def rpc(req):
    op=req['operation']
    if op=='runtime_status':
        from .remote_native import runtime_status
        return runtime_status()
    folder=folder_for(req['task_id'])
    if op in ('context','observe'):
        a=active(folder)
        if a:status_job(folder,a['job_id'])
        return snapshot(folder)
    if op=='job_status':return {'job':status_job(folder,req['job_id']),'task':snapshot(folder)}
    if op=='job_cancel':return cancel(folder,req['job_id'],req.get('reason','user cancellation'))
    if op=='artifacts':return artifacts(folder)
    if op=='quality_inspect':
        from .quality_review import inspect
        with gate():
            if active(folder):raise ValueError('SERVER_JOB_ACTIVE: query the same job')
            return inspect(task.load(folder/'task.json'),folder)
    if op=='quality_execute':
        with gate():state=task.load(folder/'task.json')
        return submit(folder,{**req,'state_id':task.state_id(state)})
    if op=='local_execute':return submit(folder,req)
    if op.startswith('local_'):
        from . import local_repair
        with gate():
            if op=='local_status':return local_repair.status(folder)
            if active(folder):raise ValueError('SERVER_JOB_ACTIVE')
            state=task.load(folder/'task.json')
            if op=='local_inspect':return local_repair.inspect(state,folder)
            if op=='local_plan':return local_repair.plan(state,folder,req)
            raise ValueError('Unknown local repair operation')
    if op=='feedback_continue':return submit(folder,req)
    if op.startswith('feedback_'):
        from .feedback_control import rpc as feedback_rpc
        with gate():
            if active(folder):raise ValueError('SERVER_JOB_ACTIVE: query job_status before feedback decisions')
            return feedback_rpc(task.load(folder/'task.json'),folder,req)
    if op.startswith('decision_'):
        from . import main_decisions as decisions
        with gate():
            if active(folder):raise ValueError('SERVER_JOB_ACTIVE: use job_status')
            state=task.load(folder/'task.json')
            if op=='decision_inspect':return decisions.inspect(state,folder,req.get('kind','summary'),req.get('cursor',0),req.get('limit',10),req.get('name'))
            if op=='decision_catalog':return decisions.catalog(state,folder)
            if op=='decision_plan':return decisions.plan(state,folder,req)
            if op=='decision_cancel':return decisions.cancel_plan(state,folder,req['plan_id'],req['reason'])
            if op=='decision_report':return decisions.report(state,folder)
            if op=='decision_execute':
                _,p=decisions.selected(state,folder,req['plan_id'])
                if p['status'] in ('completed','failed','cancelled'):return {'replayed':True,'plan':p}
                if p['tool_id']!='route_top_met3' and not p['tool_card'].get('native_stage'):
                    return decisions.execute(state,folder,p['plan_id'])
            else:raise ValueError('Unsupported decision operation')
        return submit(folder,{**req,'state_id':task.state_id(state)})
    if op=='reserve_model' and active(folder):
        return {'reserved':False,'reason':'Status-only interaction during durable server job; no native resubmission'}
    if op=='reserve_model' and (folder/'quality-review-control.json').exists():
        with gate():
            p=folder/'quality-review-control.json';c=task.load(p)
            if time.time()-c['created_at']>c['wall_seconds'] or c['model_calls']>=c['model_call_limit']:raise ValueError('QUALITY_REVIEW_MODEL_BUDGET')
            c['model_calls']+=1;task.save(p,c)
            return {'reserved':True,'scope':c['scope']}
    if op=='reserve_model':
        from .feedback_control import load as feedback_load,save as feedback_save
        with gate():
            c=feedback_load(folder)
            if c:
                if c['status']=='open':
                    if c['counts']['model_calls']>=c['budget']['model_calls']:raise ValueError('FEEDBACK_MODEL_BUDGET')
                    c['counts']['model_calls']+=1;feedback_save(folder,c)
                return {'reserved':c['status']=='open','scope':'shared_feedback_campaign'}
    if op=='reserve_model' and (folder/'main-decisions.json').exists():
        from .main_decisions import store,write
        with gate():
            d=store(folder)
            if d['observations'] and d['status']=='open':
                if d['model_calls']>=d['model_call_limit']:raise ValueError('DECISION_MODEL_BUDGET')
                d['model_calls']+=1;write(folder,d)
    if op=='download':
        manifest=artifacts(folder);r=next((f for f in manifest['files'] if f['name']==req['name']),None)
        if not r or req['sha256']!=r['sha256']:raise ValueError('Unaccepted artifact')
        offset=req.get('offset',0)
        if type(offset)!=int or not 0<=offset<=r['bytes']:raise ValueError('Invalid artifact offset')
        with Path(r['path']).open('rb') as f:f.seek(offset);data=f.read(256*1024)
        return {'data':base64.b64encode(data).decode(),'offset':offset,'sha256':r['sha256']}
    if op in ('run','act') and (op=='run' or req.get('action') not in ('finish','stop','recover')):
        return submit(folder,req)
    with gate():
        if active(folder):raise ValueError('SERVER_JOB_ACTIVE: use job_status or job_cancel')
        if op=='act' and req.get('action') not in ('stop','recover'):
            from .main_decisions import needs_decision
            if needs_decision(task.load(folder/'task.json'),folder):raise ValueError('MAIN_DECISION_REQUIRED')
        request={**req,'run':str(folder)};request.pop('task_id',None)
        if op=='start' and 'attachment_inputs' in req:
            # The local proxy hashes user-selected bytes; only exact registered
            # case bytes can be bound. No arbitrary path or script upload.
            from .ieda_stages import REGISTERED_CASES,manifest
            ref,_=REGISTERED_CASES[req['case_id']];m=manifest(req['case_id'])
            names={Path(x).name:x for x in [m['netlist'],m['tech_lef'],*m['cell_lefs'],*m['libs'],m['sdc'],'manifest.json','design.json']}
            rows=[]
            for item in req['attachment_inputs']:
                if item['name'] not in names:raise ValueError('Unexpected attachment name')
                path=ref/names[item['name']]
                if task.file_ref(path)['sha256']!=item['sha256'] or path.stat().st_size!=item['bytes']:raise ValueError('Server input bytes do not match attachment')
                rows.append({**item,'path':str(path),'transport':'ssh_verified_content_reuse',
                    'source_transport':item.get('transport'),'source_local_path':item.get('source_local_path')})
            request['attachment_inputs']=rows
        if op not in ('start','resume','retrieve','query','discover','reserve_model','act'):raise ValueError('Unsupported remote operation')
        existed=(folder/'task.json').exists()
        approved=None
        if op=='act' and existed:
            from .main_decisions import current_plan,store,selected
            state=task.load(folder/'task.json')
            approved=current_plan(state,store(folder))
            if approved and req.get('action') not in ('stop','recover'):
                _,approved=selected(state,folder,approved['plan_id'])
        result=task.dispatch(request)
        if approved and approved['tool_card'].get('native_stage')==req.get('action'):
            from .main_decisions import finish_plan
            finish_plan(folder,approved['plan_id'],{'stage':req['action'],'state_id':result['state_id'],
                'action_error':result.get('action_error')},'failed' if result.get('action_error') else 'completed')
        if op=='start' and not existed:
            from .main_decisions import enable
            enable(folder)
        return result


if __name__=='__main__':
    init()
    if len(sys.argv)==4 and sys.argv[1]=='worker':worker(sys.argv[2],sys.argv[3])
    else:
        try:print(json.dumps({'ok':True,'value':rpc(json.load(sys.stdin))},ensure_ascii=False))
        except Exception as exc:print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False));sys.exit(1)
