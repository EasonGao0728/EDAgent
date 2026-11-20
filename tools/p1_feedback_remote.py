"""Read-only authorized server inspection helper; no native execution."""
import subprocess,json,shlex
code='''
import pathlib,json,os
root=pathlib.Path('/srv/edagent/main-agent-remote-v1')
assert os.getuid()==1015
print(json.dumps({'active':[(str(p),json.loads(p.read_text()).get('status')) for p in root.glob('runs/*/jobs/*.json') if json.loads(p.read_text()).get('status') not in ['completed','failed','cancelled','lost']], 'tasks':[(p.parent.name,json.loads(p.read_text())['contract']['case_id'],json.loads(p.read_text())['status'],len(json.loads(p.read_text())['completed'])) for p in root.glob('runs/*/task.json')]}))
'''
if __name__=='__main__':
 p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','eda-worker','python3 -B -c '+shlex.quote(code)],capture_output=True,text=True,encoding='utf-8',timeout=60)
 print(p.stdout or p.stderr)
