"""Reviewed, idle-only deployment; completed task files and binaries unchanged."""
from pathlib import Path
import base64,json,subprocess,shlex,hashlib
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'runs/preroute-quality-integration-20261115'
NAMES=['macro_agent/'+n+'.py' for n in ('pin_metrics','hold_policy','quality_backend','quality_review','def_io_compat','remote_platform','remote_service','main_decisions')]+['environments/swerv-quality-review-source.json']
CODE=r'''
from pathlib import Path
import ast,base64,fcntl,hashlib,json,os,sys,time
assert os.getuid()==1015
root=Path('/srv/edagent/main-agent-remote-v1');payload=json.load(sys.stdin);items=payload['files'];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
out=root.parent/'preroute-quality-integration-20261115';out.mkdir(exist_ok=True)
with (root/'scheduler/controller.lock').open('a+b') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 assert not [str(p) for p in root.glob('runs/*/jobs/*.json') if json.loads(p.read_text())['status'] not in ('completed','failed','cancelled','lost')],'Active job'
 m=json.loads((root/'deployment-manifest.json').read_text());before={}
 for n,b in items.items():
  p=root/n;h=sha(p) if p.exists() else None;before[n]=h
  if h is not None:
   assert h in (m.get(n,{}).get('sha256'),payload['prior'].get(n)),(n,'Untracked server change')
  data=base64.b64decode(b)
  if n.endswith('.py'):ast.parse(data)
  else:json.loads(data)
  backup=out/'before'/n
  if p.exists() and not backup.exists():backup.parent.mkdir(parents=True,exist_ok=True);backup.write_bytes(p.read_bytes())
 protected={str(p):sha(p) for p in [*root.glob('runs/*/task.json'),*root.glob('runs/*/final.def'),*root.glob('runs/*/final.gds')]}
 for n,b in items.items():
  p=root/n;p.parent.mkdir(exist_ok=True);tmp=p.with_suffix(p.suffix+'.preroute-deploy');tmp.write_bytes(base64.b64decode(b));tmp.replace(p)
  m[n]={'sha256':sha(p),'bytes':p.stat().st_size}
 (root/'deployment-manifest.json').write_text(json.dumps(m,indent=2))
 assert all(sha(Path(p))==h for p,h in protected.items()),'Historical result changed'
 receipt={'before':before,'after':{n:m[n]['sha256'] for n in items},'preserved':protected,'historical_results_unchanged':True,'time':time.time(),'native_binaries_changed':False}
 (out/('deploy-'+str(time.time_ns())+'.json')).write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
'''
if __name__=='__main__':
 OUT.mkdir(exist_ok=True)
 prior={'macro_agent/def_io_compat.py':json.loads((ROOT/'runs/swerv-no-hold-20261115/evidence/io-receipt.json').read_text())['adapter_sha256']}
 payload={'files':{n:base64.b64encode((ROOT/n).read_bytes()).decode() for n in NAMES},'prior':prior}
 p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','eda-worker','python3 -B -c '+shlex.quote(CODE)],input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=90)
 if p.returncode:raise RuntimeError(p.stderr or p.stdout)
 v=json.loads(p.stdout);(OUT/'deployment.json').write_text(json.dumps(v,indent=2),encoding='utf-8')
 print(json.dumps({'deployed':len(v['after']),'preserved_files':len(v['preserved']),'historical_results_unchanged':v['historical_results_unchanged']}))
