"""Run one native sample and resume independently from each serialized boundary."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from verify_pa import BASE, DEF_HASH, RT, RUNS, active_jobs, limits, remote_service, save, setup, sha, usage

build=Path('/srv/edagent/bp-multi-official-build-v1')
study=RUNS.parent/'bp-multi-compact-layer-test'
source=RUNS/'abutment-126.def'
table=RUNS.parent/'bp-multi-sram-ce-escape-drc-v1/screened-escapes.tsv'

def trial(ref,binary,label,prior=None,finish=False,debug=False):
    w=study/label
    if (w/'receipt.json').exists():
        r=json.loads((w/'receipt.json').read_bytes())
        assert r['binary']==sha(binary) and r['input']==sha(source)
        return r
    w.mkdir()
    shutil.copytree(BASE/'config',w/'config')
    (w/'result/rt').mkdir(parents=True)
    (w/'result/report').mkdir()
    (w/'check.tcl').write_text((BASE/'routing.tcl').read_text().replace('/work/result/legalization.def','/input.def'))
    args=['bwrap','--die-with-parent','--unshare-user','--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts']
    for p in ('/usr','/bin','/lib','/lib64'):args+=['--ro-bind',p,p]
    for p,d in [(binary,'/native/iEDA'),(RT,'/runtime'),(ref,'/reference'),(source,'/input.def'),(table,'/screened.tsv')]:
        args+=['--ro-bind',str(p),d]
    args+=['--proc','/proc','--dev','/dev','--tmpfs','/tmp','--bind',str(w),'/work','--chdir','/work','--clearenv']
    env=dict(PATH='/usr/bin:/bin',HOME='/tmp',TCL_LIBRARY='/runtime/tcl8.6',LC_ALL='C',OMP_NUM_THREADS='4',
             OMP_THREAD_LIMIT='4',OPENBLAS_NUM_THREADS='1',RESULT_DIR='/work/result',CONFIG_DIR='/work/config',
             IEDA_RT_PORT_NATIVE='1',IEDA_RT_PA_LAZY_TARGETS='1',IEDA_RT_PA_RECT_PRL='1',
             IEDA_RT_PA_ESCAPE_FILE='/screened.tsv',IEDA_RT_PA_WITNESS='/work/pa.tsv',IEDA_RT_SAVE_TG='/work/TG.bin',
             IEDA_RT_SAVE_LA='/work/LA.bin',IEDA_RT_STOP_AFTER_LA='1',IEDA_RT_STATE_BINDING=sha(source))
    if prior:
        tag=prior.stem
        evidence=json.loads((prior.parent/'receipt.json').read_bytes())
        assert sha(prior)==evidence['states'][tag] and evidence['input']==sha(source)
        if evidence['binary']!=sha(binary):
            origin=json.loads((build/('frozen-'+evidence['binary'][:16])/'snapshot.json').read_bytes())
            target=json.loads((binary.parent/'snapshot.json').read_bytes())
            assert tag=='LA' and finish and origin['binary_sha256']==evidence['binary'] and target['binary_sha256']==sha(binary)
            assert origin['upstream_commit']==target['upstream_commit'] and origin['runtime_system_libs_sha256']==target['runtime_system_libs_sha256']
            old,new=origin['irt_source_delta'],target['irt_source_delta']
            delta={k for k in old.keys()|new.keys() if old.get(k)!=new.get(k)}
            assert delta=={'src/operation/iRT/source/module/detailed_router/DetailedRouter.cpp'},delta
        args+=['--ro-bind',str(prior),'/restore.bin']
        env.update(IEDA_RT_RESTORE_STATE='/restore.bin',IEDA_RT_RESTORE_LEVEL=tag)
    if finish:
        assert prior and prior.stem=='LA'
        for key in ('IEDA_RT_STOP_AFTER_LA','IEDA_RT_SAVE_TG','IEDA_RT_SAVE_LA'):
            del env[key]
    for k,v in env.items():args+=['--setenv',k,v]
    args+=['/usr/bin/timeout','--foreground','--kill-after=5','360']
    if debug:
        args+=['/usr/bin/strace','-f','-qq','-k','-e','trace=tgkill','-e','signal=SIGSEGV,SIGABRT',
               '-o','/work/router-stack.txt']
    args+=['/native/iEDA','-script','/work/check.tcl']
    rss=vm=0
    with (w/'stdout.log').open('wb') as log:
        p=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,preexec_fn=limits)
        while p.poll() is None:
            a,b=usage(p.pid);rss=max(rss,a);vm=max(vm,b);time.sleep(.2)
    rt=(w/'result/rt/rt.log').read_text(errors='replace')
    states={f.stem:sha(f) for f in w.glob('*.bin')}
    modules={'PA':('PinAccessor','access'),'SA':('SupplyAnalyzer','analyze'),
             'TG':('TopologyGenerator','generate'),'LA':('LayerAssigner','assign')}
    counts={k:len(re.findall(rf'{cls}\.cpp:\d+ Info {method}\] Starting',rt)) for k,(cls,method) in modules.items()}
    saved=dict(binary=sha(binary),input=sha(source),returncode=p.returncode,rss=rss,vm=vm,states=states,counts=counts,
               restore=prior.stem if prior else None,ended='EDA_LA_MEASUREMENT_STOP' in rt)
    if finish:
        marker='SWERV_STAGE_OK routing' in (w/'stdout.log').read_text(errors='replace')
        routed=w/'result/routing.def'
        saved.update(stage_marker=marker,output_sha256=sha(routed) if routed.is_file() else None)
    save(w/'receipt.json',saved)
    return saved

def run():
    ref=setup();study.mkdir(exist_ok=True)
    meta=json.loads((build/'candidate-v9.json').read_bytes())
    binary=build/('frozen-'+meta['binary_sha256'][:16])/'iEDA'
    assert sha(binary)==meta['binary_sha256']
    direct=trial(ref,binary,'direct')
    assert direct['returncode']==25 and direct['ended'] and set(direct['states'])=={'TG','LA'},direct
    for tag in ('TG','LA'):
        restored=trial(ref,binary,'restore-'+tag,study/'direct'/(tag+'.bin'))
        assert restored['returncode']==25 and restored['ended'] and restored['states']['LA']==direct['states']['LA'],restored
        assert all(restored['counts'][m]==0 for m in ('PA','SA','TG')),restored
        if tag=='TG':assert restored['states']['TG']==direct['states']['TG']
        else: assert restored['counts']['LA']==0
    print('Both native checkpoint restores matched the original layer assignment byte-for-byte.')
    if sys.argv[1:] in (['--finish-sample'],['--diagnose-downstream']):
        debug=sys.argv[1]=='--diagnose-downstream'
        label='sample-downstream-stack' if debug else 'sample-downstream'
        downstream=trial(ref,binary,label,study/'direct/LA.bin',finish=True,debug=debug)
        assert not any(downstream['counts'].values()),downstream
        print(json.dumps(downstream),flush=True)
        assert downstream['returncode']==0 and downstream['stage_marker'] and downstream['output_sha256'],downstream
    if len(sys.argv)==3 and sys.argv[1]=='--downstream-revision':
        version=int(sys.argv[2])
        meta=json.loads((build/f'candidate-v{version}.json').read_bytes())
        binary=build/('frozen-'+meta['binary_sha256'][:16])/'iEDA'
        assert meta['status']=='completed' and sha(binary)==meta['binary_sha256']
        downstream=trial(ref,binary,f'downstream-v{version}',study/'direct/LA.bin',finish=True)
        print(json.dumps(downstream),flush=True)
        assert not any(downstream['counts'].values()) and downstream['returncode']==0 and downstream['stage_marker'] and downstream['output_sha256'],downstream

if __name__=='__main__':
    remote_service.init()
    with remote_service.gate():
        if active_jobs():raise RuntimeError('Native job already active')
        run()
