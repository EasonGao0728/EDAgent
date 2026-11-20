"""30-second, four-worker diagnostic; not an EDA workload or acceptance run."""
import concurrent.futures,hashlib,json,statistics,subprocess,time
from pathlib import Path
from macro_agent.portable_ieda import IMAGE
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/aes-p1-20261108/diagnostics-20261111'
expected=json.loads((OUT/'cpu-server.json').read_text())['sha256']
assert hashlib.sha256((OUT/'cpu-probe').read_bytes()).hexdigest()==expected
REMOTE=r'''
import os,subprocess,json,hashlib,pathlib
assert os.getuid()==1015
b='/srv/edagent/diagnostics-20261111/cpu-probe'
assert hashlib.sha256(pathlib.Path(b).read_bytes()).hexdigest()==EXPECTED
shell='for w in 1 2 3 4; do (while :; do '+b+'; done) & done; wait'
p=subprocess.run(['timeout','--kill-after=2','30','taskset','-c',','.join(map(str,sorted(os.sched_getaffinity(0))[:4])),'sh','-c',shell],capture_output=True,text=True,timeout=35)
print(json.dumps({'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr[-500:]}))
'''.replace('EXPECTED',repr(expected))
def run_server():
    p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','eda-backup','python3 -B -'],input=REMOTE,text=True,encoding='utf-8',capture_output=True,timeout=55,check=True)
    return json.loads(p.stdout)
def run_local():
    shell='for w in 1 2 3 4; do (while :; do /probe/cpu-probe; done) & done; wait'
    p=subprocess.run(['docker','run','--rm','--pull=never','--network','none','--cpus','4','--memory','128m','--pids-limit','24','--mount',f'type=bind,source={OUT},target=/probe,readonly',IMAGE,'timeout','--kill-after=2','30','sh','-c',shell],capture_output=True,text=True,timeout=40)
    return {'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr[-500:]}
def summarize(r):
    assert r['returncode']==124,r
    rows=[json.loads(line) for line in r['stdout'].splitlines() if line.startswith('{')]
    assert rows and len({x['checksum'] for x in rows})==1
    return {'expected_timeout_exit':124,'completed_kernels':len(rows),'median_kernel_wall_s':statistics.median(x['wall_s'] for x in rows),
        'first_four_wall_s':[x['wall_s'] for x in rows[:4]],'last_four_wall_s':[x['wall_s'] for x in rows[-4:]],'samples':rows}
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    fs=pool.submit(run_server);fl=pool.submit(run_local)
    r={'observed_at':time.time(),'server':summarize(fs.result()),'local':summarize(fl.result()),'binary_sha256':expected,
       'scope':'Both 30 seconds, four independent CPU workers, no iEDA; server CPU affinity four cores vs Docker 4-CPU quota. Native program unchanged. No power-plan change.'}
(OUT/'sustained-cpu-comparison.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
print(json.dumps({k:{q:v for q,v in d.items() if q!='samples'} if isinstance(d,dict) else d for k,d in r.items()}))
