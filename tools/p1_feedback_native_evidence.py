import json,subprocess,shlex
from pathlib import Path
code=r'''
import json,pathlib,hashlib
r=pathlib.Path('/srv/edagent/main-agent-remote-v1/runs')
parent=r/'remote-e5c7f543bbce738395e58a0a';child=r/'remote-9ef68e900c65ccae62cf5ca6'
states=[json.loads((p/'task.json').read_text()) for p in [parent,child]]
results=[]
for state in states:
 p=state['results']['placement'];log=pathlib.Path(p['log']).read_text(errors='replace')
 results.append({'placement_sha256':hashlib.sha256(pathlib.Path(p['artifact']).read_bytes()).hexdigest(), 'density_log':[s for s in log.splitlines() if 'density' in s.lower()][:20],'parameter_effect':p.get('parameter_effect'),'completed':state['completed']})
print(json.dumps(results))
'''
p=subprocess.run(['ssh','-o','BatchMode=yes','eda-worker','python3 -B -c '+shlex.quote(code)],capture_output=True,text=True,encoding='utf-8',timeout=60)
if p.returncode:raise RuntimeError(p.stderr)
Path('runs/p1-feedback-20261114/native-density-evidence.json').write_text(p.stdout,encoding='utf-8');print(p.stdout)
