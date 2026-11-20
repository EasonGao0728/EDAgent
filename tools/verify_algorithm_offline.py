"""Persist a reproducible fixture-provider run with REAL OS sandbox execution.

This is not a live LLM run and not a desktop demonstration.
"""
import sys
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests.test_algorithm_agent import ProviderFixture
from macro_agent import algorithm_agent as aa
from macro_agent.dsh_host import initialize,act,ROOT,save
from macro_agent.common import digest,write_json
from macro_agent.windows_sandbox import WindowsSandbox

run=ROOT/'runs'/('algorithm-offline-'+uuid.uuid4().hex[:12])
state=initialize(run,ROOT/'cases/toy/connected_groups.json')
request=act(state,{'tool':'request_tool','state_id':digest(state['case']),
    'reason':'OFFLINE FIXTURE: ranked axial local search','target_ids':['a','b'],
    'metric':'weighted_macro_center_hpwl'},'request',run=run)
provider=ProviderFixture();sandbox=WindowsSandbox(ROOT,timeout=10)
for n in range(3):
    delivery=aa.advance(run,request['request_id'],f'fixture-step-{n}',provider=provider,sandbox=sandbox,guard=lambda:None)
    if delivery['status']=='failed':raise RuntimeError(delivery['feedback'])
assert delivery['status']=='delivered',delivery
result=act(state,{'tool':'run_generated_tool','state_id':digest(state['case']),
    'tool_id':delivery['delivery']['tool_id']},'execute',run=run)
save(run/'checkpoint.json',state)
report={'verification_kind':'offline_model_fixture_real_appcontainer','live_model':False,'desktop_demo':False,
    'run':str(run),'delivery':delivery,'application':result}
write_json(run/'verification.json',report)
print(str(run/'verification.json'))
print('HPWL:',result['before']['weighted_hpwl'],'->',result['after']['weighted_hpwl'])
