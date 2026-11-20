"""Download bounded evidence of the current SWERV task; never invokes EDA."""
from pathlib import Path
import base64, hashlib, json, subprocess

OUT=Path(__file__).resolve().parents[1]/'runs/medium-macro-fullflow-20261114/final-evidence'
CODE=r'''
from pathlib import Path
import json,base64,hashlib,os,time
assert os.getuid()==1015
p=Path('/srv/edagent/main-agent-remote-v1/runs/remote-ba81f7bdbfebcf944da30462')
s=json.loads((p/'task.json').read_text())
j=json.loads((p/'jobs/job-f863e2f008543b31ebcfd294.json').read_text())
assert j['status'] in ('completed','failed','cancelled','lost'),'Routing is still active; keep monitoring'
assert not s.get('pending'),'Follow-on stage active; collect after completion'
files={n:p/n for n in ('task.json','main-decisions.json','approved-budget-extension.json','approved-budget-extension-6h.json','single-terminal-gds-checker-correction.json','acceptance.json','metrics.json','decision-report.html')}
files['failed-gds-export-evidence.json']=p/'attempts/35edb3d986f6/gds_export-evidence.json'
for label,attempt in [('first','3a65aa9b4f44'),('second','98dfa3fc26bf'),('third','15f45a6cc990')]:
    w=p/'attempts'/attempt
    for name in ('routing-evidence.json','routing.tcl','logs/routing.log','logs/routing-progress.jsonl','result/rt/rt.log','result/rt/violation_reporter/route_summary.json'):
        files[label+'-'+name.replace('/','-')]=w/name
for job in p.glob('jobs/*.json'):files[job.name]=job
a=Path(s.get('accepted_work') or p)
assert a.resolve().is_relative_to(p.resolve())
for name in ('filler-evidence.json','drc-evidence.json','timing-evidence.json','gds_export-evidence.json','routed_readback-evidence.json','result/report/drc_summary.json','result/report/drc.rpt','result/report/drc_rules.json','result/timing/swerv_wrapper.rpt'):
    files['accepted-'+name.replace('/','-')]=a/name
items=[]
total=0
for name,f in files.items():
    if not f.is_file():continue
    assert f.resolve().is_relative_to(p.resolve())
    assert f.stat().st_size<12*1024**2
    data=f.read_bytes();total+=len(data);assert total<40*1024**2
    items.append({'name':name,'server_path':str(f),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'base64':base64.b64encode(data).decode()})
print(json.dumps({'observed_at':time.time(),'task_status':s['status'],'completed':s['completed'],'job_status':j['status'],'files':items}))
'''
errors=[]
for host in ('eda-worker','eda-backup'):
    try:
        r=subprocess.run(['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=10',host,'python3 -'],input=CODE,capture_output=True,text=True,encoding='utf-8',timeout=60)
        if r.returncode:raise RuntimeError(r.stderr[:500])
        v=json.loads(r.stdout);break
    except (subprocess.TimeoutExpired,RuntimeError,ValueError) as exc:errors.append(str(exc))
else:raise RuntimeError('Read-only evidence collection unavailable: '+str(errors))
OUT.mkdir(exist_ok=True)
for item in v['files']:
    data=base64.b64decode(item.pop('base64'))
    assert hashlib.sha256(data).hexdigest()==item['sha256'] and len(data)==item['bytes']
    dest=OUT/item['name']
    assert dest.parent.resolve()==OUT.resolve()
    # Only this dedicated final snapshot is refreshed; old attempt evidence is untouched.
    dest.write_bytes(data)
(OUT/'manifest.json').write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'task_status':v['task_status'],'completed':len(v['completed']),'files':len(v['files']),'directory':str(OUT)},ensure_ascii=False))
