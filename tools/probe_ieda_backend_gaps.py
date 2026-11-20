"""Bounded commissioning of remaining native backend stages, outside Agent admission."""
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
from macro_agent.portable_ieda import ENV
from macro_agent.def_validation import read_def


def ref(p):
    return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--task',required=True);ap.add_argument('--output',required=True)
    ap.add_argument('--adapt-to-schema',action='store_true')
    a=ap.parse_args();task=Path(a.task).resolve();work=Path(a.output).resolve()
    if not work.is_relative_to(ROOT/'runs') or work.exists():raise ValueError('Fresh runs directory required')
    state=json.loads(task.read_text())
    if state['status']!='target_met' or state['contract']['case_id']!='ibench_gcd_legacy':raise ValueError('Accepted HD task required')
    source=Path(state['accepted_work']);reference=Path(state['contract'].get('input_root') or ROOT/'cases/ibench/gcd_legacy')
    work.mkdir()
    for d in ('config','script','result'):shutil.copytree(source/d,work/d)
    (work/'logs').mkdir()
    for d in ('no','to','to_drv','to_hold'):(work/'result'/d).mkdir(exist_ok=True)
    record={'operator_only':True,'agent_admitted':False,'source_task':ref(task),
            'source_def':ref(Path(state['final_def']['path'])),'image':rt.IMAGE,
            'resource_limits':{'cpu_quota':4,'memory_gib':8,'pids':256,'native_seconds':120,'host_seconds':140},
            'stages':[]}
    if a.adapt_to_schema:
        changes=[]
        for stage,inp in [('drv','cts.def'),('hold','to_drv.def')]:
            path=work/'config'/('to_default_config_'+stage+'.json');old=json.loads(path.read_text())
            cfg={k:v for k,v in old.items() if k in ('file_path','fix_fanout','optimize_drv','optimize_hold','optimize_setup','DRV_insert_buffers','setup_insert_buffers','hold_insert_buffers')}
            mapping={'setup_slack_margin':'setup_target_slack','hold_slack_margin':'hold_target_slack',
                'max_buffer_percent':'max_insert_instance_percent','max_utilization':'max_core_utilization',
                'number_passes_allowed_decreasing_slack':'number_of_decreasing_slack_iter',
                'rebuffer_max_fanout':'max_allowed_buffering_fanout','split_load_min_fanout':'min_divide_fanout'}
            cfg.update({new:old[key] for key,new in mapping.items()})
            cfg.update(routing_tree='flute',optimize_endpoints_percent=1.0,drv_optimize_iter_number=5,
                specific_prefix={k:{'make_buffer':k+'_buffer_','make_net':k+'_net_'} for k in ('drv','hold','setup')})
            cfg['file_path'].update(design_work_space='/work/result/to_'+stage,
                sdc_file='/reference/sdc/gcd.sdc',lib_files=['/reference/pdk/lib/sky130_fd_sc_hd__tt_025C_1v80.lib'],
                lef_files=['/reference/pdk/lef/sky130_fd_sc_hd.tlef','/reference/pdk/lef/sky130_fd_sc_hd_merged.lef'],
                def_file='/work/result/'+inp,output_def='/work/result/to_'+stage+'/ito_result.def',
                report_file='/work/result/to_'+stage+'/report.txt',gds_file='/work/result/to_'+stage+'/to.gds')
            path.write_text(json.dumps(cfg,indent=2))
            changes.append({'stage':stage,'config':ref(path),'explicit_field_mapping':mapping})
        record['to_profile']={'status':'operator-only candidate; runtime validation required',
            'source':'https://github.com/OSCC-Project/iEDA/blob/master/src/operation/iTO/source/config/Config.json',
            'native_binary_key_strings_also_inspected':True,'changes':changes}
    def save():(work/'verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    pre='''flow_init -config /work/config/flow_config.json
db_init -config /work/config/db_default_config.json
source /work/script/DB_script/db_path_setting.tcl
source /work/script/DB_script/db_init_lef.tcl
db_init -lib_path $LIB_PATH
db_init -sdc_path $SDC_PATH
'''
    stages=[('fanout','iFP_result.def','run_no_fixfanout -config /work/config/no_default_config_fixfanout.json'),
            ('to_drv','cts.def','run_to_drv -config /work/config/to_default_config_drv.json'),
            ('to_hold','to_drv.def','run_to_hold -config /work/config/to_default_config_hold.json'),
            ('gds_native','routed_readback.def','gds_save -path /work/result/native.gds2')]
    save()
    for stage,inp,command in stages:
        if not (work/'result'/inp).is_file():
            record['stages'].append({'stage':stage,'status':'blocked','reason':'missing input '+inp});save();continue
        body=pre+'def_init -path /work/result/'+inp+'\n'+command+'\n'
        if stage!='gds_native':body+='def_save -path /work/result/'+stage+'.def\nnetlist_save -path /work/result/'+stage+'.v -exclude_cell_names {}\n'
        script=work/(stage+'.tcl')
        script.write_text('if {[catch {\n'+body+'puts "PROBE_OK '+stage+'"\n} message]} {puts stderr $message; exit 1}\nflow_exit\n')
        name='aieda-gap-'+uuid.uuid4().hex[:12]
        args=rt.docker()+['run','--rm','--pull=never','--name',name,'--network','none','--cpus','4','--memory','8g','--pids-limit','256','--ulimit','core=0',
            '--mount',f'type=bind,source={reference},target=/reference,readonly','--mount',f'type=bind,source={work},target=/work','--workdir','/work']
        for k,v in {**ENV,'OMP_NUM_THREADS':'4','RESULT_DIR':'/work/result','CONFIG_DIR':'/work/config'}.items():args+=['--env',k+'='+v]
        args += [rt.IMAGE,'timeout','--kill-after=5','120','iEDA','-script','/work/'+stage+'.tcl']
        start=time.monotonic();log=work/'logs'/(stage+'.log')
        with log.open('w') as out:
            try:code=subprocess.run(args,stdout=out,stderr=subprocess.STDOUT,timeout=140,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode
            except subprocess.TimeoutExpired:
                try:rt.invoke(['kill',name])
                except RuntimeError:pass
                code=124
        complete=code==0 and 'PROBE_OK '+stage in log.read_text(errors='replace')
        item={'stage':stage,'process_completed':complete,'exit_code':code,'seconds':round(time.monotonic()-start,3),'log':ref(log),'script':ref(script)}
        if complete and stage!='gds_native':
            before=read_def(work/'result'/inp);after=read_def(work/'result'/(stage+'.def'))
            item['differences']={'added_instances':sorted(set(after['components'])-set(before['components'])),
                'removed_instances':sorted(set(before['components'])-set(after['components'])),
                'changed_masters':[n for n in before['components'] if n in after['components'] and before['components'][n]['master']!=after['components'][n]['master']],
                'same_logical_nets':before['nets']==after['nets']}
            item['quality_accepted']=False
        if complete and stage=='gds_native':
            # Reader only: never convert/rewrite the native iEDA artifact.
            import klayout.db as db
            try:
                native=work/'result/native.gds2';layout=db.Layout();layout.read(str(native))
                design=read_def(work/'result'/inp);die=design['die']
                tops=[{'name':c.name,'bbox_dbu':str(c.bbox()),'width_um':c.bbox().width()*layout.dbu,'height_um':c.bbox().height()*layout.dbu,'children':c.child_instances()} for c in layout.top_cells()]
                expected=[(die[2]-die[0])/design['units'],(die[3]-die[1])/design['units']]
                top=layout.cell(design['design'])
                errors=[]
                if top is None:errors.append('missing_design_top')
                elif abs(top.bbox().width()*layout.dbu-expected[0])>0.01 or abs(top.bbox().height()*layout.dbu-expected[1])>0.01:errors.append('die_scale_mismatch')
                geometry=next((t for t in tops if t['name']=='DIEAREA'),None)
                if geometry and (geometry['width_um']<expected[0]*0.5 or geometry['height_um']<expected[1]*0.5):errors.append('native_geometry_scale_mismatch')
                item['gds_validation']={'passed':not errors,'errors':errors,'producer':'native iEDA gds_save','reader_only':'KLayout','modified_by_reader':False,
                    'file':ref(native),'dbu_um':layout.dbu,'expected_die_um':expected,'tops':tops,'layers':layout.layers(),
                    'signoff_clean':False,'library_transistor_geometry_merged':False}
            except Exception as exc:item['gds_validation']={'passed':False,'error':str(exc)}
        record['stages'].append(item);save();print(json.dumps(item,ensure_ascii=False),flush=True)
    print('EVIDENCE='+str(work/'verification.json'))


if __name__=='__main__':main()
