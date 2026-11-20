"""Bounded, identical native AES stages for Linux baseline and desktop adapter.

The runner is not an Agent loop. Failed checks remain failed and never certify P1.
"""
import hashlib,json,os,re,shutil,signal,subprocess,time,uuid
from pathlib import Path
from .portable_ieda import IMAGE,ENV,BINARY_SHA256
from .def_validation import read_def,validate_placement
from .backend_checks import routing_gate,drc_gate,route_records,transformation_check
from .aes_netlist import verify as verify_netlist

STAGES=['import_netlist','floorplan','fanout','placement','validate','export_def','cts','to_drv','to_hold','legalization','routing','filler','drc','timing','gds_export','routed_readback']
VERSION='aes-hd-native-full-v5-drc-artifact-budget'
ROUTER_SHA256='9f6c91ac6a58a00feaa63ba5eef37cfd240a4b60dd1fedba0654439763a3a6f8'
SINGLE_FILE_LIMIT_BYTES=1024**3
WORK_LIMIT_BYTES=4*1024**3

def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def prune_duplicate_drc_exports(work):
    """Remove only byte-identical secondary JSON exports in a private attempt.

    Keep both canonical detail files, counts, every violation and all text logs.
    This changes storage only, after the native DRC writer has exited.
    """
    work=Path(work).resolve();removed=[]
    for name in ('violations.json','violation_map.json'):
        canonical=work/'result/report'/name
        duplicate=work/'result/report/drc.rpt.artifacts'/name
        if not duplicate.exists():continue
        for p in (canonical,duplicate):
            if p.is_symlink() or p.resolve()!=p or not p.is_relative_to(work) or not p.is_file():
                raise ValueError('Unsafe DRC duplicate path: '+str(p))
        def checksum(p):
            with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
        expected=checksum(canonical)
        if duplicate.stat().st_size!=canonical.stat().st_size or checksum(duplicate)!=expected:
            raise ValueError('DRC secondary export differs; retaining both files')
        removed.append({'removed':duplicate.relative_to(work).as_posix(),
            'canonical':canonical.relative_to(work).as_posix(),'sha256':expected,'bytes':duplicate.stat().st_size})
    # Validate both pairs before any deletion. No directory or computed subtree removal.
    for item in removed:(work/item['removed']).unlink()
    if removed:
        write(work/'drc-storage-dedup.json',{'method':'verified identical secondary exports only',
            'details_preserved':True,'removed':removed,'freed_bytes':sum(r['bytes'] for r in removed)})
    return removed

def setup(work,reference):
    work=Path(work);reference=Path(reference);m=json.loads((reference/'manifest.json').read_text())
    if m['storage_policy']['single_file_limit_bytes']!=SINGLE_FILE_LIMIT_BYTES or m['storage_policy']['maximum_work_bytes']!=WORK_LIMIT_BYTES:
        raise ValueError('Frozen storage policy does not match the native resource guards')
    shutil.copytree(reference/'config',work/'config')
    shutil.copytree(reference/'script',work/'script')
    for d in ('logs','result/report','result/pl','result/cts','result/no','result/to','result/to_drv','result/to_hold','result/rt','result/drc','result/timing','result/feature'):(work/d).mkdir(parents=True,exist_ok=True)
    for f in (work/'config').glob('*.json'):
        text=f.read_text(encoding='utf-8').replace('${RESULT_DIR}','result').replace('${CONFIG_DIR}','config').replace('$CONFIG_DIR','config')
        f.write_text(text,encoding='utf-8')
    p=work/'config/pl_default_config.json';pl=json.loads(p.read_text());pl['PL'].pop('MP',None)
    pl['PL'].update(num_threads=4,info_iter_num=10)
    pl['PL']['GP']['Density'].update(target_density=.6,bin_cnt_x=128,bin_cnt_y=128,is_adaptive_bin=0)
    write(p,pl)
    p=work/'config/cts_default_config.json';cfg=json.loads(p.read_text())
    write(p,{k:cfg[k] for k in ('skew_bound','max_buf_tran','max_sink_tran','max_cap','max_fanout','max_length','routing_layer','buffer_type')})
    mappings={'setup_slack_margin':'setup_target_slack','hold_slack_margin':'hold_target_slack','max_buffer_percent':'max_insert_instance_percent','max_utilization':'max_core_utilization','number_passes_allowed_decreasing_slack':'number_of_decreasing_slack_iter','rebuffer_max_fanout':'max_allowed_buffering_fanout','split_load_min_fanout':'min_divide_fanout'}
    for stage in ('drv','hold'):
        p=work/'config'/('to_default_config_'+stage+'.json');old=json.loads(p.read_text())
        cfg={k:v for k,v in old.items() if k in ('file_path','fix_fanout','optimize_drv','optimize_hold','optimize_setup','DRV_insert_buffers','setup_insert_buffers','hold_insert_buffers')}
        cfg.update({v:old[k] for k,v in mappings.items()})
        cfg.update(routing_tree='flute',optimize_endpoints_percent=1.,drv_optimize_iter_number=5,
                   specific_prefix={k:{'make_buffer':k+'_buffer_','make_net':k+'_net_'} for k in ('drv','hold','setup')})
        write(p,cfg)
    # Use the same established IO/PDN rule on both hosts; preserve source die/core.
    p=work/'script/iFP_script/module/pdn.tcl'
    p.write_text(p.read_text().replace('-width 1.60','-width 3.20').replace('-width 0.48','-width 0.46'))
    for p in (work/'script/iFP_script/module').glob('*.tcl'):
        p.write_text(p.read_text(encoding='utf-8').replace('$::env(TCL_SCRIPT_DIR)','script'),encoding='utf-8')
    write(work/'execution-policy.json',{'version':VERSION,'threads':4,'memory_gib':8,'seconds_per_native_stage':1800,'routing_seconds':m['budget'].get('routing_seconds',1800),
        'maximum_task_bytes':WORK_LIMIT_BYTES,'single_file_limit_bytes':SINGLE_FILE_LIMIT_BYTES,'reference_def_used':False,
        'expected_binary_sha256':BINARY_SHA256,'router_sha256':ROUTER_SHA256,'native_environment':ENV,'case':m['case_id'],
        'routing_policy':m['routing_policy'],
        'acceptance_mode':'flow_reproduction_separate_from_physical_quality'})

def script(stage,m):
    pre='''flow_init -config config/flow_config.json
db_init -config config/db_default_config.json
tech_lef_init -path $::env(INPUT_ROOT)/pdk/lef/sky130_fd_sc_hd.tlef
lef_init -path [list $::env(INPUT_ROOT)/pdk/lef/sky130_fd_sc_hd_merged.lef]
'''
    common=pre+'''db_init -lib_path [list $::env(INPUT_ROOT)/pdk/lib/sky130_fd_sc_hd__tt_025C_1v80.lib]
db_init -sdc_path $::env(INPUT_ROOT)/sdc/design.sdc
'''
    inp={'fanout':'floorplan','placement':'fanout','export_def':'placement','cts':'export_def','to_drv':'cts','to_hold':'to_drv','legalization':'to_hold','routing':'legalization','filler':'routing','drc':'filler','timing':'filler','routed_readback':'filler'}
    if stage=='import_netlist':body=pre+f'verilog_init -path $::env(INPUT_ROOT)/netlist/design.v -top {{{m["top"]}}}\n'
    elif stage=='floorplan':
        # iDB exports an import-only DEF with no DIEAREA. Re-import the frozen
        # netlist instead of feeding that diagnostic DEF back to the parser.
        body=common+f'verilog_init -path $::env(INPUT_ROOT)/netlist/design.v -top {{{m["top"]}}}\n'
        body+='init_floorplan -die_area {'+' '.join(map(str,m['die_area_microns']))+'} -core_area {'+' '.join(map(str,m['core_area_microns']))+'} -core_site unithd -io_site unithd -corner_site unithd\n'
        body+='''source script/iFP_script/module/create_tracks.tcl
auto_place_pins -layer met3 -width 800 -height 800
tapcell -tapcell sky130_fd_sc_hd__tapvpwrvgnd_1 -distance 14 -endcap sky130_fd_sc_hd__fill_1
source script/iFP_script/module/pdn.tcl
set_net -net_name clk -type CLOCK
'''
    else:
        body=common+'def_init -path result/'+inp[stage]+'.def\n'
        commands={'fanout':'run_no_fixfanout -config config/no_default_config_fixfanout.json',
          'placement':'run_placer -config config/pl_default_config.json',
          'export_def':'', 'cts':'run_cts -config config/cts_default_config.json -work_dir result/cts\ncts_report -path result/cts',
          'to_drv':'run_to_drv -config config/to_default_config_drv.json',
          'to_hold':'run_to_hold -config config/to_default_config_hold.json',
          'legalization':'run_incremental_flow -config config/pl_default_config.json',
          'routing':'init_rt -temp_directory_path result/rt -bottom_routing_layer met1 -top_routing_layer met5 -thread_number 4\nrun_rt\ndestroy_rt',
          'filler':'run_filler -config config/pl_default_config.json',
          'drc':'run_drc -config config/drc_default_config.json -path result/report/drc.rpt\nsave_drc -path result/drc/detail.drc',
          'timing':'run_sta -output result/timing','routed_readback':''}
        body+=commands[stage]+'\n'
    body+=f'def_save -path result/{stage}.def\nnetlist_save -path result/{stage}.v -exclude_cell_names {{}}\nreport_db -path result/report/{stage}.rpt\nputs "AES_STAGE_OK {stage}"\n'
    return 'if {[catch {\n'+body+'} message]} {puts stderr $message; exit 1}\nflow_exit\n'

def execute(stage,work,reference,runtime=None):
    work=Path(work).resolve();reference=Path(reference).resolve();m=json.loads((reference/'manifest.json').read_text())
    if stage not in STAGES:raise ValueError('Unknown stage')
    if stage in ('gds_export','routed_readback'):prune_duplicate_drc_exports(work)
    if stage=='validate':
        from .ieda_runtime import parse_placement_report
        placed=read_def(work/'result/placement.def');fanout=read_def(work/'result/fanout.def')
        value={'backend':parse_placement_report(work/'result/pl/report/summary_report.txt'),
               'independent':validate_placement(fanout,fanout,placed,[reference/p for p in m['cell_lefs']],m)}
        value['passed']=value['backend']['placement_checks_passed'] and value['independent']['passed']
        write(work/'validation.json',value);return value
    native_export=stage=='gds_export'
    router=Path(__file__).resolve().parents[1]/'environments/ieda-aes-router/iEDA'
    if stage=='routing' and sha(router)!=ROUTER_SHA256:raise ValueError('AES routing binary identity mismatch')
    seconds=m['budget'].get('routing_seconds',1800) if stage=='routing' else 1800
    if not 0<seconds<=21600:raise ValueError('Stage deadline outside reviewed medium-AES ceiling')
    export_bin=Path(__file__).resolve().parents[1]/'environments/ieda-export/bin/ieda-idb-export'
    export_manifest=json.loads((export_bin.parents[1]/'runtime-manifest.json').read_text()) if native_export else None
    if native_export and sha(export_bin)!=export_manifest['executable_sha256']:raise ValueError('Native exporter changed')
    (work/'stage.tcl').write_text('# Native public-iDB abstract GDS exporter\n' if native_export else script(stage,m),encoding='utf-8')
    env={**ENV,'OMP_NUM_THREADS':'4','OMP_THREAD_LIMIT':'4','OPENBLAS_NUM_THREADS':'1','RESULT_DIR':'result','CONFIG_DIR':'config','TCL_SCRIPT_DIR':'script'}
    if stage=='routing':
        iterations=m['routing_policy']['max_dr_iterations']
        if type(iterations) is not int or not 1<=iterations<=9:raise ValueError('Invalid frozen routing iteration policy')
        env.update(IEDA_RT_NATIVE_LAYER_GRAPH='1' if m['routing_graph']=='layered' else '0',
            IEDA_RT_MAX_ITERATIONS=str(iterations),IEDA_RT_NATIVE_LAYER_TRACKS='1',IEDA_RT_MAX_MEMORY_MB='8192')
    log=work/'logs'/(stage+'.log');resources=work/'logs'/(stage+'.resources.txt')
    if runtime:
        runtime=Path(runtime).resolve()
        if sha(runtime/'iEDA')!=BINARY_SHA256:raise ValueError('Runtime identity mismatch')
        env.update(INPUT_ROOT=str(reference),TCL_LIBRARY=str(runtime/'tcl8.6'))
        target=[str(export_bin),'result/filler.def','result/final.gds',str(reference/m['tech_lef']),*[str(reference/p) for p in m['cell_lefs']]] if native_export else [str(router if stage=='routing' else runtime/'iEDA'),'-script','stage.tcl']
        # --foreground prevents GNU timeout from creating a separate group,
        # so cancellation of this isolated session also kills the native child.
        command=['/usr/bin/time','-v','-o',str(resources),'timeout','--foreground','--kill-after=5',str(seconds),'prlimit','--as=8589934592','--core=0',f'--fsize={SINGLE_FILE_LIMIT_BYTES}','--',str(runtime/'ld-linux-x86-64.so.2'),'--library-path',str(runtime/'lib'),*target]
        affinity=sorted(os.sched_getaffinity(0))[:4]
        command=['taskset','-c',','.join(map(str,affinity))]+command
        popen_env=dict(os.environ,**env);container=None
    else:
        from . import ieda_runtime as rt
        container='aieda-aes-'+uuid.uuid4().hex[:12];env['INPUT_ROOT']='/reference'
        command=rt.docker()+['run','--rm','--pull=never','--name',container,'--network','none','--cpus','4','--memory','8g','--pids-limit','256','--ulimit','core=0','--ulimit',f'fsize={SINGLE_FILE_LIMIT_BYTES}',
            '--mount',f'type=bind,source={reference},target=/reference,readonly','--mount',f'type=bind,source={work},target=/work','--workdir','/work']
        for k,v in env.items():command+=['--env',k+'='+v]
        if native_export:
            command+=['--mount',f'type=bind,source={export_bin.parent},target=/native,readonly',export_manifest['image'],'timeout','--kill-after=5','1800','/native/ieda-idb-export','result/filler.def','result/final.gds','/reference/'+m['tech_lef'],*['/reference/'+p for p in m['cell_lefs']]]
        elif stage=='routing':
            command+=['--mount',f'type=bind,source={router.parent},target=/router,readonly',IMAGE,'timeout','--kill-after=5',str(seconds),'/opt/runtime/ld-linux-x86-64.so.2','--library-path','/opt/runtime/lib','/router/iEDA','-script','stage.tcl']
        else:command+=[IMAGE,'timeout','--kill-after=5',str(seconds),'iEDA','-script','stage.tcl']
        popen_env=os.environ
    if stage in ('to_drv','to_hold'):
        p=work/'config'/('to_default_config_'+stage[3:]+'.json');cfg=json.loads(p.read_text())
        cfg['file_path'].update(design_work_space='result/'+stage,sdc_file=env['INPUT_ROOT']+'/'+m['sdc'],
            lib_files=[env['INPUT_ROOT']+'/'+v for v in m['libs']],lef_files=[env['INPUT_ROOT']+'/'+v for v in [m['tech_lef'],*m['cell_lefs']]],
            def_file='result/'+('cts' if stage=='to_drv' else 'to_drv')+'.def',output_def='result/'+stage+'/ito_result.def',report_file='result/'+stage+'/report.txt',gds_file='result/'+stage+'/to.gds')
        write(p,cfg)
    start=time.monotonic();timedout=False;storage_exceeded=False
    with log.open('w',encoding='utf-8') as out:
        proc=subprocess.Popen(command,cwd=work,env=popen_env,stdout=out,stderr=subprocess.STDOUT,
            start_new_session=bool(runtime),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            while proc.poll() is None:
                time.sleep(2)
                size=sum(p.stat().st_size for p in work.rglob('*') if p.is_file())
                timedout=time.monotonic()-start>seconds+20;storage_exceeded=size>WORK_LIMIT_BYTES
                if timedout or storage_exceeded:break
        finally:
            # A parent deadline or interruption must not leave an EDA job behind.
            if proc.poll() is None:
                if runtime:os.killpg(proc.pid,signal.SIGKILL)
                else:rt.invoke(['kill',container])
                proc.wait()
        timedout=timedout or proc.returncode==124
    value={'stage':stage,'returncode':proc.returncode,'seconds':round(time.monotonic()-start,3),
        'log':str(log),'timed_out':timedout,'storage_limit_exceeded':storage_exceeded,
        'file_size_limit_exceeded':proc.returncode in (153,-25),'single_file_limit_bytes':SINGLE_FILE_LIMIT_BYTES,
        'maximum_task_bytes':WORK_LIMIT_BYTES,'script_sha256':sha(work/'stage.tcl'),
        'binary_sha256':sha(export_bin) if native_export else ROUTER_SHA256 if stage=='routing' else BINARY_SHA256,'deadline_seconds':seconds,'passed':False}
    artifact=work/'result'/('final.gds' if native_export else stage+'.def')
    if native_export:
        if proc.returncode==0 and artifact.exists() and 'IDB_NATIVE_EXPORT_OK' in log.read_text(errors='replace'):
            from .native_gds import validate
            check=validate(artifact,work/'result/filler.def',reference/m['tech_lef'],[reference/p for p in m['cell_lefs']])
            value.update(artifact=str(artifact),artifact_sha256=sha(artifact),validation=check,passed=check['passed'],native_exporter_sha256=sha(export_bin))
        write(work/(stage+'-evidence.json'),value);return value
    if proc.returncode==0 and artifact.exists() and f'AES_STAGE_OK {stage}' in log.read_text(errors='replace'):
        value.update(artifact=str(artifact),artifact_sha256=sha(artifact),passed=True)
        after=read_def(artifact)
        if stage=='import_netlist':value['import_check']=verify_netlist(reference/m['netlist'],artifact)
        if stage=='floorplan':
            before=read_def(work/'result/import_netlist.def');errors=[]
            if before['nets']!=after['nets']:errors.append('logical_net_change')
            for n,c in before['components'].items():
                if after['components'].get(n,{}).get('master')!=c['master']:errors.append('original_instance_change:'+n)
            if any(c['master'] not in m['allowed_physical_insertions'] for n,c in after['components'].items() if n not in before['components']):errors.append('unapproved_physical_insertion')
            if set(after['pins'])-set(before['pins'])!=set(m['allowed_power_pins']) or set(before['pins'])-set(after['pins']):errors.append('port_change')
            value['floorplan_preservation']={'passed':not errors,'errors':errors}
        previous={'fanout':'floorplan','placement':'fanout','cts':'export_def','to_drv':'cts','to_hold':'to_drv','legalization':'to_hold','routing':'legalization','filler':'routing','drc':'filler','timing':'filler','routed_readback':'filler'}
        if stage in previous:
            from .aes_transforms import check
            value['transformation']=check(read_def(work/'result'/(previous[stage]+'.def')),after,stage)
        if stage=='routing':
            from .aes_reproduction import routing_observation
            value['routing_gate']=routing_observation(json.loads((work/'result/rt/violation_reporter/route_summary.json').read_text()))
            native_log=(work/'result/rt/rt.log').read_text(errors='replace')
            begins=re.findall(r'DetailedRouter[^\n]*Begin iteration (\d+)/(\d+)',native_log)
            ends=re.findall(r'DetailedRouter[^\n]*End Iteration (\d+)/(\d+)',native_log)
            value['routing_profile']={'passed':bool(begins) and begins==ends and all(int(n)==iterations for _,n in begins),
                'max_dr_iterations':iterations,'observed_iterations':begins,'native_layer_tracks':True,
                'native_graph':m['routing_graph'],'best_effort':False,'internal_memory_limit_mb':8192}
        if stage=='drc':
            from .aes_reproduction import drc_observation
            from .drc_counts import runtime_identity
            value['drc_gate']=drc_observation(json.loads((work/'result/report/drc_summary.json').read_text()),
                report_dir=work/'result/report',producer_sha256=runtime_identity(rt))
        if stage in ('to_drv','to_hold'):
            report=json.loads((work/'result/to/ito_pass_report.json').read_text())
            passes=[p for p in report.get('passes',[]) if p.get('phase')==stage[3:]]
            value['native_optimization']={'passed':len(passes)==1 and passes[0].get('status')=='OK' and not passes[0].get('rolled_back'),'passes':passes,'signoff_clean':False}
        if stage=='timing':
            report=work/'result/timing'/(m['top']+'.rpt')
            value['timing']={'passed':report.is_file() and 'core_clock' in report.read_text(),'report':str(report),'signoff_clean':False,'parasitics':'No SPEF; cell-delay diagnostic only'}
        if stage in ('export_def','routed_readback'):
            source=work/'result'/('placement.def' if stage=='export_def' else 'filler.def')
            value['roundtrip']={'passed':read_def(source)==after and route_records(source)==route_records(artifact)}
        if stage in ('legalization','filler','drc','routed_readback'):
            value['geometry']=validate_placement(after,after,after,[reference/p for p in m['cell_lefs']],m)
        if any(isinstance(v,dict) and v.get('passed') is False for v in value.values()):value['passed']=False
    if stage=='drc' and value.get('passed') is True:prune_duplicate_drc_exports(work)
    write(work/(stage+'-evidence.json'),value)
    shutil.copyfile(work/'stage.tcl',work/(stage+'.tcl'))
    return value
