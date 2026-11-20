"""Identical post-placement flow on Windows Docker and Linux portable runtime.

Only writes a fresh output directory; input bundle and runtime are read-only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v): p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input',required=True,help='Frozen bundle containing placement.def, config/, pdk/, sdc/')
    ap.add_argument('--output',required=True)
    ap.add_argument('--runtime',help='Linux portable runtime directory; omit for local Docker')
    ap.add_argument('--image',help='Pinned local Docker image ID')
    ap.add_argument('--threads',type=int,choices=[1,4],default=4)
    a=ap.parse_args();source=Path(a.input).resolve();work=Path(a.output).resolve()
    manifest=json.loads((source/'bundle.json').read_text())
    for ref in manifest['files']:
        if sha(source/ref['path'])!=ref['sha256']:raise ValueError('Input hash mismatch: '+ref['path'])
    work.mkdir(parents=True,exist_ok=False)
    shutil.copytree(source,work/'input')
    shutil.copytree(source/'config',work/'config')
    for f in ['logs','result/report','result/pl','result/cts','result/rt','result/drc']:(work/f).mkdir(parents=True,exist_ok=True)
    if a.runtime:
        runtime=Path(a.runtime).resolve();r=json.loads((runtime/'manifest.json').read_text())
        for ref in r['files']:
            if sha(runtime/ref['path'])!=ref['sha256']:raise ValueError('Runtime hash mismatch')
        binary=[str(runtime/'ld-linux-x86-64.so.2'),'--library-path',str(runtime/'lib'),str(runtime/'iEDA')]
        env=dict(os.environ,TCL_LIBRARY=str(runtime/'tcl8.6'))
        mount=str(work)
    else:
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from macro_agent import ieda_runtime as rt
        if not a.image:raise ValueError('--image is required on Windows')
        mount='/work';env=dict(os.environ)
    # Use identical relative Tcl and config paths on both machines.
    settings={'OMP_NUM_THREADS':str(a.threads),'IEDA_RT_BEST_EFFORT':'0','IEDA_RT_NATIVE_LAYER_GRAPH':'0',
              'IEDA_RT_SR_LOCAL_PARALLEL':'0','RESULT_DIR':'result','CONFIG_DIR':'config','LC_ALL':'C'}
    env.update(settings)
    for f in (work/'config').glob('*.json'):
        s=f.read_text().replace('${RESULT_DIR}','result').replace('$CONFIG_DIR','config')
        f.write_text(s)
    pl=json.loads((work/'config/pl_default_config.json').read_text());pl['PL']['num_threads']=a.threads
    save(work/'config/pl_default_config.json',pl)
    pre='''flow_init -config config/flow_config.json
db_init -config config/db_default_config.json
tech_lef_init -path input/pdk/lef/sky130_fd_sc_hd.tlef
lef_init -path [list input/pdk/lef/sky130_fd_sc_hd_merged.lef]
db_init -lib_path [list input/pdk/lib/sky130_fd_sc_hd__tt_025C_1v80.lib]
db_init -sdc_path input/sdc/gcd.sdc
'''
    stages={
      'import_check':('input/placement.def',''),
      'cts':('result/import_check.def','run_cts -config config/cts_default_config.json -work_dir result/cts\ncts_report -path result/cts'),
      'legalization':('result/cts.def','run_incremental_flow -config config/pl_default_config.json'),
      'routing':('result/legalization.def',f'init_rt -temp_directory_path result/rt -bottom_routing_layer met1 -top_routing_layer met5 -thread_number {a.threads}\nrun_rt\ndestroy_rt\nfeature_summary -path result/report/routing_features.json -step routing'),
      'filler':('result/routing.def','run_filler -config config/pl_default_config.json'),
      'drc':('result/filler.def','run_drc -config config/drc_default_config.json -path result/report/drc.rpt\nsave_drc -path result/drc/detail.drc'),
      'gds_native':('result/filler.def','gds_save -path result/native.gds2')}
    records=[]
    run={'flow_version':'portable-dsh-v1','input_bundle_sha256':sha(source/'bundle.json'),'threads':a.threads,'environment':settings,'stages':records,'image':a.image,'runtime':a.runtime}
    for stage,(inp,cmd) in stages.items():
        body=pre+'def_init -path '+inp+'\n'+cmd+'\n'
        if stage not in ['drc','gds_native']:
            body+=f'def_save -path result/{stage}.def\nnetlist_save -path result/{stage}.v -exclude_cell_names {{}}\nreport_db -path result/report/{stage}.rpt\n'
        (work/f'{stage}.tcl').write_text('if {[catch {\n'+body+f'puts "PORTABLE_OK {stage}"\n'+'} message]} {puts stderr $message; exit 1}\nflow_exit\n')
        if a.runtime:
            command=['timeout','--kill-after=5','120','prlimit','--as=8589934592','--core=0','--']+binary+['-script',f'{stage}.tcl']
        else:
            name='ieda-portable-'+uuid.uuid4().hex[:12]
            command=rt.docker()+['run','--rm','--pull=never','--name',name,'--network','none','--cpus',str(a.threads),'--memory','8g','--pids-limit','256','--mount',f'type=bind,source={work},target=/work','--workdir','/work']
            for k,v in settings.items():command+=['--env',k+'='+v]
            command+=[a.image,'timeout','--kill-after=5','120','prlimit','--as=8589934592','--core=0','--','iEDA','-script',f'{stage}.tcl']
        print('RUN '+stage,flush=True);start=time.monotonic()
        with (work/'logs'/f'{stage}.log').open('w',encoding='utf-8') as log:
            try:
                proc=subprocess.run(command,cwd=work,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=140,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));code=proc.returncode
            except subprocess.TimeoutExpired:
                if not a.runtime:rt.invoke(['kill',name])
                code=124
        text=(work/'logs'/f'{stage}.log').read_text(errors='replace')
        good=code==0 and 'PORTABLE_OK '+stage in text
        if stage not in ['drc','gds_native']:
            f=work/'result'/f'{stage}.def';good=good and f.exists() and 'END DESIGN' in f.read_text()
        record={'stage':stage,'completed':good,'exit_code':code,'seconds':round(time.monotonic()-start,3)}
        records.append(record);save(work/'run.json',run);print(json.dumps(record),flush=True)
        if not good:raise RuntimeError('Stage failed: '+stage+'; see logs')
    f=work/'result/report/drc_summary.json';drc=json.loads(f.read_text())
    route=json.loads((work/'result/rt/violation_reporter/route_summary.json').read_text())
    run.update(status='physical_flow_completed',route_complete=route['route_complete'],drc_status=drc['status'],drc_count=drc['violation_count'],unsupported_rules=len(drc['unsupported']),signoff_clean=False)
    save(work/'run.json',run)
    print('OUTPUT='+str(work),flush=True)


if __name__=='__main__':main()
