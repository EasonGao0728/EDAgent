"""Read-only native connectivity audit and independent geometry check of a frozen route."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from sram_escape_check import BASE, DEF_HASH, ROOT, RT, SOURCE, active_jobs, limits, remote_service, save, setup, sha
from verify_route_v7 import AUDITOR_SHA, graph_check, read_def, validate

SNAPS=Path('/srv/benchmarks/iBench/benchmarks/tools/runtime_snapshots_v2')
BIN=SNAPS/'iEDA-native-auditor-96fcd39cb8a62110'
V7='06edd7bb810f919208b5ca39b2c6a585e295abfab1f472af0fbcc0a39b160fd3'
V9='86665afd3583436bf90f421847887fa535f6b807f9ac427999fe49d3c2e438fe'
V11='a299a1d992acf5e9d56955d1ae111c8220803f62e4c4be55af6a1262e9679b0f'
V12='6f66e655f6ca5d82fe99820dac17858b65428cba0cf0490a2fe21034cdca4b15'

V17='4bcf90e29e58c12d68c3312fc1aba7214b51fa08a3bcac3b0ee25994d8d06092'
V16='38e1d582f61d1d524f367ecffde779684fffda49820feb938eef97fd04707555'
V14='6e2bb1c604846cbc4c793194463472412dbd82deaa7e3432e48e3dfb1371c243'
V13='e7e4a2a204f01c3a20214382db99843b448441da5d836c1e3b6abf0e5fb7e811'

def main(binary_sha,sample=False):
    if sample:
        assert binary_sha==V11
        work=ROOT/'runs/bp-multi-compact-layer-test/downstream-v11'
        source=ROOT/'runs/bp-multi-official-pa-v1/abutment-126.def'
        graph=json.loads((work/'physical-audit.json').read_bytes())
        assert graph['graph']['passed'] and graph['source']==sha(source) and graph['artifact']==sha(work/'result/routing.def')
    elif binary_sha in (V12,V13,V14,V16,V17):
        work=ROOT/'runs/bp-multi-official-pa-v1'/('full-lazy-'+V11[:12])/{V12:'recovery-v12',V13:'recovery-v13',V14:'recovery-v14',V16:'recovery-v16',V17:'recovery-v17'}[binary_sha]
    else:
        work=ROOT/'runs/bp-multi-official-pa-v1'/('full-lazy-'+binary_sha[:12])
    batch_parents=[]
    if binary_sha==V17:
        import os
        from resume_space import attempt_name
        count=int(os.environ.get('BP_MULTI_RETRY','0'))
        batch_parents=[work.parent/attempt_name(17,i) for i in range(count)]
        work=work.parent/attempt_name(17,count)
    receipt=json.loads((work/'receipt.json').read_bytes())
    if sample:
        assert receipt['input']==sha(source) and receipt['binary']==binary_sha
    else:
        assert receipt['input_sha256']==sha(SOURCE)==DEF_HASH and receipt['binary_sha256']==binary_sha and receipt['pa']['passed']
    assert receipt['returncode']==0 and receipt['stage_marker']
    routed=work/'result/routing.def'
    digest=sha(routed)
    assert sha(BIN/'iEDA')==AUDITOR_SHA
    ref=setup()
    directory=work/'routed-def-audit'
    if not (directory/'receipt.json').exists():
        directory.mkdir(exist_ok=False)
        shutil.copytree(BASE/'config',directory/'config')
        tcl=(work/('check.tcl' if sample else 'route.tcl')).read_text().split('init_rt ')[0].replace('/frozen.def','/input.def')
        tcl+='init_rt -temp_directory_path /work/audit -bottom_routing_layer metal2 -top_routing_layer metal6 -thread_number 4\nrun_rt\ndestroy_rt\nputs BENCHMARK_PHYSICAL_AUDIT_OK\n} message]} {puts stderr $message; exit 1}\nflow_exit\n'
        (directory/'audit.tcl').write_text(tcl)
        cmd=['bwrap','--die-with-parent','--unshare-user','--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts']
        for p in ('/usr','/bin','/lib','/lib64'):cmd+=['--ro-bind',p,p]
        for p,d in [(RT,'/runtime'),(BIN,'/auditor'),(ref,'/reference'),(routed,'/input.def')]:cmd+=['--ro-bind',str(p),d]
        cmd+=['--proc','/proc','--dev','/dev','--tmpfs','/tmp','--bind',str(directory),'/work','--chdir','/work','--clearenv']
        env=dict(PATH='/usr/bin:/bin',HOME='/tmp',TCL_LIBRARY='/runtime/tcl8.6',LC_ALL='C',OMP_NUM_THREADS='4',
                 OMP_THREAD_LIMIT='4',OPENBLAS_NUM_THREADS='1',RESULT_DIR='/work',CONFIG_DIR='/work/config',
                 IEDA_RT_BEST_EFFORT='0', IEDA_RT_DR_RESUME_IMPORTED='0',IEDA_RT_VIOLATION_REPAIR='1',
                 IEDA_RT_VR_POST_BEST_REPAIR='1',IEDA_RT_VR_REPAIR_ONLY='1',IEDA_RT_VR_CONNECTIVITY_AUDIT_ONLY='1',
                 IEDA_RT_NATIVE_LAYER_TRACKS='1',IEDA_RT_NATIVE_LAYER_GRAPH='1')
        for k,v in env.items():cmd+=['--setenv',k,v]
        if binary_sha not in (V16,V17):cmd+=['/usr/bin/timeout','--foreground','--kill-after=5','600']
        cmd+=['/runtime/ld-linux-x86-64.so.2',
              '--library-path','/auditor/lib:/runtime/lib','/auditor/iEDA','-script','/work/audit.tcl']
        with (directory/'audit.log').open('wb') as log:
            rc=subprocess.run(cmd,preexec_fn=limits,stdout=log,stderr=subprocess.STDOUT).returncode
        audit=directory/'audit/detailed_router/connectivity_audit.json'
        result=dict(binary_sha256=AUDITOR_SHA,input_sha256=digest,input_sha256_after=sha(routed),returncode=rc,
                    audit_sha256=sha(audit) if audit.is_file() else None,script_sha256=sha(directory/'audit.tcl'))
        save(directory/'receipt.json',result)
        if rc or not audit.exists():raise RuntimeError(result)
        shutil.copyfile(audit,directory/'connectivity_audit.json')
    if sample:
        expected={name:pins for name,pins in read_def(source)['nets'].items() if len(pins)>=2}
        result=graph_check(directory,digest,expected)
        save(work/'native-sample-graph.json',result)
        print(json.dumps(result),flush=True)
        return result['passed']
    tech=ref/'data/input2.lef'
    cells=[ref/f'data/input{i}.lef' for i in range(3,10)]
    result=validate(work,SOURCE,binary_sha,directory,tech,cells,ROOT/'runs/bp-multi-sram-ce-escape-drc-v1/screened-escapes.tsv',
                    prior_la=work.parent if binary_sha in (V12,V13,V14,V16,V17) else None,
                    prior_sr=work.parent/'recovery-v12' if binary_sha in (V13,V14,V16,V17) else None,
                    batch_parents=batch_parents,prior_batch=work.parent/'recovery-v16' if binary_sha==V17 else None,
                    prior_ta=work.parent/'recovery-v13' if binary_sha in (V14,V16,V17) else None)
    save(work/'route-validation.json',result)
    print(json.dumps({k:v.get('passed') for k,v in result.items() if isinstance(v,dict)}))
    return result['passed']

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',type=int,choices=(7,9,11,12,13,14,16,17),default=7)
    parser.add_argument('--sample',action='store_true')
    options=parser.parse_args()
    remote_service.init()
    with remote_service.gate():
        if active_jobs():raise RuntimeError('Native job already active')
        sys.exit(0 if main({7:V7,9:V9,11:V11,12:V12,13:V13,14:V14,16:V16,17:V17}[options.version],options.sample) else 1)
