"""Read-only audit of this feedback acceptance campaign, not an executor."""
import json,subprocess,shlex
from pathlib import Path

code=r'''
import json,pathlib,hashlib
from macro_agent import main_task as task,p1_perception as perception
from macro_agent.remote_platform import install
install()
root=pathlib.Path('/srv/edagent/main-agent-remote-v1')
parent=root/'runs/remote-e5c7f543bbce738395e58a0a'
c=task.load(parent/'feedback-campaign.json');baseline=task.load(parent/'task.json')
task.verify_refs([c['baseline_task']])
out={'campaign_status':c['status'],'parent_task':task.file_ref(parent/'task.json'),'baseline_final_def':baseline['results']['routed_readback'].get('artifact_refs'),
     'budget':c['budget'],'counts':c['counts'],'events':c['events'],'branches':[],'jobs':[]}
for b in c['branches']:
 p=root/'runs'/b['branch_id'];s=task.load(p/'task.json')
 prefix={k:s['results'][k]==baseline['results'][k] for k in ['import_netlist','floorplan','fanout']}
 for k in s['completed']:
  if k not in s['results']:continue
  r=s['results'][k];task.verify_refs(r.get('artifact_refs',[]))
  if r.get('receipt_ref'):assert task.load(pathlib.Path(r['receipt_ref']))==r
 entry={'branch_id':p.name,'disposition':b.get('disposition'),'status':s['status'],'completed':s['completed'],
   'prefix_receipts_equal':prefix,'task_ref':task.file_ref(p/'task.json'),'pending':s.get('pending'),
   'density':perception.density_evidence(s),'stages':{k:{x:r.get(x) for x in ['artifact_refs','parameter_effect','log','receipt_ref']} for k,r in s['results'].items()}}
 entry['quality']=perception.hotspots(s)
 for name in ['stage-observation.json','feedback-comparison.json']:
  if (p/name).exists():entry[name]=task.load(p/name)
 out['branches'].append(entry)
for p in sorted((parent/'jobs').glob('*.json')):
 j=task.load(p)
 if j.get('request',{}).get('operation')=='feedback_continue':out['jobs'].append(j)
print(json.dumps(out))
'''
root='/srv/edagent/main-agent-remote-v1'
command='cd '+shlex.quote(root)+' && PYTHONPATH='+shlex.quote(root+':/srv/edagent/python')+' python3 -B -c '+shlex.quote(code)
result=subprocess.run(['ssh','-o','BatchMode=yes','eda-worker',command],capture_output=True,text=True,encoding='utf-8',timeout=90)
if result.returncode:raise RuntimeError(result.stderr)
data=json.loads(result.stdout)
Path('runs/p1-feedback-20261114/final-integrity-audit.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'parent_sha256':data['parent_task']['sha256'],'counts':data['counts'],'branches':[{k:b[k] for k in ['branch_id','disposition','status','completed','prefix_receipts_equal','density']} for b in data['branches']]},ensure_ascii=False))
