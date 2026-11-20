"""Deploy explicit repair adapters while the owned server scheduler is idle."""
from pathlib import Path
import base64,json,subprocess,shlex
ROOT=Path(__file__).resolve().parents[1]
NAMES=['macro_agent/'+n+'.py' for n in ('hold_repair','hold_calibration','remote_native')]
CODE=r'''
import sys,json,base64,pathlib,hashlib,ast,time,fcntl
root=pathlib.Path('/srv/edagent/main-agent-remote-v1');sys.path.insert(0,str(root))
from macro_agent.swerv_screening import active_jobs
out=root/'runs/hold-repair-20261116-v1';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
items=json.load(sys.stdin)
with (root/'scheduler/controller.lock').open('a+b') as f:
 fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
 assert not active_jobs(),'SERVER_BUSY'
 manifest=root/'deployment-manifest.json';m=json.loads(manifest.read_text());before={}
 for name,encoded in items.items():
  p=root/name;data=base64.b64decode(encoded);ast.parse(data);before[name]=sha(p) if p.exists() else None
  if name in m:assert m[name]['sha256']==before[name],('untracked change',name)
  backup=out/'before'/name
  if p.exists() and not backup.exists():backup.parent.mkdir(parents=True,exist_ok=True);backup.write_bytes(p.read_bytes())
 for name,encoded in items.items():
  p=root/name;p.write_bytes(base64.b64decode(encoded));m[name]={'sha256':sha(p),'bytes':p.stat().st_size}
 manifest.write_text(json.dumps(m,indent=2))
 r={'before':before,'after':{name:m[name]['sha256'] for name in items},'time':time.time(),'default_runtime_replaced':False}
 (out/('deploy-'+str(time.time_ns())+'.json')).write_text(json.dumps(r,indent=2));print(json.dumps(r))
'''
if __name__=='__main__':
 p=subprocess.run(['ssh','-o','BatchMode=yes','eda-worker','python3 -B -c '+shlex.quote(CODE)],input=json.dumps({n:base64.b64encode((ROOT/n).read_bytes()).decode() for n in NAMES}),text=True,capture_output=True,encoding='utf-8',timeout=45)
 if p.returncode:raise RuntimeError(p.stderr or p.stdout)
 out=ROOT/'runs/hold-repair-20261116';out.mkdir(exist_ok=True);(out/'deployment.json').write_text(p.stdout,encoding='utf-8');print(p.stdout)
