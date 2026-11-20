"""Linux continuation of the exact local DSH placement package; personal outputs only."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import time

base = Path.home()/'ibench-demo'
work = base/'dsh-continuation-20261105-01'
runtime = Path('/srv/benchmarks/iBench/benchmarks/tools/runtime_snapshots_v2/iEDA-d2f9fa939b296082')
work.mkdir(exist_ok=False)
with tarfile.open(base/'dsh-continuation-20261105-01.tar.gz') as archive:
    for member in archive.getmembers():
        target = (work/member.name).resolve()
        if not target.is_relative_to(work.resolve()) or not member.isfile():
            raise ValueError('Unexpected archive member')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.extractfile(member).read())
for folder in ['logs','result/report','result/rt','result/pl','result/drc','result/sta']:
    (work/folder).mkdir(parents=True, exist_ok=True)
for p in list(work.glob('*.tcl'))+list((work/'config').glob('*.json')):
    text=p.read_text().replace('/work/',str(work)+'/')
    text=text.replace('${RESULT_DIR}',str(work/'result')).replace('$CONFIG_DIR',str(work/'config'))
    p.write_text(text)
p=work/'routing.tcl'
p.write_text(p.read_text().replace('destroy_rt', 'destroy_rt\nfeature_summary -path {'+str(work/'result/report/routing_features.json')+'} -step routing'))
env=dict(os.environ, LD_LIBRARY_PATH=str(base.parent/'.local/opt/ieda-glog-0.7.1/lib')+':'+str(runtime/'lib'),
         OMP_NUM_THREADS='4', RESULT_DIR=str(work/'result'), CONFIG_DIR=str(work/'config'),
         IEDA_RT_BEST_EFFORT='0', IEDA_RT_NATIVE_LAYER_GRAPH='0', IEDA_RT_SR_LOCAL_PARALLEL='0')
records=[]
for stage in ['routing','filler','drc','gds']:
    print('RUN '+stage,flush=True); start=time.monotonic()
    with (work/'logs'/f'{stage}.log').open('w') as log:
        proc=subprocess.Popen(['prlimit','--as=8589934592','--core=0','--',str(runtime/'iEDA'),'-script',str(work/f'{stage}.tcl')],
                              cwd=work,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try: code=proc.wait(timeout=300)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL);proc.wait();code=124
    text=(work/'logs'/f'{stage}.log').read_text(errors='replace')
    record={'stage':stage,'exit_code':code,'seconds':round(time.monotonic()-start,2),'completed':code==0 and 'CONTINUATION_OK '+stage in text}
    records.append(record)
    (work/'remote-run.json').write_text(json.dumps({'runtime':str(runtime/'iEDA'),
        'runtime_sha256':hashlib.sha256((runtime/'iEDA').read_bytes()).hexdigest(),'stages':records},indent=2))
    print(json.dumps(record),flush=True)
    if not record['completed'] and stage in ['routing','filler']:sys.exit(1)
print('OUTPUT='+str(work),flush=True)
