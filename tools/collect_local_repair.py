"""Read this experiment's own server evidence without executing EDA."""
from pathlib import Path
import json, subprocess, shlex

OUT=Path(__file__).resolve().parents[1]/'runs/p1-local-repair-20261114'
CODE=r'''
from pathlib import Path
import json,hashlib,os
assert os.getuid()==1015
p=Path('/srv/edagent/main-agent-remote-v1/runs/remote-0416695c41fde120d84bfdcf')
out={}
for name in ['local-eco-plan.json','local-eco/receipt.json','local-eco-plan-v2.json','local-eco-v2/receipt.json','local-eco-plan-v3.json','local-eco-v3/receipt.json','local-repair-report.json']:
 f=p/name
 if f.is_file():out[name]=json.loads(f.read_text())
out['hashes']={n:hashlib.sha256((p/n).read_bytes()).hexdigest() for n in ['task.json','final.def']}
out['bytes']=sum(x.stat().st_size for w in p.glob('local-eco*') if w.is_dir() for x in w.rglob('*') if x.is_file())
out['logs']={str(f.relative_to(p)):f.read_text(errors='replace')[-5000:] for w in p.glob('local-eco*') if w.is_dir() for f in w.glob('*/native.log')}
print(json.dumps(out))
'''
if __name__=='__main__':
 p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','eda-worker','python3 -B -c '+shlex.quote(CODE)],capture_output=True,text=True,encoding='utf-8',timeout=60)
 if p.returncode:raise RuntimeError(p.stderr)
 data=json.loads(p.stdout)
 (OUT/'server-evidence.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'plan_status':data.get('local-eco-plan-v3.json',data.get('local-eco-plan-v2.json',{})).get('status'), 'result':{k:data.get('local-eco-v3/receipt.json',data.get('local-eco-v2/receipt.json',{})).get(k) for k in ['status','change_count','local_delta','global_delta','reasons','error']},'bytes':data['bytes'],'hashes':data['hashes']}))
