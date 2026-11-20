"""Read-only post-study preservation and process audit."""
from pathlib import Path
import json,subprocess
ROOT=Path(__file__).resolve().parents[1]
CODE=r'''
from pathlib import Path
import hashlib,json,os,sys
root=Path('/srv/edagent/main-agent-remote-v1');sys.path.insert(0,str(root))
from macro_agent.remote_native import identity
assert os.getuid()==1015
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
p=root/'runs/swerv-io-fixed-nohold-20261115-v3';r=json.loads((p/'receipt.json').read_text())
assert r['status']=='completed'
checks=[]
for f,h in r['frozen_inputs'].items():
    path=Path(f);assert path.resolve().is_relative_to(root)
    actual=sha(path);checks.append({'path':f,'expected_sha256':h,'actual_sha256':actual,'unchanged':h==actual})
active=[];failures=[]
studies=[root/'runs'/x for x in ('swerv-io-fixed-nohold-20261115-v1','swerv-io-fixed-nohold-20261115-v2','swerv-io-fixed-nohold-20261115-v3','swerv-no-hold-20261115-v1')]
for q in studies:
    for h in (q/'handles').glob('*.json'):
        v=json.loads(h.read_text())
        if identity(v['pid'])==v['start_ticks']:active.append(str(h))
    receipt=q/'receipt.json'
    if receipt.exists():
        v=json.loads(receipt.read_text())
        if v['status']=='failed':
            failures.append({'job_id':v['job_id'],'error':v.get('error'),'receipt_sha256':sha(receipt),
                'logs':[{'path':str(f),'sha256':sha(f),'tail':f.read_text(errors='replace')[-800:]} for f in q.glob('*/logs/probe.log')]})
print(json.dumps({'parent_unchanged':all(x['unchanged'] for x in checks),'checks':checks,'active_owned_handles':active,
    'preserved_failures':failures,'study_storage_bytes':sum(f.stat().st_size for q in studies for f in q.rglob('*') if f.is_file()),
    'routing_executed':r['routing_executed'],'production_modified':r['production_modified']}))
'''
p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','eda-worker','python3 -'],input=CODE,capture_output=True,text=True,encoding='utf-8',timeout=30)
if p.returncode:raise RuntimeError(p.stderr[-1000:])
v=json.loads(p.stdout)
(ROOT/'runs/swerv-no-hold-20261115/audit-and-preservation.json').write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v[k] for k in ('parent_unchanged','active_owned_handles','study_storage_bytes','routing_executed','production_modified')}))
