"""Commission report commands against an accepted routed DEF, without rerouting."""
import json,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from macro_agent import ieda_runtime as rt
from macro_agent.portable_ieda import ENV
work=ROOT/'runs/stage1-native-reports-20261106'
state=json.loads((ROOT/'runs/stage1-routed-baseline-20261106-04/task.json').read_text())
source=Path(state['accepted_work']);reference=ROOT/'cases/ibench/gcd_legacy'
work.mkdir(exist_ok=True)
if not (work/'config').exists():
    for d in ('config','script','result'):shutil.copytree(source/d,work/d)
pre='''flow_init -config /work/config/flow_config.json
db_init -config /work/config/db_default_config.json
source /work/script/DB_script/db_path_setting.tcl
source /work/script/DB_script/db_init_lef.tcl
db_init -lib_path $LIB_PATH
db_init -sdc_path $SDC_PATH
def_init -path /work/result/routed_readback.def
'''
tests={
 'introspection':'foreach cmd {run_drc init_drc check_def init_rcx run_rcx run_sta} {puts "CMD $cmd"; if {[llength [info procs $cmd]]} {puts [info body $cmd]}}',
}
for name,cmd in tests.items():
    script=work/(name+'.tcl');log=work/(name+'.log')
    script.write_text('if {[catch {\n'+pre+cmd+'\nputs "PROBE_OK"\n} message]} {puts stderr $message; exit 1}\nflow_exit\n')
    args=rt.docker()+['run','--rm','--pull=never','--name','aieda-report-probe','--network','none','--cpus','4','--memory','8g','--pids-limit','256',
       '--mount',f'type=bind,source={reference},target=/reference,readonly','--mount',f'type=bind,source={work},target=/work']
    for k,v in {**ENV,'OMP_NUM_THREADS':'4','OMP_THREAD_LIMIT':'4','RESULT_DIR':'/work/result','CONFIG_DIR':'/work/config'}.items():args+=['--env',k+'='+v]
    args += [rt.IMAGE,'timeout','--kill-after=5','120','iEDA','-script','/work/'+name+'.tcl']
    with log.open('w') as out:
        try:code=subprocess.run(args,stdout=out,stderr=subprocess.STDOUT,timeout=140,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode
        except subprocess.TimeoutExpired:
            rt.invoke(['kill','aieda-report-probe']);code=124
    print(name,code,flush=True)
