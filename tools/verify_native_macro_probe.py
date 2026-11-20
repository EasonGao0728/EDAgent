"""Read/validate native MP geometry, then bounded stdcell and fresh DB readback.

Operator commissioning only. No production registration or model invocation.
"""
import copy
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from macro_agent import ieda_runtime as rt
from macro_agent.def_validation import read_def,lef_cells,validate_placement
from macro_agent.task_artifacts import ref,render
from macro_agent.portable_ieda import ENV

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);ap.add_argument('--sparse-macro-profile',action='store_true');args=ap.parse_args()
    source=ROOT/'runs/stage1-native-macro-20261106-01';work=Path(args.output).resolve()
    if not work.is_relative_to(ROOT/'runs'):raise ValueError('Output must be under runs')
    work.mkdir(exist_ok=False)
    for n in ('config','script'):shutil.copytree(source/n,work/n)
    profile={'name':'inherited GCD configuration'}
    if args.sparse_macro_profile:
        config=work/'config/pl_default_config.json';data=json.loads(config.read_text())
        data['PL']['GP']['Density'].update(target_density=0.12,bin_cnt_x=64,bin_cnt_y=64)
        config.write_text(json.dumps(data,indent=2))
        profile={'name':'sparse two-SRAM commissioning profile','target_density':0.12,'bins':[64,64],
            'rationale':'two fixed SRAMs occupy about 10% of this core; avoid 185491 fillers from inherited 0.6 density; finer grid resolves large obstacles',
            'legality_gates_unchanged':True,'source':ref(source/'config/pl_default_config.json'),'actual':ref(config)}
    for n in ('logs','result/pl','result/report','result/feature','result/sta'):(work/n).mkdir(parents=True,exist_ok=True)
    original=read_def(source/'result/iFP_result.def');placed=read_def(source/'result/iPL_result.def')
    lefs=[rt.REFERENCE/'scripts/foundry/sky130/lef'/n for n in ('sky130_fd_sc_hs_merged.lef','sky130_sram_1rw1r_44x64_8.lef')]
    cells={}
    for f in lefs:cells.update(lef_cells(f,placed['units']))
    macros=[n for n,c in original['components'].items() if cells[c['master']]['hard_macro']]
    errors=[];boxes=[]
    expected=copy.deepcopy(original)
    for n in macros:
        if original['components'][n]['placement'] is not None:errors.append('macro_input_not_unplaced:'+n)
        p=placed['components'][n]['placement']
        if not p or p[0]!='PLACED' or p[3]!='N':errors.append('unsupported_macro_placement:'+n);continue
        x,y=p[1:3];w,h=cells[placed['components'][n]['master']]['size'];d=placed['die']
        if not(d[0]<=x and d[1]<=y and x+w<=d[2] and y+h<=d[3]):errors.append('macro_outside_die:'+n)
        box=(x,y,x+w,y+h,n)
        if any(min(box[2],b[2])>max(box[0],b[0]) and min(box[3],b[3])>max(box[1],b[1]) for b in boxes):errors.append('macro_overlap')
        boxes.append(box);expected['components'][n]=placed['components'][n]
    sentinel_cells=[]
    for n,c in original['components'].items():
        if n not in macros and c['placement'] is None and placed['components'].get(n)=={'master':c['master'],'placement':['PLACED',-1,-1,'N']}:
            # Native MP exports untouched stdcells with an invalid sentinel. This is
            # NOT a legal placement; restore UNPLACED for the later native placer.
            sentinel_cells.append(n);expected['components'][n]=placed['components'][n]
    if expected!=placed:errors.append('unexpected_non_macro_change')
    if len(macros)<2:errors.append('insufficient_real_macros')
    report={'scope':'derived public real SRAM integration fixture; not full phase-one or full-backend acceptance',
        'source_probe':ref(source/'probe.json'),'macro_result':ref(source/'result/iPL_result.def'),'placement_profile':profile,
        'macro_check':{'passed':not errors,'errors':errors,'macros':macros,'boxes':boxes},
        'native_mp_export_issue':{'invalid_stdcell_sentinels':sentinel_cells,'raw_full_placement_legal':False,
            'adapter_policy':'Only original UNPLACED stdcells exported at (-1,-1) N are restored to UNPLACED; later real iPL must place and validate all cells'},'stages':[]}
    def save():(work/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    if errors:raise ValueError('Macro geometry/semantic check failed')
    # Status-only transition freezes accepted native coordinates; no coordinates are calculated.
    text=(source/'result/iPL_result.def').read_text()
    for n in macros:
        text,count=re.subn(r'(^\s*-\s+'+re.escape(n)+r'\s+.*?\+)\s+PLACED\b',r'\1 FIXED',text,count=1,flags=re.M|re.S)
        if count!=1:raise ValueError('Cannot freeze exact macro record')
    for n in sentinel_cells:
        text,count=re.subn(r'(^\s*-\s+'+re.escape(n)+r'\s+.*?\+)\s+PLACED\s+\(\s*-1\s+-1\s*\)\s+N\b',r'\1 UNPLACED',text,count=1,flags=re.M|re.S)
        if count!=1:raise ValueError('Cannot restore exact originally unplaced cell')
    fixed=work/'result/macros_fixed.def';fixed.write_text(text)
    fixed_expected=copy.deepcopy(placed)
    for n in macros:fixed_expected['components'][n]['placement'][0]='FIXED'
    for n in sentinel_cells:fixed_expected['components'][n]['placement']=None
    if read_def(fixed)!=fixed_expected:raise ValueError('Status-only transition modified other semantics')
    report['freeze']={'file':ref(fixed),'method':'DEF status only; native MP coordinates preserved','macros':macros}
    pre='''flow_init -config /work/config/flow_config.json
db_init -config /work/config/db_default_config.json
source /work/script/DB_script/db_path_setting.tcl
source /work/script/DB_script/db_init_lef.tcl
source /work/script/DB_script/db_init_lib.tcl
source /work/script/DB_script/db_init_sdc.tcl
'''
    for stage,inp,body in [('stdcell','macros_fixed.def','run_placer -config /work/config/pl_default_config.json\n'),('readback','stdcell.def','')]:
        (work/(stage+'.tcl')).write_text('if {[catch {\n'+pre+'def_init -path /work/result/'+inp+'\n'+body+
            'def_save -path /work/result/'+stage+'.def\nputs "OK '+stage+'"\n} message]} {puts stderr $message; exit 1}\nflow_exit\n')
        env={**ENV,'CONFIG_DIR':'/work/config','RESULT_DIR':'/work/result','TCL_SCRIPT_DIR':'/work/script','OMP_NUM_THREADS':'2'}
        name='aieda-macro-check-'+uuid.uuid4().hex[:12]
        command=rt.docker()+['run','--rm','--pull=never','--name',name,'--network','none','--cpus','2','--memory','4g','--pids-limit','256','--ulimit','core=0',
            '--mount',f'type=bind,source={rt.REFERENCE},target=/reference,readonly','--mount',f'type=bind,source={work},target=/work','--workdir','/work']
        for k,v in env.items():command+=['--env',k+'='+v]
        command += [rt.IMAGE,'timeout','--kill-after=5','120','iEDA','-script','/work/'+stage+'.tcl']
        start=time.monotonic();log=work/'logs'/(stage+'.log')
        with log.open('w') as stream:
            try:code=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,timeout=140,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode
            except subprocess.TimeoutExpired:
                try:rt.invoke(['kill',name])
                except RuntimeError:pass
                code=124
        report['stages'].append({'stage':stage,'exit_code':code,'seconds':round(time.monotonic()-start,3),'log':ref(log)});save()
        if code or 'OK '+stage not in log.read_text(errors='replace'):raise ValueError('Native stage failed: '+stage)
        if stage=='stdcell':
            report['placement_check']=validate_placement(original,read_def(fixed),read_def(work/'result/stdcell.def'),lefs)
            report['backend']=rt.parse_placement_report(work/'result/pl/report/summary_report.txt');save()
            if not report['placement_check']['passed'] or not report['backend']['placement_checks_passed']:raise ValueError('Macro/stdcell validation failed')
    report['readback_equal']=read_def(work/'result/stdcell.def')==read_def(work/'result/readback.def')
    report['preview']=render(work/'result/readback.def',lefs,work/'placement.svg');save()
    print(json.dumps({'macro_check':report['macro_check'],'placement_check':report['placement_check'],'readback_equal':report['readback_equal'],'evidence':str(work/'verification.json')}))

if __name__=='__main__':main()
