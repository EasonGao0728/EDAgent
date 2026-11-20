"""Run all full-flow native stages before exposing the goal to DSH."""
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from macro_agent.full_backend import for_case
from macro_agent.native_gds import ref
ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);a=ap.parse_args()
w=Path(a.output).resolve()
if not w.is_relative_to(ROOT/'runs') or w.exists():raise ValueError('Fresh runs path required')
w.mkdir();b=for_case('ibench_gcd_legacy');b.setup(w)
record={'schema':'full_backend_qualification_v1','agent_llm_calls':0,'backend_version':b.BACKEND_VERSION,
 'inputs':[ref(p) for p in b.input_files()],'stages':[],'passed':False}
evidence=w/'qualification.json'
def save():evidence.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
save()
try:
    for stage in b.STAGES:
        result=b.execute(stage,w);record['stages'].append({'stage':stage,'result':result});save();print('PASSED '+stage,flush=True)
    record['passed']=True;save()
except Exception as exc:record['error']=str(exc);save();raise
print('QUALIFIED '+str(evidence),flush=True)
