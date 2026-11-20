"""Read preserved results with the deployed gates; never runs a native stage."""
from pathlib import Path
import json
import subprocess
import shlex

OUT = Path('runs/drc-counter-audit-20261114')
CODE = r'''
import sys,json,pathlib,hashlib,os
assert os.getuid()==1015
root=pathlib.Path('/srv/edagent/main-agent-remote-v1')
sys.path.insert(0,str(root))
from macro_agent.remote_platform import install
install()
from macro_agent import main_task as task
from macro_agent import p1_perception
from macro_agent.backend_checks import drc_gate
from macro_agent.drc_counts import file_ref
from macro_agent.remote_native import runtime_status
original=json.loads(sys.stdin.read());runtime=runtime_status()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
before={str(p):sha(p) for p in root.glob('runs/*/task.json')}
work=pathlib.Path(original['work']);report=work/'result/report'
state=task.load(work.parent.parent/'task.json')
summary=task.load(report/'drc_summary.json')
result={'runtime':runtime,'native_stages_executed':0,
 'historical_gate':task.load(work/'backend-checks.json')['drc_gate'],
 'reanalysis':drc_gate(summary,report_dir=report,producer_sha256=runtime['binary_sha256']),
 'agent_failed_attempt_observation':p1_perception.failed_drc_observation(state),
 'accepted_result_replays':[]}
# Re-read one retained GCD and one AES result. No controller action is invoked.
for branch in root.glob('runs/*/task.json'):
 s=task.load(branch);r=s.get('results',{}).get('drc',{})
 if not r.get('receipt_ref'):continue
 case=s.get('contract',{}).get('case_id','')
 group='aes' if case.startswith('aes_') else 'gcd' if case=='ibench_gcd_legacy' else None
 if not group or any(x['group']==group for x in result['accepted_result_replays']):continue
 folder=pathlib.Path(r['receipt_ref']).parent/'result/report'
 if not (folder/'drc_summary.json').is_file():continue
 from macro_agent.aes_reproduction import drc_observation
 fun=drc_observation if group=='aes' else drc_gate
 value=fun(task.load(folder/'drc_summary.json'),report_dir=folder,producer_sha256=runtime['binary_sha256'])
 result['accepted_result_replays'].append({'group':group,'case':case,'task':s.get('task_id'),
   'passed':value['passed'],'quality_clean':value.get('quality_clean',value['passed']),
   'errors':value['errors'],'reconciliation':value.get('count_reconciliation')})
result['collected_evidence_unchanged']=all(sha(pathlib.Path(r['path']))==r['sha256'] for r in original['files'])
result['task_files_unchanged_during_replay']=before=={str(p):sha(p) for p in root.glob('runs/*/task.json')}
result['task_files_unchanged_since_collection']=all(sha(root/'runs'/name/'task.json')==h for name,h in original['task_hashes'].items())
result['active_jobs']=[str(p) for p in root.glob('runs/*/jobs/*.json') if task.load(p).get('status') not in ('completed','failed','cancelled','lost')]
print(json.dumps(result))
'''

if __name__ == '__main__':
    p = subprocess.run(['ssh', '-o', 'BatchMode=yes', 'eda-worker', 'python3 -B -c ' + shlex.quote(CODE)],
                       input=(OUT / 'collection.json').read_text(encoding='utf-8'),
                       capture_output=True, text=True, encoding='utf-8', timeout=180)
    if p.returncode:
        raise RuntimeError(p.stderr or p.stdout)
    data = json.loads(p.stdout)
    (OUT / 'server-reanalysis.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    print(json.dumps({k: data[k] for k in ('collected_evidence_unchanged', 'task_files_unchanged_during_replay',
                                         'task_files_unchanged_since_collection', 'active_jobs')}))
    print(json.dumps({'failed_attempt_new_gate': data['reanalysis']['passed'],
                      'old_results': [{k:v for k,v in x.items() if k!='reconciliation'} for x in data['accepted_result_replays']]}))
