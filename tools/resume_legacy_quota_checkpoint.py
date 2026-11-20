"""Explicit user-authorized wall-time amendment; never executes native stages.

Preserves original task snapshot and all accepted results. This is an amended
run, NOT a claim that the original wall-clock deadline was met.
"""
import argparse, copy, json, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from macro_agent import main_task as t, ieda_runtime as rt

EXPECTED=['import_netlist','floorplan','fanout','placement','validate','export_def','cts','to_drv','to_hold','legalization','routing']
ERROR_ID='32410ad75196'

def amended(state, interrupted, now):
    if state['contract']['case_id']!='aes_legacy' or state['contract']['goal']!='full_backend':raise ValueError('Wrong case')
    if state['status']!='running' or state.get('pending') or state['completed']!=EXPECTED:raise ValueError('Wrong checkpoint')
    if state.get('quota_continuation'):raise ValueError('Already amended')
    budget=state['contract']['budget'];deadline=state['created_at']+budget['wall_seconds']
    if not state['created_at']<interrupted<deadline<now:raise ValueError('Invalid interruption timeline')
    if any(state['counts'][k]>=budget[k] for k in ('executions','model_calls')):raise ValueError('Count budget exhausted')
    remaining=deadline-interrupted
    result=copy.deepcopy(state)
    result['contract']['budget']=copy.deepcopy(budget)
    result['contract']['budget']['wall_seconds']=now+remaining-state['created_at']
    result['revision']+=1
    result['quota_continuation']={'authorization':'User explicitly requested Legacy checkpoint continuation on2026-11-10; do not rerun completed stages',
      'original_deadline':deadline,'interrupted_at':interrupted,'resumed_at':now,'remaining_seconds':remaining,
      'new_deadline':now+remaining,'original_deadline_met':False,'amended_wall_budget':True,
      'execution_and_model_counts_reset':False,'native_stages_reused':EXPECTED,'native_execution_started':False}
    result['events'].append({'action':'authorized_quota_continuation','status':'running',**result['quota_continuation']})
    return result

def run(folder,apply=False):
    folder=Path(folder).resolve()
    if folder!=ROOT/'runs/dsh-desktop-d60fc838a3964422/main-task':raise ValueError('Only exact interrupted Legacy run supported')
    with t.locked(folder):
        state=t.load(folder/'task.json')
        errors=[json.loads(x) for x in (ROOT/'runs/dsh-host-errors.jsonl').read_text().splitlines()]
        error=next(x for x in errors if x['id']==ERROR_ID)
        if error['mode']!='quota' or error['type']!='ValueError':raise ValueError('Wrong interruption evidence')
        t.verify_refs(state['input_refs'])
        for name in state['completed']:
            r=state['results'][name];t.verify_refs(r['artifact_refs'])
            if t.load(Path(r['receipt_ref']))!=r:raise ValueError('Receipt changed')
        if rt.invoke(['ps','--format','{{.Names}}']).strip():raise ValueError('Active containers; do not amend')
        new=amended(state,error['time'],time.time())
        if not apply:return new['quota_continuation']
        audit=folder/'checkpoints/quota-continuation-20261110';audit.mkdir(parents=True,exist_ok=False)
        (audit/'task-before.json').write_bytes((folder/'task.json').read_bytes())
        new['quota_continuation']['parent']=t.file_ref(audit/'task-before.json')
        new['quota_continuation']['program']=t.file_ref(Path(__file__))
        t.save(audit/'amendment.json',new['quota_continuation'])
        for k in ('created_at','counts','completed','results','receipts','input_refs','failure_counts','accepted_work'):
            if new[k]!=state[k]:raise ValueError('Protected state changed:'+k)
        t.save(folder/'task.json',new)
        return new['quota_continuation']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
    print(json.dumps(run(a.run,a.apply)))
