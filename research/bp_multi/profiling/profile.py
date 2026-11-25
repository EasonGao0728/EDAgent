"""Take one CPU sample of our full-chip candidate at each expensive routing phase."""
from pathlib import Path
import json,os,resource,subprocess,time
root=Path('/srv/edagent/main-agent-remote-v1')
study=root/'runs/bp-multi-tg-study-20261121'
w=study/'full-subdivision-12-r1'
rt=w/'result/rt/rt.log'; monitor=w/'logs/routing-progress.jsonl'
d=study/'profile';d.mkdir(exist_ok=True)
sym=d/'symbols';sym.mkdir(exist_ok=True)
snap=Path('/srv/benchmarks/iBench/benchmarks/tools/runtime_snapshots_v2/iEDA-tg-subdivision-d85ab79124824b9d-d85ab79124824b9d')
if not (sym/'router').exists():(sym/'router').symlink_to(snap,target_is_directory=True)
resource.setrlimit(resource.RLIMIT_FSIZE,(40*2**20,40*2**20))
resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3))
seen=set()
end=time.monotonic()+5300
while time.monotonic()<end and not (w/'receipt.json').exists():
    time.sleep(8)
    if not rt.exists() or not monitor.exists():continue
    with rt.open('rb') as f:
        f.seek(max(0,rt.stat().st_size-6000));tail=f.read().decode(errors='replace')
    label=None
    for value,token in [('tg_tail','Routed 70000/78493'),('space','routeSRBoxMap] Starting'),('detailed','routeDRBoxMap] Starting')]:
        if value not in seen and token in tail:label=value;break
    if label is None:continue
    tick=json.loads(monitor.read_bytes().splitlines()[-1]);workers=[x for x in tick['processes'] if x['name']=='ld-linux-x86-64']
    if len(workers)!=1 or time.time()-tick['time']>65:continue
    proc=Path('/proc')/str(workers[0]['pid'])
    if not proc.is_dir() or proc.stat().st_uid!=os.getuid() or (proc/'stat').read_text().rsplit(')',1)[1].split()[19]!=workers[0]['start_ticks']:continue
    if b'/router/iEDA' not in (proc/'cmdline').read_bytes():continue
    seen.add(label)
    os.sched_setaffinity(0,os.sched_getaffinity(workers[0]['pid']))
    data=d/(label+'.perf');sample=subprocess.run(['perf','record','-e','cpu-clock:u','-F','49','--call-graph','dwarf,4096','-p',proc.name,'-o',str(data),'--','sleep','8'],capture_output=True,text=True,timeout=22)
    info={'phase':label,'start_ticks':workers[0]['start_ticks'],'record_exit':sample.returncode,'stderr':sample.stderr,'trigger':tail.splitlines()[-2:]}
    if sample.returncode==0:
        report=subprocess.run(['perf','report','--stdio','--sort','dso,symbol','--symfs',str(sym),'--no-children','--percent-limit','0.5','-i',str(data)],capture_output=True,text=True,timeout=25)
        (d/(label+'.txt')).write_text(report.stdout)
        info['report_exit']=report.returncode
    (d/(label+'.json')).write_text(json.dumps(info,indent=2))
