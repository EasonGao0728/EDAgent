"""Operator diagnostic only, not an admitted Agent backend or acceptance run."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from macro_agent import ieda_runtime as r
import subprocess
p=r.ROOT/'runs'/('ieda-mp-real-sram-probe-v4-20261105' if '--v4' in sys.argv else 'ieda-mp-real-sram-probe-20261105')
env={'CONFIG_DIR':'/work/config','FOUNDRY_DIR':'/reference/scripts/foundry/sky130','RESULT_DIR':'/work/result','TCL_SCRIPT_DIR':'/work/script','DESIGN_TOP':'gcd','NETLIST_FILE':'/work/gcd_sram.v','SDC_FILE':'/reference/scripts/foundry/sky130/sdc/gcd.sdc','DIE_AREA':'0 0 1500 1500','CORE_AREA':'10 10 1490 1490','OMP_NUM_THREADS':'4'}
for stage,script in [('floorplan-v3','/work/script/iFP_script/run_iFP.tcl'),('macro-v3','/work/mp.tcl')]:
    args=['run','--pull=never','--rm','--network','none','--cpus','4','--memory','8g','--ulimit','core=0','--mount',f'type=bind,source={r.REFERENCE},target=/reference,readonly','--mount',f'type=bind,source={p},target=/work','--workdir','/work']
    for k,v in env.items():args+=['--env',k+'='+v]
    if '--v4' in sys.argv:
        args+=['--mount',f'type=bind,source={r.REFERENCE}/src/third_party/hmetis/hmetis2.0pre1,target=/src/third_party/hmetis/hmetis2.0pre1,readonly']
    args += [r.IMAGE,'/usr/bin/timeout','--kill-after=5','60','iEDA','-script',script]
    with (p/'logs'/f'{stage}.log').open('w') as log:
        z=subprocess.run(r.docker()+args,stdout=log,stderr=subprocess.STDOUT,timeout=75)
    print(stage,z.returncode,flush=True)
    if z.returncode:break
