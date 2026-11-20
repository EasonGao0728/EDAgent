"""Short, separate compatibility probe; never starts routing or touches prior tasks."""
from pathlib import Path
import subprocess,shlex
ROOT=Path(__file__).resolve().parents[1]
CODE=r'''
import os,pathlib,json,time,fcntl,shutil
root=pathlib.Path('/srv/edagent/main-agent-remote-v1');os.chdir(root)
from macro_agent.remote_service import init,gate
init()
from macro_agent import swerv_backend as s
with gate():
 assert not [p for p in root.glob('runs/*/jobs/*.json') if json.loads(p.read_text())['status'] not in ('completed','failed','cancelled','lost')]
 work=root/'runs/swerv-interface-probe-20261114';work.mkdir(exist_ok=True)
 handles=work/'handles';handles.mkdir(exist_ok=True);os.environ['AIEDA_NATIVE_HANDLES']=str(handles)
 if not (work/'config').exists():s.setup(work,root/'cases/ibench'/s.CASE)
 for source in (root/'cases/ibench'/s.CASE/'config').glob('*.json'):
  target=work/'config'/source.name
  if target.read_bytes()!=source.read_bytes():
   backup=target.with_name(target.name+'.before-'+str(time.time_ns()));shutil.copyfile(target,backup);shutil.copyfile(source,target)
 if (work/'pl/report/summary_report.txt').exists() and not (work/'result/pl/report/summary_report.txt').exists():
  shutil.copytree(work/'pl/report',work/'result/pl/report',dirs_exist_ok=True)
  (work/'report-path-correction.json').write_text(json.dumps({'source':'pl/report','canonical':'result/pl/report','native_stages_rerun':False}))
 for stage in ['import_netlist','floorplan','macro_placement','fanout','placement','validate','export_def','cts','to_drv','to_hold','legalization']:
  receipt=work/(stage+'-probe.json')
  if receipt.exists():
   artifact=work/'result'/(stage+'.def')
   if artifact.exists():
    fix=s.normalize_unplaced(artifact)
    if fix.get('changed_records'): (work/(stage+'-syntax-repair.json')).write_text(json.dumps(fix))
   continue
  for previous in [work/'logs'/(stage+'.log'),work/(stage+'-evidence.json')]:
   if previous.exists():shutil.copyfile(previous,previous.with_name(previous.name+'.before-'+str(time.time_ns())))
  result=s.execute(stage,work,root/'cases/ibench'/s.CASE);receipt.write_text(json.dumps(result,indent=2));print(stage,result.get('seconds'),flush=True)
 print('PROBE_COMPLETE',flush=True)
'''
if __name__=='__main__':
 p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','eda-worker','cd /srv/edagent/main-agent-remote-v1 && python3 -B -c '+shlex.quote(CODE)],text=True,encoding='utf-8')
 raise SystemExit(p.returncode)
