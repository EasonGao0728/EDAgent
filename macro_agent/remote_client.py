"""Desktop transport. SSH credentials and LLM authorization never leave desktop."""
from pathlib import Path, PurePosixPath
import base64
import copy
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import uuid
import time

ROOT=Path(__file__).resolve().parents[1]
CONFIG=Path(os.environ.get('EDAGENT_REMOTE_PROFILE') or ROOT/'environments/remote-server.json')


def config():
    c=json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    if c['enabled'] is not True or c['local_fallback'] is not False:raise ValueError('Remote execution must be enabled without local fallback')
    host, root = c['ssh_host'], c['server_root']
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', host)
            or not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)+/main-agent-remote-v1', root)
            or type(c.get('server_uid')) is not int or c['server_uid'] <= 0):
        raise ValueError('Configure the SSH alias, absolute worker directory and non-root UID')
    return c


def rpc(request):
    c=config();root=c['server_root']
    command='cd '+shlex.quote(root)+' && PYTHONPATH='+shlex.quote(root+':'+str(PurePosixPath(root).parent/'python'))+' python3 -B -m macro_agent.fifo_service'
    try:
        p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','-o','ServerAliveInterval=10',
            '-o','ServerAliveCountMax=2',c['ssh_host'],command],input=json.dumps(request,ensure_ascii=False),
            capture_output=True,text=True,encoding='utf-8',timeout=100,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('REMOTE_REPLY_UNKNOWN: query the same task/job; never resubmit with a new identity') from exc
    try:r=json.loads(p.stdout)
    except ValueError:raise RuntimeError('REMOTE_UNAVAILABLE: '+p.stderr[-600:]) from None
    if not r.get('ok'):raise RuntimeError(r.get('error','Remote operation failed'))
    return r['value']


def local_folder(value):
    p=Path(value).resolve()
    if not p.is_relative_to((ROOT/'runs').resolve()) or p==(ROOT/'runs').resolve():raise ValueError('Task must be under project runs')
    return p


def swerv_screening(operation='status'):
    """Fixed pre-route research study; no arbitrary remote code or task replay."""
    if operation not in ('start','status','metric_start','metric_status','nohold_start','nohold_status','io_start','io_status'):raise ValueError('Invalid study operation')
    c=config();root=c['server_root']
    module='swerv_io_study' if operation.startswith('io_') else 'swerv_no_hold' if operation.startswith('nohold_') else 'swerv_metric_audit' if operation.startswith('metric_') else 'swerv_screening'
    command='cd '+shlex.quote(root)+' && PYTHONPATH='+shlex.quote(root+':'+str(PurePosixPath(root).parent/'python'))+' python3 -B -m macro_agent.'+module
    try:
        p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12',c['ssh_host'],command],
            input=json.dumps({'operation':operation.removeprefix('metric_').removeprefix('nohold_').removeprefix('io_')}),capture_output=True,text=True,encoding='utf-8',timeout=45,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('REMOTE_REPLY_UNKNOWN: query the status operation for the same fixed study; do not launch a new study') from exc
    try:value=json.loads(p.stdout)
    except ValueError:raise RuntimeError('REMOTE_UNAVAILABLE: '+p.stderr[-600:]) from None
    if not value.get('ok'):raise RuntimeError(value.get('error','Study request failed'))
    return value['value']


def bp_multi_routing(operation='status'):
    """Start or inspect the single frozen server qualification branch."""
    if operation not in ('start','status'):
        raise ValueError('Unsupported routing operation')
    c=config()
    directory=c['server_root']+'/qualification-evidence/catalog-v1/tg-study'
    command='cd '+shlex.quote(directory)+' && python3 -B workbench_route.py '+operation
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12',c['ssh_host'],command],
                          capture_output=True,text=True,encoding='utf-8',timeout=35,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        raise RuntimeError(result.stderr[-600:] or 'Unable to query bp_multi continuation')
    return json.loads(result.stdout)


def download_bp_multi(folder, status):
    """Publish the verified qualification files only after full backend readback."""
    manifest=status.get('delivery') or {}
    names={'final.def':'final_def','final.v':'final_netlist','final.gds':'final_gds',
           'placement.svg':'preview','report.html':'report','acceptance.json':'acceptance'}
    files=manifest.get('files',{})
    if (status['run']!='full-lazy-a299a1d992ac' or status['continuation'].get('phase')!='delivery'
            or manifest.get('case')!='bp_multi' or manifest.get('completed')!=17 or manifest.get('run')!=status['run']
            or manifest.get('router')!=status.get('binary_sha256') or set(files)!=set(names)):
        raise ValueError('bp_multi has no verified full backend delivery yet')
    c=config()
    remote=c['server_root']+'/runs/bp-multi-official-pa-v1/'+status['run']+'/backend/delivery/'
    return verified_qualification_files(folder, names, files, c, remote, (status.get('budget') or {}).get('unlimited'))


def verified_qualification_files(folder,names,files,c,remote,unlimited):
    import tempfile
    if set(files)!=set(names):
        raise ValueError('Unexpected qualification manifest')
    folder.mkdir(exist_ok=True,parents=True)
    def digest(p):
        with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
    refs=[]
    with tempfile.TemporaryDirectory(dir=folder) as holder:
        for name,kind in names.items():
            row=files[name]
            if not re.fullmatch('[a-f0-9]{64}',row['sha256']) or type(row['bytes'])!=int or row['bytes']<=0:
                raise ValueError('Invalid remote artifact identity')
            local=folder/name
            cached=local.is_file() and digest(local)==row['sha256']
            if cached and local.stat().st_size!=row['bytes']:
                raise ValueError('Invalid manifest size: '+name)
            if not cached:
                tmp=Path(holder)/name
                subprocess.run(['scp','-q','-C','-o','BatchMode=yes','-o','ConnectTimeout=15',
                                '-o','ServerAliveInterval=30','-o','ServerAliveCountMax=4',
                                c['ssh_host']+':'+remote+name,str(tmp)],check=True,
                               timeout=None if unlimited else 600)
                if tmp.stat().st_size!=row['bytes'] or digest(tmp)!=row['sha256']:raise ValueError('Corrupt transfer: '+name)
                os.replace(tmp,local)
            refs.append({'kind':kind,'name':name,'path':str(local),'bytes':row['bytes'],'sha256':row['sha256']})
    return refs


def hold_calibration(operation='status',phase='api'):
    """Explicit fixed research campaign; no production restart or local fallback."""
    if operation not in ('start','status') or not re.fullmatch('[a-z0-9-]+',phase):raise ValueError('Invalid research operation')
    c=config();root=c['server_root']
    command='cd '+shlex.quote(root)+' && PYTHONPATH='+shlex.quote(root+':'+str(PurePosixPath(root).parent/'python'))+' python3 -B -m macro_agent.hold_calibration'
    try:
        p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12',c['ssh_host'],command],input=json.dumps({'operation':operation,'phase':phase}),capture_output=True,text=True,encoding='utf-8',timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except subprocess.TimeoutExpired as e:raise RuntimeError('REMOTE_REPLY_UNKNOWN: query the same calibration phase; do not resubmit a new identity') from e
    try:value=json.loads(p.stdout)
    except ValueError:raise RuntimeError('REMOTE_UNAVAILABLE: '+p.stderr[-600:]) from None
    if not value.get('ok'):raise RuntimeError(value.get('error','Calibration request failed'))
    return value['value']


def hold_repair(operation='status',phase='build'):
    """Fixed repair study; no arbitrary remote command or duplicate submission."""
    if operation not in ('start','status') or not re.fullmatch('[a-z0-9-]+',phase):raise ValueError('Invalid repair operation')
    c=config();root=c['server_root']
    command='cd '+shlex.quote(root)+' && PYTHONPATH='+shlex.quote(root+':'+str(PurePosixPath(root).parent/'python'))+' python3 -B -m macro_agent.hold_repair'
    try:
        p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12',c['ssh_host'],command],input=json.dumps({'operation':operation,'phase':phase}),capture_output=True,text=True,encoding='utf-8',timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except subprocess.TimeoutExpired as e:raise RuntimeError('REMOTE_REPLY_UNKNOWN: query same repair phase') from e
    try:r=json.loads(p.stdout)
    except ValueError:raise RuntimeError('REMOTE_UNAVAILABLE: '+p.stderr[-600:]) from None
    if not r.get('ok'):raise RuntimeError(r.get('error','Repair request failed'))
    return r['value']


def inspect_rpc(request):
    """A case-specific research observation may be unavailable, not a host crash."""
    try:return rpc(request)
    except RuntimeError as exc:
        if (request.get('operation')!='decision_inspect'
                or request.get('kind') not in ('local_short','prior_comparison','experiment_result')
                or str(exc)!='EXPERIMENT_CAPABILITY_GAP'):
            raise
        return {'available':False,'error':'EXPERIMENT_CAPABILITY_GAP',
                'kind':request['kind'],'task_id':request['task_id'],
                'native_action_submitted':False,
                'next_step':'Use mp_task_observe or summary inspection for this task. This case has no registered experiment evidence; do not infer a routing root cause or retry execution from this result.'}


def atomic(path,obj):
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,path)


def bind(folder):
    mapping=folder/'remote-task.json'
    if mapping.exists():
        r=json.loads(mapping.read_text(encoding='utf-8'))
        if r['server_root']!=config()['server_root']:raise ValueError('Task server binding changed')
        return r
    if (folder/'task.json').exists():raise ValueError('HISTORICAL_LOCAL_TASK: preserved; start a new conversation for server execution')
    folder.mkdir(parents=True,exist_ok=True)
    # Deterministic ID makes simultaneous starts and lost replies reconnectable.
    tid='remote-'+hashlib.sha256(str(folder).lower().encode()).hexdigest()[:24]
    r={'task_id':tid,'server_root':config()['server_root'],'execution_location':'server',
        'schema_version':'remote_task_binding_v1'}
    atomic(mapping,r);return r


def mirror(value,folder):
    if value is None:return None
    view=value.get('task',value)
    if isinstance(view,dict) and 'state_id' in view and 'run' in view:
        view={**view,'server_run':view['run'],'run':str(folder),'execution_location':'server',
            'execution_profile':view.get('execution_profile','ssh-bwrap-v1'),'local_docker_required':False}
        mapping=folder/'remote-task.json'
        binding=json.loads(mapping.read_text(encoding='utf-8')) if mapping.exists() else {}
        if binding.get('purpose')=='evidence_review':
            view.update(interaction_mode='evidence_review',allowed_actions=[],
                review_constraint='Read existing evidence only. No native execution, planning, cancellation or task budget reset.')
        delivery=folder/'remote-delivery.json'
        if view.get('goal_certified') and delivery.is_file():
            saved=json.loads(delivery.read_text(encoding='utf-8'))
            refs=saved['deliverables']
            same=refs.get('final_def',{}).get('sha256')==view.get('final_def',{}).get('sha256')
            verified=same and all(
                Path(r['path']).parent.resolve()==folder.resolve()
                and Path(r['path']).is_file()
                and Path(r['path']).stat().st_size==r['bytes']
                and hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()==r['sha256']
                for r in saved['files'].values())
            if verified:
                view.update(deliverables=refs,final_def=refs['final_def'],download_verified=True,
                    delivery_state='downloaded_and_hash_verified',
                    next_step='Report local deliverables to user; no further polling or download required')
        # This is explicitly a view, never a controller state or accepted checkpoint.
        atomic(folder/'remote-view.json',view)
        if 'task' in value:value={**value,'task':view}
        else:value=view
    return value


def download(folder,tid):
    package=rpc({'operation':'artifacts','task_id':tid})
    missing=[];c=config();stage=folder/'remote-download-pending';stage.mkdir(exist_ok=True)
    for ref in package['files']:
        name=ref['name']
        if not re.fullmatch('[A-Za-z0-9_.-]+',name) or name in ('.','..'):raise ValueError('Invalid artifact name')
        if ref['path']!=c['server_root']+'/runs/'+tid+'/'+name:raise ValueError('Remote artifact outside bound task')
        dest=folder/name
        if dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest()==ref['sha256']:continue
        # A failed transfer may already contain complete files. Reuse only
        # manifest-matched bytes; never publish a partial or stale staging file.
        pending=stage/name
        if pending.is_file() and pending.stat().st_size==ref['bytes'] and hashlib.sha256(pending.read_bytes()).hexdigest()==ref['sha256']:continue
        missing.append(ref)
    if missing:
        # One authenticated compressed stream for the accepted file list. Avoid
        # hundreds of SSH handshakes and repeatedly hashing a large GDS per chunk.
        cmd=['scp','-C','-q','-o','BatchMode=yes','-o','ConnectTimeout=12',
            *[c['ssh_host']+':'+r['path'] for r in missing],str(stage)]
        p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',timeout=600,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if p.returncode:raise RuntimeError('ARTIFACT_TRANSFER_FAILED: '+p.stderr[-500:])
        for ref in missing:
            tmp=stage/ref['name']
            with tmp.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
            if actual!=ref['sha256'] or tmp.stat().st_size!=ref['bytes']:raise ValueError('Downloaded artifact integrity failure')
    publish=[]
    # Include both newly fetched and previously verified staged files. Recheck
    # the complete package before publishing anything, even on a resumed call.
    for ref in package['files']:
        dest=folder/ref['name'];tmp=stage/ref['name']
        if dest.is_file() and dest.stat().st_size==ref['bytes'] and hashlib.sha256(dest.read_bytes()).hexdigest()==ref['sha256']:continue
        if not tmp.is_file() or tmp.stat().st_size!=ref['bytes'] or hashlib.sha256(tmp.read_bytes()).hexdigest()!=ref['sha256']:raise ValueError('Staged artifact integrity failure')
        publish.append((tmp,dest))
    for tmp,dest in publish:os.replace(tmp,dest)
    bypath={r['path']:{**r,'server_path':r['path'],'path':str(folder/r['name'])} for r in package['files']}
    def rewrite(obj):
        if isinstance(obj,dict):
            if obj.get('path') in bypath:return {**obj,**bypath[obj['path']]}
            return {k:rewrite(v) for k,v in obj.items()}
        if isinstance(obj,list):return [rewrite(x) for x in obj]
        return obj
    refs=rewrite(package['deliverables']);atomic(folder/'remote-delivery.json',{'files':bypath,'deliverables':refs})
    value=rpc({'operation':'observe','task_id':tid})
    return mirror({**value,'deliverables':refs,'final_def':refs.get('final_def'),'download_verified':True},folder)


EVIDENCE_REVIEW_OPS=frozenset({'context','observe','query','retrieve','quality_inspect','decision_inspect','feedback_inspect','feedback_status','job_status','reserve_model'})


def evidence_review_gate(folder,binding,op):
    """Separate bounded dialogue; never renew an old execution campaign."""
    if binding.get('purpose')!='evidence_review':return None
    if op not in EVIDENCE_REVIEW_OPS:raise ValueError('EVIDENCE_REVIEW_READ_ONLY: execution and rebinding are disabled')
    if op!='reserve_model':return None
    if time.time()-binding['review_created_at']>3600:raise ValueError('EVIDENCE_REVIEW_MODEL_BUDGET: one-hour review expired')
    slots=folder/'evidence-review-model-calls';slots.mkdir(exist_ok=True)
    for i in range(20):
        try:
            with (slots/str(i)).open('x',encoding='utf-8') as f:json.dump({'reserved_at':time.time()},f)
            return {'reserved':True,'scope':'read-only evidence review','call':i+1,'limit':20}
        except FileExistsError:continue
    raise ValueError('EVIDENCE_REVIEW_MODEL_BUDGET: 20 calls exhausted')


def dispatch(req):
    mode=req.get('mode','task')
    if mode=='ieda_status':return rpc({'operation':'runtime_status'})
    if mode=='ieda_run':raise ValueError('LEGACY_ENTRY_DISABLED: use mp_task_start + mp_task_run; all iEDA executes on server')
    if mode!='task':raise ValueError('Not a remote task operation')
    folder=local_folder(req['run']);op=req['operation']
    mapping=folder/'remote-task.json'
    if op=='bp_multi_quality':
        parent=folder/'final.def'
        if mapping.exists() or not parent.is_file():
            raise ValueError('Open the completed bp_multi delivery conversation')
        with parent.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!='cfa1cf9b26c4862565e94535e6cfe0528f4b769d55ba0198507216318552f5d6':
                raise ValueError('Unqualified parent DEF')
        action=req['action']
        proposal=req.get('proposal_id','')
        if action not in ('diagnose','repair','status') or (action=='repair' and not re.fullmatch('[0-9a-f]{64}',proposal)):
            raise ValueError('Invalid bp_multi quality action')
        c=config()
        script=c['server_root']+'/qualification-evidence/catalog-v1/tg-study/bp_short_agent.py'
        args=['python3','-B',script,action]+([proposal] if action=='repair' else [])
        proc=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12',c['ssh_host'],shlex.join(args)],capture_output=True,text=True,encoding='utf-8',timeout=45)
        if proc.returncode:raise RuntimeError(proc.stderr[-800:])
        review=json.loads(proc.stdout)
        result={'case_id':'bp_multi','short_review':review,'execution_location':'server'}
        manifest=review.get('manifest')
        if manifest and action=='status':
            if (manifest['parent']!='cfa1cf9b26c4862565e94535e6cfe0528f4b769d55ba0198507216318552f5d6'
                    or manifest['parent']!=review['parent'] or manifest['candidate_sha256']!=review['trial']['candidate_sha256']):
                raise ValueError('Unbound bp_multi repair artifacts')
            remote=c['server_root']+'/runs/bp-multi-official-pa-v1/full-lazy-a299a1d992ac/short-study-v1/delivery/'
            names={'bp-multi-hotspot.def.gz':'candidate_def','bp-multi-hotspot.json':'quality_evidence','bp-multi-hotspot.html':'quality_report'}
            result['short_files']=verified_qualification_files(folder,names,manifest['files'],c,remote,True)
        return result
    if op=='bp_multi_route':
        if mapping.exists() or (folder/'task.json').exists():
            raise ValueError('Open the qualification branch in a separate design conversation')
        action=req['action']
        status=bp_multi_routing('status' if action=='delivery' else action)
        value={'qualification':status, 'case_id':'bp_multi','preserved_through':'legalization','execution_location':'server'}
        if action=='delivery':value['qualification_files']=download_bp_multi(folder,status)
        return value
    if mapping.exists():
        reserved=evidence_review_gate(folder,bind(folder),op)
        if reserved is not None:return reserved
    if op=='open':
        if mapping.exists():raise ValueError('Conversation already bound; open a new conversation for a different review purpose')
        if req.get('purpose') not in (None,'quality_review','evidence_review'):raise ValueError('Unknown review purpose')
        tid=req.get('task_id','')
        if not re.fullmatch('remote-[a-f0-9]{24}',tid):raise ValueError('Invalid existing task identity')
        if (folder/'task.json').exists():raise ValueError('Historical local task cannot be rebound')
        mapping=folder/'remote-task.json'
        if mapping.exists() and json.loads(mapping.read_text())['task_id']!=tid:raise ValueError('Conversation already bound to another task')
        value=rpc({'operation':'observe','task_id':tid})
        if not value or not value.get('goal_certified'):raise ValueError('Only a completed remote task can be opened for evidence review')
        folder.mkdir(parents=True,exist_ok=True)
        atomic(mapping,{'task_id':tid,'server_root':config()['server_root'],'execution_location':'server',
                        'schema_version':'remote_task_binding_v1','opened_existing':True,
                        'purpose':req.get('purpose'),'review_created_at':time.time()})
        if req.get('purpose')=='quality_review':
            value['pre_route_quality_review']=rpc({'operation':'quality_inspect','task_id':tid})
        return mirror(value,folder)
    if not (folder/'remote-task.json').exists() and op!='start':
        if op=='context' and not (folder/'task.json').exists():return None
        if op=='observe' and not (folder/'task.json').exists():
            return {'bound':False,'execution_location':'server','native_action_submitted':False,
                    'detail':'本会话还没有绑定生产任务。已登记的资格分支可通过工具库查询。'}
        if op in ('context','observe','query','retrieve') and (folder/'task.json').exists():
            from .main_task import dispatch as historical
            value=historical(req)
            if isinstance(value,dict):value.update(execution_location='historical_local',allowed_actions=[],
                migration_notice='Historical checkpoints preserved. Native execution disabled; use a new remote session.')
            return value
        if op=='reserve_model':return {'reserved':False,'reason':'historical local execution disabled'}
        raise ValueError('HISTORICAL_LOCAL_TASK: no native rerun or silent migration')
    binding=bind(folder);tid=binding['task_id']
    if op=='download':return model_reply(download(folder,tid),folder)
    request={**req,'task_id':tid};request.pop('run',None);request.pop('mode',None)
    if op=='start' and 'attachment_inputs' in req:
        rows=[]
        for item in req['attachment_inputs']:
            p=Path(item['path']);data=p.read_bytes()
            if len(data)!=item['bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Local attachment bytes changed')
            rows.append({k:v for k,v in item.items() if k!='path'}|{'source_local_path':str(p)})
        request['attachment_inputs']=rows
    value=mirror(inspect_rpc(request),folder)
    # Durable job results used to repeat the complete parent contract, while
    # the same verified snapshot is already injected as runtime context. With
    # branch observations this overflowed the context budget after submission.
    # Keep the full mirror on disk; return current execution facts plus a
    # contract reference rather than silently dropping a completed tool call.
    return model_context(value,folder) if op=='context' else model_reply(value,folder)


def project_macro_lists(value,folder):
    """Bound per-instance audit details, never contracts or pass/fail evidence."""
    if not isinstance(value,dict):return value
    view=copy.deepcopy(value);changed=[]
    def visit(node,path):
        if isinstance(node,dict):
            key='restored_unplaced_stdcell_sentinels'
            if isinstance(node.get(key),list) and len(node[key])>20:
                items=node.pop(key);node[key+'_summary']={'count':len(items),'examples':items[:3],
                    'full_list_ref':'macro_audit_snapshot_ref','json_path':path+'/'+key}
                changed.append(path+'/'+key)
            for k,v in node.items():visit(v,path+'/'+k)
        elif isinstance(node,list):
            for i,v in enumerate(node):visit(v,path+'/'+str(i))
    visit(view,'')
    if not changed:return value
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True).encode('utf-8');digest=hashlib.sha256(raw).hexdigest()
    receipts=folder/'rpc-receipts';receipts.mkdir(exist_ok=True);p=receipts/(digest+'.json');p.write_bytes(raw)
    view['macro_audit_snapshot_ref']={'path':str(p),'sha256':digest,'bytes':len(raw),'projected_fields':changed}
    return view


def model_context(value,folder):
    value=project_macro_lists(value,folder)
    if not isinstance(value,dict) or not value.get('feedback_campaign'):return value
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True).encode('utf-8')
    digest=hashlib.sha256(raw).hexdigest();receipts=folder/'rpc-receipts';receipts.mkdir(exist_ok=True)
    receipt=receipts/(digest+'.json');receipt.write_bytes(raw)
    view=copy.deepcopy(value)
    # Once feedback owns control, the parent is frozen. Its old execution plan,
    # delivery inventory and last-stage payload are historical baseline data,
    # not a second active controller. Keep their exact snapshot, while current
    # baseline observations and every candidate decision remain inline below.
    historical_fields=('latest_evidence','accepted_measurements','recent_events','plan','deliverables','main_decision')
    moved=[k for k in historical_fields if k in view]
    for k in moved:view.pop(k)
    view['frozen_baseline_details']={'fields':moved,'reference':'full_snapshot_ref',
        'scope':'Frozen parent execution/delivery history; current feedback observations and branch controls remain inline. mp_task_download returns verified baseline delivery cards.'}
    # Keep every constraint/budget and input hash. Verbose attachment transport
    # paths and repeated event metrics belong in the exact provenance record,
    # not in every inference. Current observations remain complete.
    imported=view.get('contract',{}).get('attachment_import')
    if imported and 'files' in imported:
        imported['files']=[{k:r[k] for k in ('name','sha256','bytes','relative_path','frozen_path') if k in r} for r in imported['files']]
    campaign=view['feedback_campaign']
    campaign['events']=[{k:v for k,v in event.items() if k not in ('metrics','reason')} for event in campaign.get('events',[])]
    for branch in campaign.get('branches',[]):
        latest=branch.get('latest_observation') or {}
        for gate in latest.get('gates',{}).values():
            if not isinstance(gate,dict):continue
            for key in ('added_instances','physical_insertions','reviewed_pdn_pin_additions'):
                if isinstance(gate.get(key),list) and len(gate[key])>20:
                    items=gate.pop(key)
                    gate[key+'_summary']={'count':len(items),'examples':items[:3],
                        'full_list_ref':'full_snapshot_ref; original accepted receipt also referenced by latest_observation.receipt'}
        for observation in branch.get('observations',{}).values():
            facts=observation.get('facts',{})
            if observation.get('current') is False:
                observation.pop('facts',None)
                observation['facts_scope']='Historical state; retrieve full_record when needed. Current facts are in latest_observation.'
            elif facts and all(latest.get(k)==v for k,v in facts.items()):
                observation.pop('facts',None)
                observation['facts_ref']='This branch latest_observation (identical inspected fields).'
    view['full_snapshot_ref']={'path':str(receipt),'sha256':digest,'bytes':len(raw)}
    view['context_projection']='Transport details and historical observations/events referenced by exact snapshot; current observations, constraints and budgets retained without identical duplicates.'
    return view


def model_reply(value,folder):
    """Bound reply size while retaining a hash-addressed exact RPC receipt.

    Runtime context independently supplies the newest state; a submission reply
    may already be older than that snapshot and must not duplicate its history.
    """
    value=project_macro_lists(value,folder)
    if isinstance(value,dict) and value.get('conclusion') and value.get('branch_id') and 'candidate_stage' in value:
        raw=json.dumps(value,ensure_ascii=False,sort_keys=True).encode('utf-8')
        digest=hashlib.sha256(raw).hexdigest();receipts=folder/'rpc-receipts';receipts.mkdir(exist_ok=True)
        receipt=receipts/(digest+'.json');receipt.write_bytes(raw)
        brief={k:v for k,v in value.items() if k not in ('baseline_stage','candidate_stage')}
        for name in ('baseline','candidate'):
            result=value.get(name,{})
            brief[name]={k:result[k] for k in ('status','stage_accepted','count','count_consistent','by_rule','by_layer','reported_counts','gate_errors','source','sources','recommended_action') if k in result}
            brief[name]['coverage_ref']='Full comparison snapshot; same_rule_scope reports the checked equivalence.'
        effect=value.get('parameter_effect') or {}
        brief['parameter_effect']={k:effect[k] for k in ('parameter','before','requested','algorithm_changed','constraints_changed') if k in effect}
        brief['placement_metrics']={name:value.get(name+'_stage',{}).get('metrics') for name in ('baseline','candidate')}
        brief['full_snapshot_ref']={'path':str(receipt),'sha256':digest,'bytes':len(raw)}
        return brief
    if isinstance(value,dict) and (value.get('download_verified') or ('report' in value and isinstance(value.get('campaign'),dict))):
        raw=json.dumps(value,ensure_ascii=False,sort_keys=True).encode('utf-8')
        digest=hashlib.sha256(raw).hexdigest();receipts=folder/'rpc-receipts';receipts.mkdir(exist_ok=True)
        receipt=receipts/(digest+'.json');receipt.write_bytes(raw)
        brief={k:value[k] for k in ('status','state_id','run','goal_certified','download_verified','deliverables','report','execution_location') if k in value}
        if value.get('campaign'):
            c=value['campaign'];brief['campaign']={k:c[k] for k in ('status','campaign_state_id','counts','budget') if k in c}
        brief['full_snapshot_ref']={'path':str(receipt),'sha256':digest,'bytes':len(raw)}
        return brief
    if isinstance(value,dict) and 'job' in value and isinstance(value.get('task'),dict):
        raw=json.dumps(value,ensure_ascii=False,sort_keys=True).encode('utf-8')
        digest=hashlib.sha256(raw).hexdigest();receipts=folder/'rpc-receipts';receipts.mkdir(exist_ok=True)
        receipt=receipts/(digest+'.json');receipt.write_bytes(raw)
        v=value['task'];contract=v.get('contract',{})
        brief={k:v[k] for k in ('state_id','run','status','phase','pending','allowed_actions','goal_certified','execution_location','execution_profile') if k in v}
        brief['contract_ref']={k:contract[k] for k in ('case_id','goal','backend_version','all_inputs_hash','budget','hard_constraints') if k in contract}
        c=v.get('feedback_campaign')
        if c:
            brief['feedback_campaign_ref']={'campaign_state_id':c['campaign_state_id'],'counts':c['counts'],
                'branches':[{k:b.get(k) for k in ('branch_id','state_id','status','completed','next_stage','disposition')} for b in c['branches']]}
        brief['full_snapshot_ref']={'path':str(receipt),'sha256':digest,'bytes':len(raw)}
        return {**value,'task':brief}
    return value


if __name__=='__main__':
    try:print(json.dumps({'ok':True,'value':dispatch(json.load(sys.stdin))},ensure_ascii=False))
    except Exception as exc:print(json.dumps({'ok':False,'error':str(exc),'code':'remote_execution_error'},ensure_ascii=False));sys.exit(1)
