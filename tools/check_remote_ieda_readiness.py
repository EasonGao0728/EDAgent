"""Short own-account smoke test. No design import, placement or routing."""
import json, subprocess
from pathlib import Path
CODE=r'''
import os,json,pathlib,hashlib,subprocess,shutil
assert os.getuid()==1015
base=pathlib.Path('/srv/edagent')
root=base/'diagnostics-20261111';root.mkdir(exist_ok=True)
runtime=base/'portable-runtime-v1';router=base/'aes-p1-20261108-v5c/environments/ieda-aes-router/iEDA'
def ref(p):return {'exists':p.is_file(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None}
r={'uid':os.getuid(),'runtime':ref(runtime/'iEDA'),'router':ref(router),'tmux_available':bool(shutil.which('tmux')),'free_home_bytes':shutil.disk_usage(base).free}
assert r['router']['sha256']=='9f6c91ac6a58a00feaa63ba5eef37cfd240a4b60dd1fedba0654439763a3a6f8'
script=root/'ieda-smoke.tcl';script.write_text('puts "IEDA_REMOTE_DIAGNOSTIC_OK"\nflow_exit\n')
argv=['taskset','-c',str(min(os.sched_getaffinity(0))),'timeout','20','prlimit','--as=536870912','--core=0','--',str(runtime/'ld-linux-x86-64.so.2'),'--library-path',str(runtime/'lib'),str(router),'-script',str(script)]
p=subprocess.run(argv,cwd=root,env=dict(os.environ,TCL_LIBRARY=str(runtime/'tcl8.6'),LC_ALL='C'),capture_output=True,text=True,timeout=25)
r.update(returncode=p.returncode,native_smoke_passed=p.returncode==0 and 'IEDA_REMOTE_DIAGNOSTIC_OK' in p.stdout,stdout_tail=p.stdout[-1800:],stderr_tail=p.stderr[-800:],design_loaded=False,layout_started=False)
print(json.dumps(r))
'''
p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','eda-backup','python3 -B -'],input=CODE,text=True,encoding='utf-8',capture_output=True,timeout=50)
if p.returncode:raise RuntimeError(p.stderr[-2000:])
r=json.loads(p.stdout)
out=Path(__file__).resolve().parents[1]/'runs/aes-p1-20261108/diagnostics-20261111/remote-readiness.json'
out.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(r,ensure_ascii=False))
