"""UI-independent stage-one task controller. DSH and CLI call the same dispatch API.

LLM selects allowed actions; this host owns contracts, execution, verification,
budgets, durable receipts and final acceptance. No model inference in this module.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from .common import digest
from . import ieda_stages as backend

ROOT = Path(__file__).resolve().parents[1]

def task_backend(state):
    if state['contract'].get('goal')=='full_backend':
        from .full_backend import for_case
        return for_case(state['contract']['case_id'],state['contract'].get('input_root'))
    if state['contract'].get('goal')=='routed_def':
        from .routed_stages import for_case
        return for_case(state['contract']['case_id'],state['contract'].get('input_root'))
    return backend.for_case(state['contract']['case_id'], state['contract'].get('input_root'))


def save(path, value):
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def file_ref(path):
    with path.open('rb') as stream:
        checksum=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'path':str(path),'sha256':checksum}


def compact_verified(path):
    """Lossless storage only; never share writable inodes between attempts."""
    if os.name!='nt' or path.stat().st_size<1024**2:return False
    before=file_ref(path)['sha256']
    binary=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/compact.exe'
    result=subprocess.run([str(binary),'/C','/EXE:LZX','/F','/Q',str(path)],
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise OSError('WORKSPACE_COMPRESSION_FAILED: '+str(path))
    if file_ref(path)['sha256']!=before:raise ValueError('Compression changed file content: '+str(path))
    return True


def workspace_files(folder):
    folder=Path(folder).resolve()
    files=[]
    for p in folder.rglob('*'):
        if 'log' in p.relative_to(folder).parts:continue
        if p.is_symlink() or not p.resolve().is_relative_to(folder):
            raise ValueError('Workspace links are not supported: '+str(p))
        if p.is_file():files.append(p)
    return sorted(files)


def workspace_space_required(folder):
    files=workspace_files(folder)
    return 2*max((p.stat().st_size for p in files),default=0)+256*1024**2


def clone_workspace(source,destination):
    source=Path(source);destination=Path(destination)
    required=workspace_space_required(source)
    if shutil.disk_usage(destination.parent).free<required:
        raise OSError(f'WORKSPACE_SPACE_REQUIRED: {required} bytes free before copying; native execution has not started')
    def copy_file(src,dst):
        src=Path(src);dst=Path(dst)
        expected=file_ref(src)['sha256']
        shutil.copy2(src,dst)
        compact_verified(dst)
        if file_ref(dst)['sha256']!=expected:raise ValueError('Workspace copy changed content: '+str(src))
        return str(dst)
    shutil.copytree(source,destination,copy_function=copy_file,
        ignore=shutil.ignore_patterns('log','stage-receipt.json','storage-seal.json'))


def seal_workspace(folder):
    """Compress only a finished attempt and verify every compressed file."""
    count=0
    for path in workspace_files(folder):
        if compact_verified(path):count+=1
    result={'method':'NTFS LZX with SHA256 before/after' if os.name=='nt' else 'unchanged',
            'compressed_files':count,'contents_unchanged':True,'shared_writable_files':False}
    save(Path(folder)/'storage-seal.json',result)
    return result


def stage_failure_limit(state,stage):
    """Only an explicitly frozen SWERV approval permits a third routing attempt."""
    approval=state['contract'].get('authorized_routing_retry')
    if not approval or stage!='routing':return 2
    if state['contract']['case_id']!='swerv_nangate45':raise ValueError('Retry approval case mismatch')
    if approval not in state['input_refs']:raise ValueError('Retry approval is not frozen')
    verify_refs([approval]);p=Path(approval['path']);e=load(p)
    if (p.name!='approved-budget-extension-6h.json' or p.parent.name!=e.get('task_id') or
        e.get('case_id')!='swerv_nangate45' or e.get('routing_attempt_limit')!=3 or
        e.get('routing_seconds')!=21600 or not e.get('authorization') or
        time.time()>=e.get('expires_at',0)):
        raise ValueError('Invalid or expired explicit retry approval')
    return 3


def resume_task(state,folder,request):
    if state['status']!='stopped_with_best' or state.get('pending'):
        raise ValueError('RESUME_REJECTED: task must be stopped without an uncertain execution')
    if request.get('state_id')!=state_id(state):raise ValueError('STALE_STATE: observe before resume')
    if not request.get('reason','').strip():raise ValueError('Resume reason required')
    backend=task_backend(state);budget=state['contract']['budget']
    if time.time()-state['created_at']>=budget['wall_seconds'] or state['counts']['executions']>=budget['executions'] or state['counts']['model_calls']>=budget['model_calls']:
        raise ValueError('RESUME_BUDGET_EXHAUSTED: original budgets are never reset')
    if state['contract']['backend_version']!=backend.BACKEND_VERSION or state['contract']['image']!=backend.rt.IMAGE:
        raise ValueError('RESUME_BACKEND_CHANGED')
    next_stage=next((s for s in backend.STAGES if s not in state['completed']),None)
    if next_stage is None or state['failure_counts'].get(next_stage,0)>=stage_failure_limit(state,next_stage):
        raise ValueError('RESUME_REJECTED: no retryable remaining stage')
    if state['completed']!=backend.STAGES[:len(state['completed'])]:raise ValueError('Checkpoint stage sequence changed')
    verify_refs(state['input_refs'])
    for stage in state['completed']:
        result=state['results'][stage]
        verify_refs(result['artifact_refs'])
        if load(Path(result['receipt_ref']))!=result:raise ValueError('Checkpoint stage receipt changed: '+stage)
    if not state.get('accepted_work'):raise ValueError('No accepted checkpoint to resume')
    if shutil.disk_usage(folder).free<workspace_space_required(state['accepted_work']):
        raise OSError('RESUME_SPACE_UNAVAILABLE: reclaim space before resuming')
    if any(n.startswith('aieda-') for n in backend.rt.invoke(['ps','--format','{{.Names}}']).splitlines()):
        raise ValueError('RESUME_NATIVE_JOB_ACTIVE: wait for existing native jobs')
    before=folder/'task.json';checkpoint=folder/'checkpoints';checkpoint.mkdir(exist_ok=True)
    saved=checkpoint/('before-resume-'+str(state['revision'])+'-'+uuid.uuid4().hex[:8]+'.json')
    saved.write_bytes(before.read_bytes())
    controller=file_ref(Path(__file__))
    if not any(r['path']==controller['path'] for r in state['input_refs']):
        state['input_refs'].append(controller)
        state['contract']['all_inputs_hash']=digest(state['input_refs'])
    state['status']='running';state['revision']+=1
    state['events'].append({'action':'resume','reason':request['reason'],'status':'running',
        'previous_stop_reason':state.get('stop_reason'),'checkpoint':file_ref(saved),
        'controller':controller,'native_stages_reused':list(state['completed']),
        'budgets_reset':False,'inputs_and_all_accepted_receipts_verified':True})
    save(folder/'task.json',state)
    return view(state,folder)


def verify_refs(refs):
    for ref in refs:
        path=Path(ref['path'])
        if not path.is_file() or file_ref(path)['sha256']!=ref['sha256']:
            raise ValueError('Artifact/input changed: '+str(path))


@contextmanager
def locked(folder):
    import msvcrt
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'task.lock').open('a+b') as stream:
        if stream.seek(0,2)==0:
            stream.write(b'0');stream.flush()
        stream.seek(0)
        try: msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError: raise ValueError('TASK_BUSY: another action is running') from None
        try: yield
        finally:
            stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)


def state_id(state):
    return digest({k:state[k] for k in ('contract','revision','completed','status')})


def view(state, folder):
    backend=task_backend(state)
    pending=state.get('pending')
    next_stage=next((stage for stage in backend.STAGES if stage not in state['completed']),None)
    if state['status']!='running':
        actions=[]
    elif pending: actions=['recover','stop']
    elif time.time()-state['created_at']>state['contract']['budget']['wall_seconds']: actions=['stop']
    elif state['counts']['executions']>=state['contract']['budget']['executions']: actions=['finish','stop'] if next_stage is None else ['stop']
    else: actions=[next_stage if next_stage else 'finish','stop']
    phase='UNCERTAIN' if pending else ('TARGET_MET' if state['status']=='target_met' else (next_stage or 'await_finish' if state['status']=='running' else state['status']))
    latest=state['results'].get(state['completed'][-1]) if state['completed'] else None
    if latest:
        latest={k:v for k,v in latest.items() if k!='artifact_refs'}
        if 'independent' in latest:
            latest={**latest,'independent':{k:v for k,v in latest['independent'].items() if k!='physical_insertions'}}
    measurements={k:v for k,v in state['results'].get('validate',{}).items() if k in ('backend','independent','receipt_ref')}
    if 'independent' in measurements:
        measurements['independent']={k:v for k,v in measurements['independent'].items() if k!='physical_insertions'}
    return {'schema_version':'main_task_view_v1','run':str(folder),'state_id':state_id(state),'phase':phase,
            'status':state['status'],'contract':state['contract'],'counts':state['counts'],
            'allowed_actions':actions,'plan':[{'stage':stage,'status':'validated' if stage in state['completed'] else 'pending'} for stage in backend.STAGES],
            'latest_evidence':latest,
            'accepted_measurements':measurements,
            'recent_events':state['events'][-4:], 'history_omitted':max(0,len(state['events'])-4),
            'history_ref':str(folder/'task.json'),'pending':pending,'goal_certified':state['status']=='target_met',
            'final_def':state.get('final_def'),'deliverables':state.get('deliverables'),'overall_phase1_certified':False,
            'goal_scope':'registered case only; macro and aggregate phase-one gates require separate evidence',
            'macro_placement_verified':bool(state['results'].get('macro_placement',{}).get('independent_macro_check',{}).get('passed')),
            'unknown_metrics':{'timing':None,'power':None,'routed_congestion':None},
            'limitations':(['Three public research SRAM hard macros; first fullflow qualification experiment'] if state['contract']['case_id']=='swerv_nangate45' else ['Two-real-SRAM registered placement fixture; no PDN or routing acceptance'] if state['contract']['case_id']=='sky130_sram_pair' else ['This registered standard-cell case has zero hard macros'])+['No timing or manufacturing signoff','Supported case package only, not arbitrary netlists']+
                (['Registered full backend workflow; abstract GDS only; RCX, routed timing, power and IR not qualified'] if state['contract'].get('goal')=='full_backend' else ['Experimental routed DEF subset; native GDS, fanout/DRV/hold parity and overall phase-one acceptance pending'] if state['contract'].get('goal')=='routed_def' else ['No routing acceptance'])}


def start(folder,case_id,attachment_inputs=None,goal='placement_def'):
    if goal not in ('placement_def','routed_def','full_backend'):raise ValueError('unsupported_goal')
    from .aes_backend import CASES as AES_CASES,require_qualification
    if case_id in AES_CASES:
        if goal!='full_backend':raise ValueError('Registered AES requires full_backend goal')
        require_qualification(case_id)
    elif case_id=='swerv_nangate45':
        if goal!='full_backend':raise ValueError('Registered SWERV requires full_backend goal')
        from .swerv_backend import preflight
        preflight(ROOT/'cases/ibench'/case_id)
    elif goal in ('routed_def','full_backend') and case_id!='ibench_gcd_legacy':raise ValueError(goal+' requires registered HD GCD')
    from .ieda_stages import REGISTERED_CASES
    if case_id not in REGISTERED_CASES: raise ValueError('unsupported_case: phase one permits registered iEDA-only input packages')
    if (folder/'task.json').exists():
        state=load(folder/'task.json')
        if state['contract']['case_id']!=case_id:raise ValueError('Task already bound to another case; create a new session')
        if state['contract'].get('goal','placement_def')!=goal:raise ValueError('Task already bound to another goal; create a new session')
        return view(state,folder)
    attachment_import = None
    if attachment_inputs is not None:
        from .attachment_inputs import freeze_attachments
        attachment_import = freeze_attachments(folder, case_id, attachment_inputs)
    backend=task_backend({'contract':{'case_id':case_id,'goal':goal, 'input_root':attachment_import['input_root'] if attachment_import else None}})
    case_manifest=backend.manifest()
    refs=[file_ref(p) for p in backend.input_files()]+[file_ref(Path(__file__))]
    contract={'schema_version':'task_spec_v2','case_id':case_id,'top':case_manifest['top'],'backend_version':backend.BACKEND_VERSION,
              'input_kind':'gate_level_verilog','inputs':refs[:5], 'all_inputs_hash':digest(refs),
              'goal':goal,'target':'registered_case_'+goal+'_and_preview','units':'DBU from DEF; floorplan configuration in microns',
              'eda_backend_policy':['iEDA'],'case_manifest':case_manifest,
              'hard_constraints':['preserve input instances and normal-net connectivity','preserve fixed cells',
                                  'no unplaced instances','no rectangle overlaps','inside die','pass iPL four placement checks'],
              'die_area_microns':case_manifest['die_area_microns'],'core_area_microns':case_manifest['core_area_microns'],
              'maker_enabled':False,'evaluation_stage':'real_standard_cell_placement',
              'budget':case_manifest['budget'],
              'stop_rules':['user_stop','wall_budget','execution_budget','repeated_stage_failure'],
              'image':backend.rt.IMAGE}
    if goal in ('routed_def','full_backend'):
        contract.update(
            evaluation_stage='registered_routed_def_subset',
            experimental=True,
            approved_logical_transformations={
                'cts':{'clock_net':'clk','buffer_master':'sky130_fd_sc_hd__buf_1',
                       'input_pin':'A','output_pin':'X','proof':'contract buffer tree; preserve original endpoints'},
                'other_stages':'no logical reconnection'},
            required_backend_gates=['independent_flat_netlist_import','placement_validation',
                                    'approved_cts_topology','route_complete','zero_supported_drc_violations',
                                    'no_drc_counter_discrepancy','routed_def_roundtrip'],
            full_backend_certified=False)
        contract['hard_constraints'][0]='preserve original logical instances and connectivity modulo the approved CTS buffer tree'
        if goal=='full_backend':
            contract.update(evaluation_stage='registered_full_backend_workflow',experimental=False,
                required_backend_gates=contract['required_backend_gates']+['fanout_semantic_identity','drv_hold_semantic_identity_and_native_reports','native_abstract_gds_readback'],
                qualification_scope=case_manifest['full_backend_policy'])
        if case_id in AES_CASES or case_id=='swerv_nangate45':
            contract['hard_constraints'][0]='preserve original logical instances and electrical endpoints modulo approved non-inverting buffers'
            contract.update(approved_logical_transformations={
                'fanout_cts_drv_hold':{'buffer_masters':['sky130_fd_sc_hd__buf_1','sky130_fd_sc_hd__buf_8'],
                    'input_pin':'A','output_pin':'X','proof':'preserve every original electrical endpoint partition after buffer contraction'},
                'other_stages':'no logical reconnection'},
                acceptance_mode='flow_reproduction_separate_from_physical_quality',
                required_backend_gates=['independent_flat_alias_endpoint_import','placement_validation','approved_buffer_contraction',
                    'native_routing_complete_all_nets','supported_drc_executed_and_reported','no_drc_counter_discrepancy','routed_def_roundtrip','native_abstract_gds_readback'])
        if case_id=='swerv_nangate45':
            from .swerv_backend import BUFFERS
            contract.update(experimental=True,qualification_status='first_case_run_pending',
                approved_logical_transformations={'fanout_cts_drv_hold':{'buffer_masters':list(BUFFERS),'input_pin':'A','output_pin':'Z','proof':'preserve original endpoint partitions after buffer contraction'},'other_stages':'no logical reconnection'})
            contract['required_backend_gates'].append('native_macro_geometry_and_identity')
    if attachment_import:
        contract.update(input_source='conversation_attachments', input_root=attachment_import['input_root'], attachment_import=attachment_import)
    state={'contract':contract,'input_refs':refs,'revision':0,'created_at':time.time(),'status':'running',
           'completed':[],'results':{},'counts':{'executions':0,'model_calls':0},'pending':None,'receipts':{},'events':[],
           'failure_counts':{},'accepted_work':None}
    save(folder/'task.json',state)
    return view(state,folder)


def commit(state,folder,result,action_id,fingerprint):
    stage=state['pending']['action']
    state['completed'].append(stage)
    state['results'][stage]=result
    state['accepted_work']=state['pending']['work']
    state['pending']=None
    state['revision']+=1
    state['events'].append({'action':stage,'status':'validated_and_committed','evidence_ref':result['receipt_ref'],'action_id':action_id})
    state['receipts'][action_id]={'fingerprint':fingerprint,'committed':True}
    save(folder/'task.json',state)
    return view(state,folder)


def retrieve(folder,state,query,version):
    from .knowledge import retrieve as verified_retrieve
    return verified_retrieve(folder,state,query,version)


def dispatch(request, *, execute=None):
    folder=Path(request['run']).resolve()
    if not folder.is_relative_to((ROOT/'runs').resolve()): raise ValueError('Task workspace must be inside runs')
    mode=request['operation']
    if mode=='context' and not (folder/'task.json').exists(): return None
    with locked(folder):
        if mode=='start': return start(folder,request['case_id'],request.get('attachment_inputs'),request.get('goal','placement_def'))
        state=load(folder/'task.json')
        backend=task_backend(state)
        if mode in ('context','observe'): return view(state,folder)
        if mode=='resume': return resume_task(state,folder,request)
        if mode in ('query','discover'):
            from .task_queries import query,features
            verify_refs(state['input_refs'])
            if state['completed']:verify_refs(state['results'][state['completed'][-1]]['artifact_refs'])
            if mode=='query':
                return {**query(state,backend,request['kind'],request.get('cursor',0),request.get('limit',20),request.get('stage')),'state_id':state_id(state)}
            from .placement_registry import select_tool
            facts=features(state,backend)
            result=select_tool(stage=request['stage'],format_id=state['contract']['case_manifest']['format_id'],
                required_constraints=['fixed_instances','die_bounds','nonoverlap'],movable_hard_macros=facts['movable_hard_macros'],
                state_id=state_id(state),budget={'cpu_threads':state['contract']['budget']['cpu_threads'],'memory_gb':state['contract']['budget']['memory_gb'],'timeout_seconds':max(180,state['contract']['budget'].get('container_seconds',180))})
            directory=folder/'decisions';directory.mkdir(exist_ok=True)
            target=directory/(result['decision_id']+'.json');save(target,{**result,'facts':facts})
            return {**result,'facts':facts,'evidence_ref':str(target)}
        if mode=='retrieve': return retrieve(folder,state,request['query'],request.get('backend_version',''))
        if mode=='reserve_model':
            if state['status']=='running':
                if state['counts']['model_calls']>=state['contract']['budget']['model_calls']:
                    raise ValueError('TASK_MODEL_BUDGET: stop and preserve accepted results')
                if time.time()-state['created_at']>state['contract']['budget']['wall_seconds']:
                    raise ValueError('TASK_WALL_BUDGET: stop and preserve accepted results')
                state['counts']['model_calls']+=1;save(folder/'task.json',state)
            return {'reserved':state['status']=='running','counts':state['counts']}
        if mode!='act': raise ValueError('Unknown task operation')
        action=request['action'];action_id=request['action_id'];fingerprint=digest({k:request.get(k) for k in ('action','state_id','reason')})
        if action_id in state['receipts']:
            if state['receipts'][action_id]['fingerprint']!=fingerprint: raise ValueError('Action identity collision')
            return {**view(state,folder),'replayed_receipt':True}
        if request['state_id']!=state_id(state): raise ValueError('STALE_STATE: observe before another action')
        if action not in view(state,folder)['allowed_actions']: raise ValueError('Action not allowed in current phase')
        if action=='stop':
            state['status']='stopped_with_best';state['stop_reason']=request.get('reason','user stop')
        elif action=='finish':
            verify_refs(state['input_refs'])
            final_stage=backend.STAGES[-1]
            verify_refs(state['results'][final_stage]['artifact_refs'])
            if not state['results'][final_stage].get('readback_equal'): raise ValueError('Readback not verified')
            from .task_artifacts import package
            state['deliverables']=getattr(backend,'package',package)(state,folder,backend)
            state['status']='target_met';state['final_def']=state['deliverables']['final_def']
        elif action=='recover':
            pending=state['pending'];receipt=Path(pending['work'])/'stage-receipt.json'
            if receipt.exists():
                result=load(receipt)
                if result.get('action_id')!=pending['action_id'] or result.get('base_state_id')!=pending['base_state_id']:
                    raise ValueError('Recovery receipt mismatch')
                verify_refs(state['input_refs']);verify_refs(result['artifact_refs'])
                return commit(state,folder,result,pending['action_id'],pending['fingerprint'])
            if time.time()<pending.get('safe_retry_after',0):
                return {**view(state,folder),'action_error':'EXECUTION_UNCERTAIN: wait for the bounded backend deadline before retrying',
                        'safe_retry_after':pending['safe_retry_after'],'accepted_state_preserved':True}
            state['events'].append({'action':pending['action'],'status':'uncertain_discarded','work':pending['work']})
            state['pending']=None  # Never reuse uncertain output; next attempt uses a new workspace.
        else:
            if state['contract']['backend_version'] != backend.BACKEND_VERSION or state['contract']['image'] != backend.rt.IMAGE:
                raise ValueError('BACKEND_VERSION_CHANGED: preserve this task; start a new session for the server-equivalent runtime')
            verify_refs(state['input_refs'])
            if state['counts']['executions']>=state['contract']['budget']['executions']: raise ValueError('Execution budget exhausted')
            failure_limit=stage_failure_limit(state,action)
            if state['failure_counts'].get(action,0)>=failure_limit: raise ValueError('Repeated failure: stop task')
            work=folder/'attempts'/uuid.uuid4().hex[:12]
            work.parent.mkdir(exist_ok=True)
            try:
                if state['accepted_work']:
                    previous=state['results'][state['completed'][-1]]
                    verify_refs(previous['artifact_refs'])
                    clone_workspace(state['accepted_work'],work)
                else:
                    work.mkdir();backend.setup(work)
            except Exception as exc:
                # No native process or pending execution exists at this point.
                # Record preparation failure before returning it to the model.
                state['revision']+=1
                state['events'].append({'action':action,'status':'preparation_failed','error':str(exc),'work':str(work),'native_execution_started':False})
                save(folder/'task.json',state)
                return {**view(state,folder),'action_error':'WORKSPACE_PREPARATION_FAILED: '+str(exc),
                        'native_execution_started':False,'accepted_state_preserved':True}
            state['counts']['executions']+=1
            # Docker's own timeout survives host/UI cancellation. Until it expires,
            # absence of a receipt does not prove that the old container stopped.
            deadline=max(150,state['contract']['budget'].get('host_seconds',140)+10) if execute is None and action!='validate' else 0
            state['pending']={'action':action,'action_id':action_id,'fingerprint':fingerprint,'base_state_id':state_id(state),'work':str(work),
                              'safe_retry_after':time.time()+deadline}
            save(folder/'task.json',state)
            try:
                decision=None
                if action in ('macro_placement','placement') and execute is None:
                    from .task_queries import features
                    from .placement_registry import select_tool
                    facts=features(state,backend)
                    decision=select_tool(stage='macro_placement' if action=='macro_placement' else 'standard_cell_placement',
                        format_id=state['contract']['case_manifest']['format_id'],
                        required_constraints=['fixed_instances','die_bounds','nonoverlap'],movable_hard_macros=facts['movable_hard_macros'],
                        state_id=state['pending']['base_state_id'],budget={'cpu_threads':state['contract']['budget']['cpu_threads'],'memory_gb':state['contract']['budget']['memory_gb'],'timeout_seconds':max(180,state['contract']['budget'].get('container_seconds',180))})
                    if decision['status']!='selected':raise ValueError('CAPABILITY_GAP: '+json.dumps(decision))
                result=(execute or backend.execute)(action,work)
                if decision:result['dispatcher']=decision
                verify_refs(state['input_refs'])
                result['workspace_storage']=seal_workspace(work)
                refs=[file_ref(p) for p in sorted((work/'result').rglob('*')) if p.suffix in ('.def','.txt','.rpt','.v','.json','.gds','.spef') and p.is_file()]
                refs += [file_ref(p) for p in [work/'backend-checks.json',work/'logs'/f'{action}.log'] if p.is_file()]
                result.update(artifact_refs=refs,action_id=action_id,base_state_id=state['pending']['base_state_id'],
                              receipt_ref=str(work/'stage-receipt.json'))
                save(work/'stage-receipt.json',result)
                return commit(state,folder,result,action_id,fingerprint)
            except Exception as exc:
                state['failure_counts'][action]=state['failure_counts'].get(action,0)+1
                state['events'].append({'action':action,'status':'failed','error':str(exc),'work':str(work)})
                state['pending']=None
                # Determine the limit before execution: an expiring approval must
                # never prevent recording a real native failure and clearing pending.
                if state['failure_counts'][action]>=failure_limit: state['status']='failed'
                state['revision']+=1
                save(folder/'task.json',state)
                return {**view(state,folder),'action_error':str(exc),'accepted_state_preserved':True}
        state['revision']+=1
        state['events'].append({'action':action,'reason':request.get('reason',''),'status':state['status']})
        state['receipts'][action_id]={'fingerprint':fingerprint,'committed':True}
        save(folder/'task.json',state)
        return view(state,folder)


if __name__=='__main__':
    import sys
    print(json.dumps(dispatch(json.load(sys.stdin)),ensure_ascii=False))
