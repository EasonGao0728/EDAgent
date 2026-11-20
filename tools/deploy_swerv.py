from pathlib import Path
import base64,json,subprocess,shlex
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'runs/medium-macro-fullflow-20261114'
NAMES=['macro_agent/'+n+'.py' for n in ('swerv_backend','liberty_buses','aes_netlist','aes_transforms','full_backend','ieda_stages','main_task','placement_registry','main_decisions','p1_perception','attachment_inputs','remote_native')]
NAMES += [str(p.relative_to(ROOT)).replace('\\','/') for p in (ROOT/'cases/ibench/swerv_nangate45').rglob('*') if p.is_file()]
CODE=r'''
import pathlib,json,hashlib,base64,os,fcntl,ast,time,sys,shutil
assert os.getuid()==1015
root=pathlib.Path('/srv/edagent/main-agent-remote-v1');out=root.parent/'medium-macro-fullflow-20261114';out.mkdir(exist_ok=True)
items=json.loads(sys.stdin.read());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
with (root/'scheduler/controller.lock').open('a+b') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 assert not [str(p) for p in root.glob('runs/*/jobs/*.json') if json.loads(p.read_text())['status'] not in ('completed','failed','cancelled','lost')],'Active native job'
 manifest=root/'deployment-manifest.json';m=json.loads(manifest.read_text());before={}
 for n,b in items.items():
  p=root/n;assert p.resolve().is_relative_to(root);h=sha(p) if p.exists() else None;before[n]=h
  if h is not None:assert n in m and m[n]['sha256']==h,(n,'Untracked server change')
  data=base64.b64decode(b)
  if n.endswith('.py'):ast.parse(data)
  backup=out/'before'/n
  if p.exists() and not backup.exists():backup.parent.mkdir(parents=True,exist_ok=True);backup.write_bytes(p.read_bytes())
 parents={p.parent.name:sha(p) for p in root.glob('runs/*/task.json')}
 cts_source=pathlib.Path('/srv/benchmarks/iBench/benchmarks/tools/runtime_snapshots_v2/iEDA-cts-boundary-d06c3319f65a6e28/iEDA')
 assert sha(cts_source)=='e756b7a9a29238ff0b658acfb95728ab00681dbdd3110ec4eeb58359019cc5e8'
 cts=root/'environments/ieda-swerv-cts/iEDA';cts.parent.mkdir(exist_ok=True)
 if not cts.exists():shutil.copy2(cts_source,cts)
 assert sha(cts)==sha(cts_source)
 m['environments/ieda-swerv-cts/iEDA']={'sha256':sha(cts),'bytes':cts.stat().st_size,'source':str(cts_source)}
 for n,b in items.items():
  p=root/n;p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.deploy');tmp.write_bytes(base64.b64decode(b));tmp.replace(p)
  if p.name=='hmetis2.0pre1':p.chmod(0o755)
  m[n]={'sha256':sha(p),'bytes':p.stat().st_size}
 manifest.write_text(json.dumps(m,indent=2))
 receipt={'before':before,'after':{n:m[n]['sha256'] for n in items},'parent_task_hashes':parents,'time':time.time(),'native_producers_changed':False}
 (out/('deploy-'+str(time.time_ns())+'.json')).write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
'''
if __name__=='__main__':
 payload={n:base64.b64encode((ROOT/n).read_bytes()).decode() for n in NAMES}
 p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','eda-worker','python3 -B -c '+shlex.quote(CODE)],input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=180)
 if p.returncode:raise RuntimeError(p.stderr or p.stdout)
 result=json.loads(p.stdout);(OUT/'deployment.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print('Deployed',len(NAMES),'files; preserved',len(result['parent_task_hashes']),'task records')
