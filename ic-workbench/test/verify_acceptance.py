"""Read-only acceptance of the UI-submitted GCD; never executes EDA."""
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from macro_agent.def_validation import read_def

def read(path): return json.loads(path.read_text(encoding='utf-8'))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

session=read(Path(sys.argv[1]))
run=Path(session['task']['run'])
view=read(run/'remote-view.json')
acceptance=read(run/'acceptance.json')
metrics=read(run/'metrics.json')
delivery=read(run/'remote-delivery.json')
assert view['goal_certified'] and view['download_verified']
assert view['execution_location']=='server' and view['contract']['goal']=='full_backend'
assert len(view['plan'])==16 and all(p['status']=='validated' for p in view['plan'])
assert acceptance['case_run_passed'] and acceptance['full_backend_workflow_completed']
assert acceptance['drc']['violation_count']==0
assert view['contract']['input_source']=='conversation_attachments'
assert view['contract']['attachment_import']['reviewed_case_match']
inputs=session['messages'][0]['content'][1:]
assert len(inputs)==7
for b in inputs:
    f=b['attachment'];assert sha(Path(f['hostPath']))==f['attachmentId'].split(':')[1]
for file in delivery['files'].values():
    assert sha(Path(file['path']))==file['sha256']
    assert Path(file['path']).stat().st_size==file['bytes']
preview=read(run/'preview.json')
assert preview['source_def']['sha256']==sha(run/'final.def')
assert preview['preview']['sha256']==sha(run/'placement.svg')
assert session['job']['status']=='completed'
assert all(e['model']=='gpt-6-astra' and e['effort']=='high' for e in session['events'] if e['type']=='model_response')
calls=[e for e in session['events'] if e['type']=='tool_start']
runs=[e for e in calls if e['name']=='mp_task_run']
assert len(set(e.get('executionId',e['callId']) for e in runs))==1
assert len([e for e in calls if e['name']=='mp_task_start'])==1
assert len([e for e in calls if e['name']=='mp_task_download'])==1
core=ROOT/'runs/dsh-desktop-4247ed3bc3eefbe0/main-task/task.json'
assert sha(core)=='772a8718afc7fb103f749c6c3b6316c60b5d6cf0b5ab867927dbb7826e4263a8'
baseline=ROOT/'runs/dsh-desktop-6799d616b384b405/main-task'
spec=importlib.util.spec_from_file_location('geometry',ROOT/'runs/server-dsh-acceptance-20261111/compare_geometry.py')
geometry=importlib.util.module_from_spec(spec);spec.loader.exec_module(geometry)
out={'verified_at':datetime.datetime.now().astimezone().isoformat(),'session_id':session['id'],'run':str(run),
     'server_task_id':view['server_task_id'],'job_id':session['job']['job_id'],'model':'gpt-6-astra','reasoning_effort':'high',
     'goal_certified':True,'validated_stages':16,'drc_supported_violations':0,'input_source':'conversation_attachments',
     'uploaded_files':7,'attachment_transport':'durable_file_upload','remote_transfer':'ssh_verified_content_reuse',
     'server_job_seconds':round(session['job']['finished_at']-session['job']['started_at'],3),
     'metrics':metrics,'single_submission_identity':True,'run_tool_attempts':len(runs),
     'ssh_submission_failure_preserved':any(e['type']=='tool_error' and 'REMOTE_UNAVAILABLE' in e.get('error','') for e in session['events']),
     'files':{f['name']:{k:f[k] for k in ('path','sha256','bytes')} for f in delivery['files'].values()},
     'baseline_comparison':{'reference':str(baseline),'parsed_def_equal':read_def(run/'final.def')==read_def(baseline/'final.def'),
       'route_branches_equal_ignoring_order':geometry.branches(run/'final.def')==geometry.branches(baseline/'final.def'),
       'netlist_equal_excluding_generated_header':(run/'final.v').read_text().splitlines()[1:]==(baseline/'final.v').read_text().splitlines()[1:]},
     'old_core_unchanged':True,'signoff':False,'hard_macro_acceptance':False,
     'limitations':['zero hard macros','registered case only','LEF abstract GDS','no RCX/routed timing/power/IR/manufacturing signoff']}
target=ROOT/'ic-workbench/output/acceptance.json';target.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:out[k] for k in ['goal_certified','validated_stages','drc_supported_violations','server_job_seconds','single_submission_identity','baseline_comparison','old_core_unchanged']},ensure_ascii=False))
