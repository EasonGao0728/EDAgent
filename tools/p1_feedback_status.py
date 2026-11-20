from pathlib import Path
import json
from macro_agent.remote_client import rpc
parent='remote-e5c7f543bbce738395e58a0a'
v=rpc({'operation':'observe','task_id':parent});c=v.get('feedback_campaign',{})
out=Path('runs/p1-feedback-20261114');out.mkdir(exist_ok=True)
(out/'live-status.json').write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
job=v.get('job')
print(json.dumps({'job':{k:job.get(k) for k in ('job_id','status','started_at','finished_at')} if job else None,'counts':c.get('counts'),'branches':[{k:b.get(k) for k in ('branch_id','status','completed','next_stage','state_id')} for b in c.get('branches',[])]},ensure_ascii=False))
