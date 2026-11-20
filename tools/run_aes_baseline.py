"""Fresh sequential baseline; never resumes or substitutes prior artifacts."""
import argparse,json,signal,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from macro_agent import aes_flow
ap=argparse.ArgumentParser();ap.add_argument('--case',required=True);ap.add_argument('--output',required=True);ap.add_argument('--runtime');a=ap.parse_args()
reference=ROOT/'cases/ibench'/a.case;work=Path(a.output).resolve()
if not work.is_relative_to(ROOT/'runs'):raise ValueError('Output must be in this personal project runs directory')
work.mkdir(parents=True,exist_ok=False);aes_flow.setup(work,reference)
record={'case':a.case,'version':aes_flow.VERSION,'created_at':time.time(),'status':'running','agent_calls':0,'stages':[],
    'input_sha256':{p.relative_to(reference).as_posix():aes_flow.sha(p) for p in reference.rglob('*') if p.is_file()}}
record['implementation_sha256']={str(p.relative_to(ROOT).as_posix()):aes_flow.sha(p) for p in (ROOT/'macro_agent').glob('*.py')}
record['baseline_runner_sha256']=aes_flow.sha(Path(__file__))
record['router_sha256']=aes_flow.sha(ROOT/'environments/ieda-aes-router/iEDA')
record['acceptance_mode']='flow_reproduction_separate_from_physical_quality'
aes_flow.write(work/'run.json',record)
def interrupted(signum,frame):
    raise RuntimeError('Baseline interrupted: signal '+str(signum))
if a.runtime:
    signal.signal(signal.SIGTERM,interrupted)
    signal.signal(signal.SIGALRM,interrupted)
    signal.alarm(json.loads((reference/'manifest.json').read_text())['budget']['wall_seconds'])
try:
    for stage in aes_flow.STAGES:
        print('RUN '+stage,flush=True)
        result=aes_flow.execute(stage,work,reference,a.runtime);result['stage']=stage;record['stages'].append(result)
        aes_flow.write(work/'run.json',record)
        print(stage+': '+str(result.get('passed')),flush=True)
        if not result.get('passed'):raise ValueError('Native execution or independent gate failed: '+stage)
    record['status']='passed'
    record['physical_quality_passed']=next(r['drc_gate']['quality_clean'] for r in record['stages'] if r['stage']=='drc')
except Exception as exc:
    record.update(status='failed',error=str(exc));raise
finally:
    record['finished_at']=time.time()
    if a.runtime:signal.alarm(0)
    aes_flow.write(work/'run.json',record)
