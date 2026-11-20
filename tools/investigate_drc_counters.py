"""Read-only collection of retained native DRC output. Never launches iEDA."""
from pathlib import Path
import json,subprocess,shlex,base64,hashlib
OUT=Path('runs/drc-counter-audit-20261114');OUT.mkdir(exist_ok=True)
CODE=r'''
import pathlib,json,hashlib,base64,os
assert os.getuid()==1015
base=pathlib.Path('/srv/edagent');root=base/'main-agent-remote-v1'
branch=root/'runs/remote-9e3f3d292052aa78e302cf96';state=json.loads((branch/'task.json').read_text())
event=next(e for e in reversed(state['events']) if e.get('action')=='drc' and e.get('status')=='failed')
work=pathlib.Path(event['work']);assert work.resolve().is_relative_to(branch.resolve())
files=[work/'backend-checks.json',work/'logs/drc.log',work/'stage.tcl',work/'config/drc_default_config.json',branch/'task.json']
files += [p for p in (work/'result/report').rglob('*') if p.is_file() and p.suffix in ('.json','.rpt','.txt')]
data={'work':str(work),'directories':[p.name for p in base.iterdir() if p.is_dir() and not p.is_symlink()],
 'active_jobs':[str(p) for p in root.glob('runs/*/jobs/*.json') if json.loads(p.read_text()).get('status') not in ['completed','failed','cancelled','lost']],
 'task_hashes':{p.parent.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('runs/*/task.json')},'files':[]}
for p in dict.fromkeys(files):
 if p.is_file():
  b=p.read_bytes();entry={'path':str(p),'relative':str(p.relative_to(branch)),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'mtime_ns':p.stat().st_mtime_ns}
  if len(b)<2_000_000:entry['data']=base64.b64encode(b).decode()
  data['files'].append(entry)
print(json.dumps(data))
'''
result=subprocess.run(['ssh','-o','BatchMode=yes','eda-worker','python3 -B -c '+shlex.quote(CODE)],capture_output=True,text=True,encoding='utf-8',timeout=90)
if result.returncode:raise RuntimeError(result.stderr)
data=json.loads(result.stdout)
for row in data['files']:
 if 'data' in row:
  content=base64.b64decode(row.pop('data'));assert hashlib.sha256(content).hexdigest()==row['sha256']
  p=OUT/'original'/row['relative'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
(OUT/'collection.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
print(json.dumps({'work':data['work'],'active':data['active_jobs'],'personal_directories':data['directories'],'files':[{'name':r['relative'],'bytes':r['bytes']} for r in data['files']]}))
