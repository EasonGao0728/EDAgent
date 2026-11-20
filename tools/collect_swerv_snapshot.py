"""Copy bounded audit evidence from this task; no EDA calls or server writes."""
from pathlib import Path
import json,subprocess,shlex,hashlib

root=Path(__file__).resolve().parents[1]
out=root/'runs/medium-macro-fullflow-20261114/server-evidence'
out.mkdir(exist_ok=True)
task='/srv/edagent/main-agent-remote-v1/runs/remote-ba81f7bdbfebcf944da30462'
code=r'''
import pathlib,json,hashlib
p=pathlib.Path(TASK);s=json.loads((p/'task.json').read_text())
w=p/'attempts/3a65aa9b4f44';a=pathlib.Path(s['accepted_work'])
files={n:p/n for n in ['task.json','main-decisions.json','decision-report.html']}
files.update({n:w/n for n in ['routing-evidence.json','routing.tcl']})
files.update({'routing.log':w/'logs/routing.log','rt.log':w/'result/rt/rt.log',
    'accepted-legalization.def':a/'result/legalization.def','legalization-evidence.json':a/'legalization-evidence.json'})
for f in (w/'logs').glob('native-*.json'):files[f.name]=f
for f in (p/'jobs').glob('job-14764ae8ff4b20f7d8b46f52*'):
 if f.is_file():files[f.name]=f
result=[]
for name,f in files.items():
 if f.is_file():
  assert f.resolve().is_relative_to(p.resolve()) and f.stat().st_size<100*1024**2
  result.append({'name':name,'path':str(f),'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
print(json.dumps({'status':s['status'],'completed':s['completed'],'files':result}))
'''.replace('TASK',repr(task))
p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','eda-worker','python3 -c '+shlex.quote(code)],capture_output=True,text=True,encoding='utf-8',timeout=30,check=True)
snapshot=json.loads(p.stdout)
for f in snapshot['files']:
    dest=out/f['name']
    if dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest()==f['sha256']:continue
    subprocess.run(['scp','-q','-C','-o','BatchMode=yes','-o','ConnectTimeout=10','eda-worker:'+f['path'],str(dest)],timeout=60,check=True)
    actual=hashlib.sha256(dest.read_bytes()).hexdigest()
    if actual!=f['sha256']:raise ValueError('Snapshot changed during transfer: '+f['name'])
(out/'manifest.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':snapshot['status'],'completed':len(snapshot['completed']),'files':len(snapshot['files']),'directory':str(out)},ensure_ascii=False))
