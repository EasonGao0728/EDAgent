"""One audited budget amendment, without starting native work or resetting history."""
from pathlib import Path
import base64,json,subprocess,shlex
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/medium-macro-fullflow-20261114'
CODE=r'''
import pathlib,json,hashlib,base64,os,fcntl,ast,time,sys,copy
assert os.getuid()==1015
root=pathlib.Path('/srv/edagent/main-agent-remote-v1')
sys.path.insert(0,str(root));sys.path.insert(0,'/srv/edagent/python')
from macro_agent.remote_platform import install
t=install()
from macro_agent import main_decisions as decisions
from macro_agent import swerv_backend as old
payload=json.loads(sys.stdin.read());data=base64.b64decode(payload['code']);ast.parse(data)
tid='remote-ba81f7bdbfebcf944da30462';folder=root/'runs'/tid
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
with t.locked(root/'scheduler'),t.locked(folder):
 assert not [p for p in root.glob('runs/*/jobs/*.json') if json.loads(p.read_text())['status'] not in ('completed','failed','cancelled','lost')],'Active native job'
 assert not (folder/'approved-budget-extension.json').exists(),'Amendment already exists; do not reset its clock'
 s=t.load(folder/'task.json');d=decisions.store(folder)
 assert s['status']=='stopped_with_best' and s['pending'] is None
 assert s['contract']['case_id']==old.CASE
 assert s['completed']==old.STAGES[:11] and s['failure_counts']=={'routing':1}
 assert s['counts']=={'executions':12,'model_calls':42}
 t.verify_refs(s['input_refs'])
 for stage in s['completed']:
  result=s['results'][stage];t.verify_refs(result['artifact_refs'])
  assert t.load(pathlib.Path(result['receipt_ref']))==result,stage
 work=pathlib.Path(s['accepted_work']);checkpoint=work/'result/legalization.def'
 failure=folder/'attempts/3a65aa9b4f44/routing-evidence.json'
 assert t.load(failure)['returncode']==124
 module=root/'macro_agent/swerv_backend.py';manifest=root/'deployment-manifest.json';m=t.load(manifest)
 assert sha(module)==m['macro_agent/swerv_backend.py']['sha256']=='6704559170c0d64e056a91b46102c877ede3803c98511d3b95896a05a5ab76e8'
 # Verify the amendment does not change any generated native Tcl stage.
 namespace={'__name__':'macro_agent._swerv_retry_validation','__package__':'macro_agent','__file__':str(module)}
 exec(compile(data,str(module),'exec'),namespace)
 for stage in old.STAGES:
  if stage not in ('validate','gds_export'):
   assert old.script(stage,old.manifest())==namespace['script'](stage,old.manifest()),stage
 now=time.time();backup=folder/'checkpoints'/'before-budget-extension';backup.mkdir(parents=True,exist_ok=False)
 for name in ('task.json','main-decisions.json'):(backup/name).write_bytes((folder/name).read_bytes())
 (backup/'swerv_backend.py').write_bytes(module.read_bytes())
 (backup/'deployment-manifest.json').write_bytes(manifest.read_bytes())
 e={'schema_version':'swerv_budget_extension_v1','task_id':tid,'case_id':old.CASE,
    'issued_at':now,'expires_at':now+14400,'routing_seconds':10800,'other_stage_seconds':600,
    'cpu_threads':4,'memory_gb':8,'original_budget_failed':True,
    'authorization':'User requested continue attempting after timeout; announced bounded routing 3h / continuation 4h',
    'original_task':t.file_ref(backup/'task.json'),'original_decisions':t.file_ref(backup/'main-decisions.json'),
    'original_adapter':t.file_ref(backup/'swerv_backend.py'),'original_failure':t.file_ref(failure),
    'checkpoint_sha256':sha(checkpoint),'reused_stages':list(s['completed']),
    'algorithm_inputs_parameters_native_binaries_unchanged':True}
 amendment=folder/'approved-budget-extension.json';t.save(amendment,e)
 tmp=module.with_suffix('.retry.tmp');tmp.write_bytes(data);tmp.replace(module)
 m['macro_agent/swerv_backend.py']={'sha256':sha(module),'bytes':len(data)};t.save(manifest,m)
 old_budget=copy.deepcopy(s['contract']['budget'])
 s['contract']['budget'].update(wall_seconds=e['expires_at']-s['created_at'],routing_seconds=10800,
    container_seconds=10800,host_seconds=10820,model_calls=s['counts']['model_calls']+24)
 s['contract']['budget_amendment']={**t.file_ref(amendment),'original_budget_failed':True,
    'original_budget':old_budget,'reused_stages':list(s['completed']),'deadline_utc_epoch':e['expires_at']}
 s['input_refs']=[t.file_ref(module) if r['path']==str(module) else r for r in s['input_refs']]
 s['input_refs'].append(t.file_ref(amendment));s['contract']['all_inputs_hash']=t.digest(s['input_refs'])
 s['revision']+=1;s['events'].append({'action':'explicit_budget_amendment','time':now,
    'reason':e['authorization'],'amendment':t.file_ref(amendment),'original_failure_retained':True,
    'completed_stages_reused':s['completed'],'native_stages_started':0,'counts_reset':False})
 d['budget']['wall_seconds']=e['expires_at']-d['created_at'];d['model_call_limit']=d['model_calls']+24
 d['revision']+=1;d['events'].append({'action':'explicit_budget_amendment','amendment':t.file_ref(amendment),'counts_reset':False})
 t.verify_refs(s['input_refs'])
 decisions.write(folder,d);t.save(folder/'task.json',s)
 receipt={'amendment':e,'task_state_id':t.state_id(s),'task_status':s['status'],
    'counts':s['counts'],'original_task_snapshot_sha256':sha(backup/'task.json'),
    'new_adapter_sha256':sha(module),'native_stages_started':0,'native_tcl_unchanged':True}
 t.save(folder/'budget-extension-receipt.json',receipt);print(json.dumps(receipt))
'''

if __name__=='__main__':
    payload={'code':base64.b64encode((ROOT/'macro_agent/swerv_backend.py').read_bytes()).decode()}
    p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','eda-worker','python3 -B -c '+shlex.quote(CODE)],
        input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=120)
    if p.returncode:raise RuntimeError(p.stderr or p.stdout)
    result=json.loads(p.stdout)
    (OUT/'budget-extension-receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='amendment'},ensure_ascii=False))
