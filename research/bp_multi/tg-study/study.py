"""Server-only paired TG experiments on the frozen bp_multi legalization checkpoint."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path('/srv/edagent/main-agent-remote-v1')
BENCH = Path('/srv/benchmarks/iBench/benchmarks')
BASE = ROOT/'runs/bringup-bp_multi-area130-cts100-drv2/attempt-inherited-drv2'
STUDY = ROOT/'runs/bp-multi-tg-study-20261121'
CAT = ROOT/'qualification-evidence/catalog-v1'
SNAPS = BENCH/'tools/runtime_snapshots_v2'
RT = ROOT.parent/'portable-runtime-v1'
SOURCE = BASE/'result/legalization.def'
DEF_HASH = 'f0485dca1a091200b6004dd8a75692422f5877ae405deca267733e99f2784728'
SNAP = {'original':('iEDA-a4f0682fd0fd7c19','9f6c91ac6a58a00feaa63ba5eef37cfd240a4b60dd1fedba0654439763a3a6f8'),
        'subdivision':('iEDA-tg-subdivision-d85ab79124824b9d-d85ab79124824b9d','c9676349b18f010474cef73fc60c2fe437612dc9439ee5ae4b4b32f3c73eb7a8')}
sys.path[:0] = [str(CAT/'bp_multi_drv'),str(CAT),str(ROOT)]
from macro_agent import remote_service,swerv_backend
from macro_agent.def_validation import read_def,section
from macro_agent.swerv_screening import active_jobs
from qualify_catalog_nangate import prepare

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def save(p,value):
    tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,indent=2))
    tmp.replace(p)

def setup():
    ref=STUDY/'reference'
    receipt=json.loads((BASE/'progress.json').read_bytes())
    assert sha(SOURCE)==DEF_HASH and receipt['completed'][-1]=='legalization'
    e=json.loads((BASE/'legalization-evidence.json').read_bytes())
    assert e['passed'] and e['artifact_sha256']==DEF_HASH
    if not ref.exists():
        ref.mkdir()
        c=next(x for x in json.loads((CAT/'case-packages.json').read_bytes()) if x['id']=='bp_multi')
        prepare(ROOT,BENCH,CAT/'pdks',c,ROOT/'runs/structural-bp_multi',ref,swerv_backend,1.3,True,100,2)
    for p in ref.rglob('*'):
        if p.is_file():assert sha(p)==receipt['binding'][str(p.relative_to(ref))]
    return ref

def sample(ref):
    db=read_def(SOURCE);text=SOURCE.read_text()
    macros=json.loads((BASE/'manifest.json').read_bytes())['expected_macro_masters']
    # Select by two-pin stdcell origin bbox. No assumption about iRT's access-point rank.
    eligible=[]
    for name,pins in db['nets'].items():
        if len(pins)!=2 or any(n=='PIN' or n in macros for n,_ in pins):continue
        a,b=[db['components'][n]['placement'][1:3] for n,_ in pins]
        dx,dy=abs(a[0]-b[0]),abs(a[1]-b[1])
        if dx and dy:eligible.append((dx*dy,name,dx,dy,pins))
    eligible.sort()
    records={r.split()[0]:r for r in section(text,'NETS')}
    chosen={}
    for label,quantile in [('short',.25),('tail',.995),('extreme',1.)]:
        area,name,dx,dy,pins=eligible[int((len(eligible)-1)*quantile)]
        chunk=re.sub(r'^NETS\s+\d+\s*;.*?^END NETS\s*$',lambda _: 'NETS 1 ;\n- '+records[name]+' ;\nEND NETS',text,flags=re.M|re.S)
        chunk=re.sub(r'^PINS\s+\d+\s*;.*?^END PINS\s*$', 'PINS 0 ;\nEND PINS',chunk,flags=re.M|re.S)
        path=STUDY/(label+'.def')
        if not path.exists():path.write_text(chunk)
        assert path.read_text()==chunk
        d=read_def(path)
        assert d['nets']=={name:pins} and d['components']==db['components'] and d['physical']==db['physical']
        chosen[label]={'net':name,'pins':pins,'bbox_dx_um':dx/db['units'],'bbox_dy_um':dy/db['units'],'def_sha256':sha(path),'quantile':quantile}
    save(STUDY/'sample.json',{'source_sha256':DEF_HASH,'eligible_two_pin_nets':len(eligible),'selected':chosen})
    return chosen

def limits():
    os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:4])
    resource.setrlimit(resource.RLIMIT_AS,(8*2**30,8*2**30))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_FSIZE,(2**30,2**30))

def run(ref,label,variant,span,repeat=1):
    full=label=='full'
    src=SOURCE if full else STUDY/(label+'.def')
    w=STUDY/f'{label}-{variant}-{span}-r{repeat}'
    if (w/'receipt.json').exists():return json.loads((w/'receipt.json').read_bytes())
    w.mkdir()
    for sub in ('result/rt','result/report','logs'):(w/sub).mkdir(parents=True,exist_ok=True)
    shutil.copytree(BASE/'config',w/'config')
    tcl=(BASE/'routing.tcl').read_text().replace('/work/result/legalization.def','/frozen.def')
    (w/'stage.tcl').write_text(tcl)
    snap=SNAPS/SNAP[variant][0];binary=snap/'iEDA'
    assert sha(binary)==SNAP[variant][1]
    meta=json.loads((snap/'snapshot.json').read_bytes())
    refs={}
    for lib in meta['shared_libraries']:
        p=snap/'lib'/Path(lib['snapshot']).name
        assert p.resolve().is_relative_to(snap.resolve()) and sha(p)==lib['sha256']
        refs[p.name]=lib['sha256']
    args=['bwrap','--die-with-parent','--unshare-user','--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts']
    for d in ['/usr','/bin','/lib','/lib64']:args+=['--ro-bind',d,d]
    args+=['--proc','/proc','--dev','/dev','--tmpfs','/tmp','--ro-bind',str(RT),'/opt/runtime','--ro-bind',str(snap),'/router','--ro-bind',str(src),'/frozen.def','--ro-bind',str(ref),'/reference','--bind',str(w),'/work','--chdir','/work','--clearenv']
    env=dict(swerv_backend.ENV,PATH='/usr/bin:/bin',HOME='/tmp',TCL_LIBRARY='/opt/runtime/tcl8.6',OMP_NUM_THREADS='4',OMP_THREAD_LIMIT='4',OPENBLAS_NUM_THREADS='1',RESULT_DIR='/work/result',CONFIG_DIR='/work/config',TCL_SCRIPT_DIR='/work/script',IEDA_RT_NATIVE_LAYER_TRACKS='1',IEDA_RT_MAX_MEMORY_MB='8192',IEDA_RT_MAX_ITERATIONS='1')
    if variant=='subdivision':env.update(IEDA_RT_TG_MAX_EDGE_SPAN=str(span),IEDA_RT_TG_STREAM_CANDIDATES='1')
    seconds=4989 if full else 360
    for k,v in env.items():args+=['--setenv',k,v]
    args+=['/usr/bin/timeout','--foreground','--kill-after=5',str(seconds),'/opt/runtime/ld-linux-x86-64.so.2','--library-path','/router/lib:/opt/runtime/lib','/router/iEDA','-script','/work/stage.tcl']
    identity={'variant':variant,'span':span,'full':full,'binary_sha256':sha(binary),'libraries':refs,'def_sha256':sha(src),'source_sha256':DEF_HASH,'cpu':4,'as_gib':8,'timeout':seconds,'env':env}
    save(w/'protocol.json',identity);start=time.monotonic()
    tg=None;end=None;log=w/'result/rt/rt.log';offset=0;pending='';events=[];last=''
    with (w/'logs/routing.log').open('wb') as out:
        proc=subprocess.Popen(args,stdout=out,stderr=subprocess.STDOUT,start_new_session=True,preexec_fn=limits)
        try:
            while True:
                if log.exists():
                    with log.open('rb') as f:
                        f.seek(offset);raw=f.read();offset=f.tell()
                    seq=(pending+raw.decode(errors='replace')).split('\n');pending=seq.pop()
                    for line in seq:
                        if not line:continue
                        last=line
                        if 'Info generateTGModel] Starting' in line:tg=time.monotonic()
                        if 'TG_SUBDIVISION net=' in line or ('Info generateTGModel]' in line and ('Routed ' in line or 'Completed' in line)):
                            if not full or len(events)<25:events.append(line)
                        if 'Info generateTGModel] Completed' in line:end=time.monotonic()
                if end is not None and not full and proc.poll() is None:
                    os.killpg(proc.pid,signal.SIGTERM)
                if proc.poll() is not None:break
                time.sleep(.025 if not full else 1)
        finally:
            if proc.poll() is None:os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGKILL);proc.wait()
    result=dict(identity,exit=proc.returncode,elapsed=round(time.monotonic()-start,3),tg_observed_wall=None if tg is None or end is None else round(end-tg,3),tg_complete=end is not None,events=events,last_log=last)
    save(w/'receipt.json',result)
    print(label,variant,span,result['exit'],result['elapsed'],result['tg_observed_wall'],last[:140],flush=True)
    return result

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('mode',choices=['sample','full']);a.add_argument('--span',type=int,default=12);args=a.parse_args()
    remote_service.init()
    with remote_service.gate():
        if active_jobs():raise RuntimeError('Another native job is active')
        STUDY.mkdir(exist_ok=True)
        ref=setup()
        if args.mode=='sample':
            print(sample(ref),flush=True)
            for label in ('extreme','tail','short'):
                for variant,span in [('original',0),('subdivision',0),('subdivision',args.span)]:
                    row=run(ref,label,variant,span)
                    if not row['tg_complete'] and row['exit']!=124:raise RuntimeError('See diagnostic receipt')
        else:
            evidence=[json.loads((STUDY/f'extreme-subdivision-{n}-r1/receipt.json').read_bytes()) for n in (0,args.span)]
            if not all(row['tg_complete'] for row in evidence) or not any('TG_SUBDIVISION' in l for l in evidence[1]['events']):raise RuntimeError('Missing paired native evidence')
            row=run(ref,'full','subdivision',args.span)
            sys.exit(0 if row['exit']==0 else 1)
