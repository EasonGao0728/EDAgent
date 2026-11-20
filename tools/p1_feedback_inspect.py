import subprocess,shlex
code='''
import pathlib,json
r=pathlib.Path('/srv/edagent/main-agent-remote-v1')
for tid in ['remote-e5c7f543bbce738395e58a0a','remote-0416695c41fde120d84bfdcf']:
 s=json.loads((r/'runs'/tid/'task.json').read_text()); print(tid, 'density',json.loads((pathlib.Path(s['accepted_work'])/'config/pl_default_config.json').read_text())['PL']['GP']['Density'])
 print('resultkeys',[(k,list(v)) for k,v in s['results'].items() if k in ['fanout','placement','drc']]); print('drcgate',s['results']['drc']['drc_gate'])
 for n in ['violations.json','violation_map.json','drc_summary.json']:
  p=pathlib.Path(s['results']['drc']['receipt_ref']).parent/'result/report'/n
  if p.exists(): print(n,p.stat().st_size,p.read_text()[:1800])
 print('placement',str(s['results']['placement'])[:1200])
'''
p=subprocess.run(['ssh','-o','BatchMode=yes','eda-worker','python3 -B -c '+shlex.quote(code)],capture_output=True,text=True,encoding='utf-8',timeout=60)
print(p.stdout or p.stderr)
