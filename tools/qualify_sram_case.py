"""Qualify the registered native adapter before allowing Dispatcher selection."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from macro_agent.ieda_stages import for_case
from macro_agent.placement_registry import record_verification

ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);a=ap.parse_args()
work=Path(a.output).resolve()
if not work.is_relative_to(ROOT/'runs') or work.exists():raise ValueError('Fresh runs output required')
work.mkdir();b=for_case('sky130_sram_pair');b.setup(work)
record={'schema':'native_sram_adapter_qualification_v1','image':b.rt.IMAGE,'backend_version':b.BACKEND_VERSION,
        'inputs':[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in b.input_files()],
        'case_id':'sky130_sram_pair','agent_llm_calls':0,'stages':[],'passed':False}
evidence=work/'qualification.json'
def save():evidence.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
save()
try:
    for stage in b.STAGES:
        result=b.execute(stage,work);record['stages'].append({'stage':stage,'result':result});save()
        print('PASSED '+stage,flush=True)
    record['passed']=True;save()
except Exception as exc:
    record['error']=str(exc);save();raise
for tool in ('ieda_imp_sram_pair','ieda_ipl_sram_pair'):
    record_verification(tool,b.rt.IMAGE,b.rt.IMAGE,evidence)
print('QUALIFIED '+str(evidence))
