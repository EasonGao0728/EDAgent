"""Bounded local commissioning probes; never commit results to an Agent task."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from macro_agent import ieda_runtime as rt
from macro_agent.portable_ieda import ENV,adapt_placement_config
from macro_agent.def_validation import read_def,lef_cells
from macro_agent.backend_checks import routing_gate,transformation_check

def ref(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('kind',choices=['route_repair','route_io','macro']);ap.add_argument('--output',required=True)
    a=ap.parse_args();work=Path(a.output).resolve()
    if not work.is_relative_to(ROOT/'runs') or work.exists():raise ValueError('Fresh directory under runs required')
    work.mkdir();(work/'logs').mkdir();record={'kind':a.kind,'operator_diagnostic_only':True,'agent_admitted':False,
        'image':rt.IMAGE,'threads':2,'memory_gb':4,'container_timeout_seconds':120,'stages':[]}
    env={**ENV,'OMP_NUM_THREADS':'2','CONFIG_DIR':'/work/config','RESULT_DIR':'/work/result','TCL_SCRIPT_DIR':'/work/script'}
    mounts=[]
    if a.kind in ('route_repair','route_io'):
        task_path=ROOT/'runs/stage1-routed-baseline-20261106-01/task.json';task=json.loads(task_path.read_text())
        if task['completed'][-1]!='legalization':raise ValueError('Expected accepted legalization checkpoint')
        source=Path(task['accepted_work']);reference=ROOT/'cases/ibench/gcd_legacy'
        for name in ('config','script','result'):shutil.copytree(source/name,work/name)
        record['source_task']=ref(task_path);record['source_def']=ref(source/'result/legalization.def')
        profile=ROOT/'runs/dsh-delivery-review-20261106/server-reference/aes13_flow.py'
        record['profile_source']=ref(profile)
        # Only repair switches present in the saved server script; no relaxed quality gate.
        if a.kind=='route_repair':
            env.update({k:'1' for k in ('IEDA_RT_FINAL_MINAREA_HOTSPOT_SORT','IEDA_RT_RULE_AWARE_COST',
                'IEDA_RT_ENHANCED_MINAREA_REPAIR','IEDA_RT_COMPONENT_ESCALATE','IEDA_RT_COMPONENT_SCHEDULE',
                'IEDA_RT_PRL_SHORT_REPAIR','IEDA_RT_RULE_BUCKET_PRIORITY')})
            env['IEDA_RT_BEST_EFFORT_SKIP_FINAL_MINAREA']='0'
        script=(Path(task['events'][-1]['work'])/'backend-stage.tcl').read_text().replace('-thread_number 4','-thread_number 2')
        if a.kind=='route_io':
            anchor='def_init -path /work/result/legalization.def\n'
            if script.count(anchor)!=1:raise ValueError('Unexpected routing script')
            script=script.replace(anchor,anchor+'auto_place_pins -layer met3 -width 800 -height 800\ndef_save -path /work/result/io_replanned.def\n')
            record['io_variant']={'layer':'met3','size_dbu':[800,800],'source_tech_lef':ref(reference/'pdk/lef/sky130_fd_sc_hd.tlef'),
                'rationale':'isolate met5 IO/PDN obstacle shorts; met3 WIDTH=0.3um AREA=0.24um2; 0.8um square clears these two minimum rules',
                'input_contract_changed':True,'original_task_modified':False,'formal_new_flow_required':True}
        (work/'repair.tcl').write_text(script)
        stages=[('routing_repair','repair.tcl')]
    else:
        source=ROOT/'runs/ieda-mp-real-sram-probe-v4-20261105';reference=rt.REFERENCE
        for name in ('config','script'):shutil.copytree(source/name,work/name)
        for name in ('gcd_sram.v','mp.tcl','aimp.tcl'):shutil.copyfile(source/name,work/name)
        for name in ('report','pl','feature','sta'):(work/'result'/name).mkdir(parents=True,exist_ok=True)
        record['netlist_source']=ref(source/'gcd_sram.v')
        record['case_scope']='derived harness with real public SRAM LEF/LIB; commissioning, not final G1-Macro acceptance'
        adapt_placement_config(work/'config/pl_default_config.json')
        pl=json.loads((work/'config/pl_default_config.json').read_text());pl['PL']['num_threads']=2
        write(work/'config/pl_default_config.json',pl)
        env.update(FOUNDRY_DIR='/reference/scripts/foundry/sky130',DESIGN_TOP='gcd',NETLIST_FILE='/work/gcd_sram.v',
            SDC_FILE='/reference/scripts/foundry/sky130/sdc/gcd.sdc',DIE_AREA='0 0 1500 1500',CORE_AREA='10 10 1490 1490')
        hmetis=reference/'src/third_party/hmetis/hmetis2.0pre1'
        mounts+=['--mount',f'type=bind,source={hmetis},target=/src/third_party/hmetis/hmetis2.0pre1,readonly']
        record['hmetis_source']=ref(hmetis)
        for script,marker in [('mp.tcl','MP_END'),('aimp.tcl','AIMP_END')]:
            body=(work/script).read_text().replace('flow_exit','')
            (work/script).write_text('if {[catch {\n'+body+'\n} message]} {puts stderr $message; exit 1}\nflow_exit\n')
        stages=[('floorplan','script/iFP_script/run_iFP.tcl'),('macro','mp.tcl'),('aimp','aimp.tcl')]
    record['environment']=env;write(work/'probe.json',record)
    for stage,script in stages:
        name='aieda-probe-'+uuid.uuid4().hex[:12]
        command=rt.docker()+['run','--rm','--pull=never','--name',name,'--network','none','--cpus','2','--memory','4g',
            '--pids-limit','256','--ulimit','core=0','--mount',f'type=bind,source={reference},target=/reference,readonly',
            '--mount',f'type=bind,source={work},target=/work','--workdir','/work']+mounts
        for k,v in env.items():command+=['--env',k+'='+v]
        command += [rt.IMAGE,'timeout','--kill-after=5','120','iEDA','-script','/work/'+script]
        began=time.monotonic();log=work/'logs'/f'{stage}.log'
        with log.open('w',encoding='utf-8') as stream:
            try:code=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,timeout=140,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode
            except subprocess.TimeoutExpired:
                try:rt.invoke(['kill',name],timeout=10)
                except RuntimeError:pass
                code=124
        item={'stage':stage,'exit_code':code,'seconds':round(time.monotonic()-began,3),'log':ref(log)}
        record['stages'].append(item);write(work/'probe.json',record);print(json.dumps(item),flush=True)
        if code:break
    if a.kind in ('route_repair','route_io'):
        summary=work/'result/rt/violation_reporter/route_summary.json'
        if summary.exists():
            data=json.loads(summary.read_text());record['route_summary']=ref(summary);record['gate']=routing_gate(data)
            record['drc_count']=data['coverage']['drc_output_violation_count']
            before=work/'result'/('io_replanned.def' if a.kind=='route_io' else 'legalization.def')
            record['transformation']=transformation_check(read_def(before),read_def(work/'result/routing.def'),'routing')
            if a.kind=='route_io':
                original=read_def(work/'result/legalization.def');changed=read_def(before)
                record['io_replan_only']=(set(original['pins'])==set(changed['pins']) and
                    {k:v for k,v in original.items() if k!='pins'}=={k:v for k,v in changed.items() if k!='pins'})
    else:
        f=work/'result/iFP_result.def'
        if f.exists():
            initial=read_def(f);cells=lef_cells(reference/'scripts/foundry/sky130/lef/sky130_sram_1rw1r_44x64_8.lef',initial['units'])
            macros=[n for n,c in initial['components'].items() if c['master'] in cells and cells[c['master']]['hard_macro']]
            record['macros_before']={n:initial['components'][n] for n in macros}
            record['outputs']={}
            for name in ('iPL_result.def','aimp_result.def'):
                p=work/'result'/name
                if p.exists():
                    d=read_def(p);record['outputs'][name]={'file':ref(p),'macros':{n:d['components'][n] for n in macros},'same_as_floorplan':d==initial}
    write(work/'probe.json',record);print('EVIDENCE='+str(work/'probe.json'))

if __name__=='__main__':main()
