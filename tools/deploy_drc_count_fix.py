"""Deploy only reviewed main-Agent code, with no active server job and backups."""
from pathlib import Path
import base64,json,subprocess,shlex
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'runs/drc-counter-audit-20261114'
NAMES=['macro_agent/'+n+'.py' for n in ['drc_counts','backend_checks','aes_reproduction','full_backend','routed_stages','aes_flow','p1_perception','remote_platform']]
CODE=r'''
import pathlib,json,hashlib,base64,os,fcntl,ast,time,sys
assert os.getuid()==1015
root=pathlib.Path('/srv/edagent/main-agent-remote-v1');out=root.parent/'drc-counter-audit-20261114';out.mkdir(exist_ok=True)
items=json.loads(sys.stdin.read());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
with (root/'scheduler/controller.lock').open('a+b') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 assert not [str(p) for p in root.glob('runs/*/jobs/*.json') if json.loads(p.read_text())['status'] not in ('completed','failed','cancelled','lost')],'Active native job'
 manifest=root/'deployment-manifest.json';m=json.loads(manifest.read_text());before={}
 for n,b in items.items():
  p=root/n;h=sha(p) if p.exists() else None;before[n]=h
  if h is not None:assert n in m and m[n]['sha256']==h,(n,'Untracked server change')
  data=base64.b64decode(b);ast.parse(data)
  backup=out/'before'/n
  if p.exists() and not backup.exists():backup.parent.mkdir(parents=True,exist_ok=True);backup.write_bytes(p.read_bytes())
 parents={p.parent.name:sha(p) for p in root.glob('runs/*/task.json')}
 for n,b in items.items():
  p=root/n;tmp=p.with_name(p.name+'.feedback-deploy');tmp.write_bytes(base64.b64decode(b));tmp.replace(p)
  m[n]={'sha256':sha(p),'bytes':p.stat().st_size}
 manifest.write_text(json.dumps(m,indent=2))
 receipt={'before':before,'after':{n:m[n]['sha256'] for n in items},'parent_task_hashes':parents,'time':time.time(),'native_binaries_changed':False,'gate_semantics_version':'drc-count-semantics-v2','historical_tasks_modified':False}
 target=out/('deploy-'+str(time.time_ns())+'.json');target.write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
'''
if __name__=='__main__':
 OUT.mkdir(exist_ok=True)
 payload={n:base64.b64encode((ROOT/n).read_bytes()).decode() for n in NAMES}
 p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','eda-worker','python3 -B -c '+shlex.quote(CODE)],input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=90)
 if p.returncode:raise RuntimeError(p.stderr or p.stdout)
 result=json.loads(p.stdout);(OUT/'deployment.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
