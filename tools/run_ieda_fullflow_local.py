"""Run a verified DSH HD GCD placement through the pinned local backend, without SSH."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from macro_agent.portable_ieda import IMAGE
from macro_agent.ieda_stages import REGISTERED_CASES
from ieda_gds_export import export


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--task',required=True);ap.add_argument('--output',required=True)
    a=ap.parse_args();task=Path(a.task).resolve();out=Path(a.output).resolve()
    if not out.is_relative_to(ROOT/'runs'):raise ValueError('Output must be under project runs')
    s=json.loads((task/'task.json').read_text(encoding='utf-8'))
    if s['status']!='target_met' or s['contract']['case_id']!='ibench_gcd_legacy':
        raise ValueError('Requires an accepted ibench_gcd_legacy DSH placement')
    refs=[*s['input_refs'],s['final_def']]
    for ref in refs:
        if hashlib.sha256(Path(ref['path']).read_bytes()).hexdigest()!=ref['sha256']:raise ValueError('Frozen input/artifact changed')
    source=Path(s['contract'].get('input_root') or REGISTERED_CASES['ibench_gcd_legacy'][0])
    m=s['contract']['case_manifest'];out.mkdir(parents=True,exist_ok=False);bundle=out/'bundle';bundle.mkdir()
    shutil.copy2(s['final_def']['path'],bundle/'placement.def')
    for rel in [m['tech_lef'],*m['cell_lefs'],*m['libs'],m['sdc']]:
        target=bundle/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/rel,target)
    shutil.copytree(source/m['config_dir'],bundle/'config')
    f=bundle/'config/pl_default_config.json';pl=json.loads(f.read_text());pl['PL'].pop('MP',None);pl['PL']['info_iter_num']=10;pl['PL']['GP']['Density']['is_adaptive_bin']=0
    f.write_text(json.dumps(pl,indent=2))
    f=bundle/'config/cts_default_config.json';cts=json.loads(f.read_text());cts={k:cts[k] for k in ['skew_bound','max_buf_tran','max_sink_tran','max_cap','max_fanout','max_length','routing_layer','buffer_type']};f.write_text(json.dumps(cts,indent=2))
    files=[{'path':f.relative_to(bundle).as_posix(),'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in sorted(bundle.rglob('*')) if f.is_file()]
    (bundle/'bundle.json').write_text(json.dumps({'source_dsh':str(task),'source_def':s['final_def'],'files':files},indent=2))
    work=out/'local'
    subprocess.run([sys.executable,'-B',str(ROOT/'tools/ieda_portable_flow.py'),'--input',str(bundle),'--output',str(work),'--image',IMAGE],check=True)
    gds=export(work)
    report=json.loads((work/'run.json').read_text());report.update(gds=gds,status='completed_with_limitations')
    (out/'run.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('RESULT='+str(out/'run.json'))


if __name__=='__main__':main()
