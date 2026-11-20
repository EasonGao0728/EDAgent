"""Read-only collection of the completed repair campaign and provenance."""
from pathlib import Path
import json,subprocess,shlex

ROOT=Path(__file__).resolve().parents[1]
CODE=r'''
import sys,json,pathlib,hashlib,subprocess,re
root=pathlib.Path('/srv/edagent/main-agent-remote-v1');sys.path.insert(0,str(root))
from macro_agent.remote_platform import python_compat
python_compat()
from macro_agent import hold_repair as r,hold_calibration as h
from macro_agent.swerv_screening import active_jobs
sha=lambda p:h.sha(p)
out=r.OUT;old=r.OLD
phases=['build','smoke','clock-api','rc-direct','rc-official','rc-qualification','resume-budgets']
d={'phases':{},'original_failures':[],'checkpoints':[],'internal_hold_reports':{},'stage_audit':[]}
for phase in phases:
 p=out/phase/'receipt.json';v=json.loads(p.read_text());assert v['status']=='completed',(phase,v['status'])
 d['phases'][phase]=v
for name in ('aes','tinyram','gcd','jpeg'):
 for label in ('cap01','cap025','cap05','cap10','cap20'):
  p=old/'sweep'/name/label/'hold/native-receipt.json'
  if name in ('aes','tinyram'):
   v=json.loads(p.read_text());assert v['returncode']==136
   d['original_failures'].append({'case':name,'label':label,'path':str(p),'sha256':sha(p),'returncode':v['returncode']})
 p=old/'sweep'/name/'cap01/hold/result/to/report.txt'
 if p.exists():d['internal_hold_reports'][name]=p.read_text(errors='replace')
q=json.loads((old/'checkpoints/qualification.json').read_text())
for c in q:
 if 'frozen_checkpoint' not in c:continue
 p=c['frozen_checkpoint'];v={**p,'case':c['case'],'unchanged':sha(p['path'])==p['sha256']};assert v['unchanged'];d['checkpoints'].append(v)
for p in out.rglob('native-receipt.json'):
 v=json.loads(p.read_text());script=p.parent/'stage.tcl';s=script.read_text()
 assert not re.search(r'(?m)^\s*(run_rt|run_placer|placer_run_mp)\b',s)
 d['stage_audit'].append({'path':str(p),'sha256':sha(p),'script_sha256':sha(script),'binary_sha256':v['binary_sha256'],'returncode':v['returncode'],'seconds':v['seconds']})
d['smoke']=json.loads((out/'smoke/results.json').read_text())
d['qualification']=json.loads((out/'rc-qualification/qualification.json').read_text())
d['resumed']=json.loads((out/'resume-budgets/results.json').read_text())
d['original_sweep']=json.loads((old/'sweep/results.json').read_text())
d['original_binary_unchanged']=sha(root.parent/'portable-runtime-v1/iEDA')==r.BASE_SHA
d['active_jobs']=active_jobs()
d['tool_manifest']=json.loads((r.TOOL/'manifest.json').read_text())
d['guard_disassembly']=(out/'build/disassembly.txt').read_text()
d['rc_loop_disassembly']=subprocess.run(['objdump','-d','-C','--start-address=0x130ffe0','--stop-address=0x1310210',str(root.parent/'portable-runtime-v1/iEDA')],capture_output=True,text=True,check=True).stdout
d['source_evidence']={}
src=root.parent/'ieda-rootcause-20261112/source/src'
for name in ['evaluation/src/util/init_sta.cc','operation/iTO/source/module/evaluator/EstimateParasitics.cpp','operation/iSTA/source/module/sta/StaClockPropagation.cc']:
 p=src/name;d['source_evidence'][name]={'sha256':sha(p),'text':p.read_text()}
print(json.dumps(d))
'''

if __name__=='__main__':
    p=subprocess.run(['ssh','-o','BatchMode=yes','eda-worker','python3 -B -c '+shlex.quote(CODE)],capture_output=True,text=True,encoding='utf-8',timeout=45)
    if p.returncode:raise RuntimeError(p.stderr or p.stdout)
    d=json.loads(p.stdout);out=ROOT/'runs/hold-repair-20261116';out.mkdir(exist_ok=True)
    (out/'evidence.json').write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'phases':{k:v['status'] for k,v in d['phases'].items()},'new_native_calls':len(d['stage_audit']),'original_failures_preserved':len(d['original_failures']),'active_jobs':d['active_jobs']}))
