"""Small read-only runtime capability probe; writes only a temporary personal folder."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

root=Path.home()/'ibench-demo'
runtime=root/'portable-runtime-v1'
expected='d9ae28962bf622f1139e2b438c6f69deb646d93a48ece783da80a082d607694a'
actual=hashlib.sha256((runtime/'iEDA').read_bytes()).hexdigest()
if actual!=expected:raise ValueError('Runtime hash mismatch')
names=['placer_run_mp','aimp_random','run_cts','run_incremental_flow','init_rt','run_rt','run_drc','gds_save']
with tempfile.TemporaryDirectory(prefix='capability-probe-',dir=root) as directory:
    work=Path(directory);script=work/'probe.tcl'
    script.write_text('\n'.join('puts "CAPABILITY '+name+' [llength [info commands '+name+']]"' for name in names)+'\nexit\n')
    env={**os.environ,'OMP_NUM_THREADS':'1','TCL_LIBRARY':str(runtime/'tcl8.6')}
    command=['timeout','--kill-after=3','20','prlimit','--as=1073741824','--core=0','--',str(runtime/'ld-linux-x86-64.so.2'),'--library-path',str(runtime/'lib'),str(runtime/'iEDA'),'-script',str(script)]
    p=subprocess.run(command,cwd=work,env=env,capture_output=True,text=True,timeout=25)
    print(json.dumps({'binary_sha256':actual,'exit_code':p.returncode,'commands':[line for line in p.stdout.splitlines() if line.startswith('CAPABILITY ')],
        'stderr_tail':p.stderr[-1000:],'threads':1,'memory_limit_bytes':1073741824,'timeout_seconds':20,'scope':'command registration only, not algorithm validation'}))
