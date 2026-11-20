"""Candidate complete registered HD flow. Admission requires native export qualification.

This is an execution profile of main_task, not another Agent loop. The new goal
keeps historical placement and routed-only contracts unchanged.
"""
import copy,json,shutil,subprocess,time,uuid
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from . import ieda_stages as placement,routed_stages as routed
from .portable_ieda import ENV
from .def_validation import read_def,validate_placement
from .backend_checks import transformation_check,routing_gate,drc_gate,route_records

VERSION=placement.BACKEND_VERSION+'-full-v1'
STAGES=['import_netlist','floorplan','fanout','placement','validate','export_def','cts','to_drv','to_hold',
        'legalization','routing','filler','drc','timing','gds_export','routed_readback']
BUDGET={'executions':22,'model_calls':40,'wall_seconds':3600,'cpu_threads':4,'memory_gb':8,'container_seconds':120,'host_seconds':140}

def configure_to(work):
    mapping={'setup_slack_margin':'setup_target_slack','hold_slack_margin':'hold_target_slack',
       'max_buffer_percent':'max_insert_instance_percent','max_utilization':'max_core_utilization',
       'number_passes_allowed_decreasing_slack':'number_of_decreasing_slack_iter',
       'rebuffer_max_fanout':'max_allowed_buffering_fanout','split_load_min_fanout':'min_divide_fanout'}
    for stage,inp in [('drv','cts.def'),('hold','to_drv.def')]:
        p=work/'config'/f'to_default_config_{stage}.json';old=json.loads(p.read_text())
        cfg={k:v for k,v in old.items() if k in ('file_path','fix_fanout','optimize_drv','optimize_hold','optimize_setup','DRV_insert_buffers','setup_insert_buffers','hold_insert_buffers')}
        cfg.update({new:old[key] for key,new in mapping.items()})
        cfg.update(routing_tree='flute',optimize_endpoints_percent=1.0,drv_optimize_iter_number=5,
           specific_prefix={k:{'make_buffer':k+'_buffer_','make_net':k+'_net_'} for k in ('drv','hold','setup')})
        cfg['file_path'].update(design_work_space='/work/result/to_'+stage,sdc_file='/reference/sdc/gcd.sdc',
          lib_files=['/reference/pdk/lib/sky130_fd_sc_hd__tt_025C_1v80.lib'],
          lef_files=['/reference/pdk/lef/sky130_fd_sc_hd.tlef','/reference/pdk/lef/sky130_fd_sc_hd_merged.lef'],
          def_file='/work/result/'+inp,output_def='/work/result/to_'+stage+'/ito_result.def',
          report_file='/work/result/to_'+stage+'/report.txt',gds_file='/work/result/to_'+stage+'/to.gds')
        p.write_text(json.dumps(cfg,indent=2))

def setup(work,base):
    base.setup(work);configure_to(Path(work))

def for_case(case_id,reference_root=None):
    if case_id=='swerv_nangate45':
        from .swerv_backend import for_case as swerv_case
        return swerv_case(case_id,reference_root)
    from .aes_backend import CASES,for_case as aes_case
    if case_id in CASES:return aes_case(case_id,reference_root)
    if case_id!='ibench_gcd_legacy':raise ValueError('full_backend requires the registered HD GCD input package')
    base=routed.for_case(case_id,reference_root)
    def manifest():
        m=copy.deepcopy(base.manifest());m['budget']=dict(BUDGET)
        m['full_backend_policy']={'logical_optimizations':'Only the CTS tree transformation is admitted; fanout/DRV/hold must preserve all design semantics on this qualified case',
           'timing':'Cell-delay diagnostic without SPEF; no timing closure claim',
           'optional_unavailable':{'rcx':'No validated technology RC extraction model in the registered bundle',
               'power':'No qualified activity/parasitic scenario','ir':'No qualified PG electrical model/current scenario'},
           'gds':'Local public-iDB native export patch; LEF abstract geometry, not transistor library GDS or foundry mapping'}
        return m
    from .native_gds import input_files as export_inputs
    return SimpleNamespace(rt=base.rt,BACKEND_VERSION=VERSION,STAGES=STAGES,manifest=manifest,
       input_files=lambda:base.input_files()+[Path(__file__)]+export_inputs(),setup=partial(setup,base=base),
       execute=partial(execute,base=base),package=package)

def timing_optimization_gate(data,phase):
    passes=[p for p in data.get('passes',[]) if p.get('phase')==phase]
    errors=[]
    if len(passes)!=1:return {'passed':False,'errors':['missing_or_ambiguous_native_pass']}
    p=passes[0];q=p.get('timing_quality_after',{})
    if p.get('status')!='OK' or p.get('rolled_back'):errors.append('native_pass_not_accepted')
    if not p.get('canonical_hash_before') or p.get('canonical_hash_before')!=p.get('canonical_hash_after'):errors.append('unaudited_logical_optimization')
    if not q.get('available'):errors.append('missing_native_timing_observation')
    if phase=='drv':
        for k in ('cap','slew','fanout'):
            if q.get('buckets',{}).get(k,{}).get('violations')!=0:errors.append('drv_violation_or_unknown:'+k)
    elif phase=='hold' and q.get('wns_tns',{}).get('hold_wns_ns',-1)<0:errors.append('hold_violation')
    return {'passed':not errors,'errors':errors,'native_pass':p,
       'measurement_scope':'Native iTO updated estimated RC; initialization and post-update numbers use different RC states. No improvement inferred from their delta.',
       'signoff_clean':False}

def execute(stage,work,base):
    work=Path(work)
    if stage in placement.STAGES:
        if stage=='placement':
            # Native fanout output becomes the placement input; the old floorplan
            # stays in the prior immutable attempt and this backup.
            shutil.copyfile(work/'result/iFP_result.def',work/'result/floorplan_original.def')
            shutil.copyfile(work/'result/fanout.def',work/'result/iFP_result.def')
        return base.execute(stage,work)
    if stage=='gds_export':
        from .native_gds import export
        return export(work,base)
    reference=base.input_files()[0]
    for _ in Path(base.manifest()['netlist']).parts:reference=reference.parent
    for d in ('cts','rt','drc','no','to','to_drv','to_hold','timing'):(work/'result'/d).mkdir(exist_ok=True)
    cts=work/'config/cts_default_config.json';cfg=json.loads(cts.read_text())
    keys=('skew_bound','max_buf_tran','max_sink_tran','max_cap','max_fanout','max_length','routing_layer','buffer_type')
    cts.write_text(json.dumps({k:cfg[k] for k in keys},indent=2))
    commands={
       'fanout':('iFP_result.def','run_no_fixfanout -config /work/config/no_default_config_fixfanout.json'),
       'cts':('readback.def','run_cts -config /work/config/cts_default_config.json -work_dir /work/result/cts\ncts_report -path /work/result/cts'),
       'to_drv':('cts.def','run_to_drv -config /work/config/to_default_config_drv.json'),
       'to_hold':('to_drv.def','run_to_hold -config /work/config/to_default_config_hold.json'),
       'legalization':('to_hold.def','run_incremental_flow -config /work/config/pl_default_config.json'),
       'routing':('legalization.def','init_rt -temp_directory_path /work/result/rt -bottom_routing_layer met1 -top_routing_layer met5 -thread_number 4\nrun_rt\ndestroy_rt'),
       'filler':('routing.def','run_filler -config /work/config/pl_default_config.json'),
       'drc':('filler.def','run_drc -config /work/config/drc_default_config.json -path /work/result/report/drc.rpt\nsave_drc -path /work/result/drc/detail.drc'),
       'timing':('filler.def','run_sta -output /work/result/timing/'),
       'routed_readback':('filler.def','')}
    inp,cmd=commands[stage]
    script='''flow_init -config /work/config/flow_config.json
db_init -config /work/config/db_default_config.json
source /work/script/DB_script/db_path_setting.tcl
source /work/script/DB_script/db_init_lef.tcl
db_init -lib_path $LIB_PATH
db_init -sdc_path $SDC_PATH
'''+f'def_init -path /work/result/{inp}\n'+cmd+'\n'
    output=work/'result'/f'{stage}.def'
    script+=f'def_save -path /work/result/{stage}.def\nnetlist_save -path /work/result/{stage}.v -exclude_cell_names {{}}\nputs "STAGE_OK {stage}"\n'
    (work/'backend-stage.tcl').write_text('if {[catch {\n'+script+'} message]} {puts stderr $message; exit 1}\nflow_exit\n')
    name='aieda-full-'+uuid.uuid4().hex[:12]
    args=base.rt.docker()+['run','--rm','--pull=never','--name',name,'--network','none','--cpus','4','--memory','8g','--pids-limit','256','--ulimit','core=0',
       '--mount',f'type=bind,source={reference},target=/reference,readonly','--mount',f'type=bind,source={work},target=/work','--workdir','/work']
    for k,v in {**ENV,'OMP_NUM_THREADS':'4','OMP_THREAD_LIMIT':'4','RESULT_DIR':'/work/result','CONFIG_DIR':'/work/config'}.items():args+=['--env',k+'='+v]
    args += [base.rt.IMAGE,'timeout','--kill-after=5','120','iEDA','-script','/work/backend-stage.tcl']
    started=time.monotonic();log=work/'logs'/f'{stage}.log'
    with log.open('w',encoding='utf-8') as out:
        try:code=subprocess.run(args,stdout=out,stderr=subprocess.STDOUT,timeout=140,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode
        except subprocess.TimeoutExpired:
            try:base.rt.invoke(['kill',name])
            except RuntimeError:pass
            raise RuntimeError('BACKEND_TIMEOUT: bounded full-flow stage stopped') from None
    if code or f'STAGE_OK {stage}' not in log.read_text(errors='replace'):raise ValueError('Native stage failed; see '+str(log))
    before=read_def(work/'result'/inp);after=read_def(output)
    result={'artifact':str(output),'log':str(log),'seconds':round(time.monotonic()-started,3),
       'input_artifact':str(work/'result'/inp),'transformation':transformation_check(before,after,stage)}
    if stage in ('fanout','to_drv','to_hold','timing'):
        result['unchanged_design']={'passed':before==after,'errors':[] if before==after else ['unexpected_design_semantic_change']}
    if stage in ('to_drv','to_hold'):
        result['optimization']=timing_optimization_gate(json.loads((work/'result/to/ito_pass_report.json').read_text()),stage[3:])
    if stage=='routing':result['routing_gate']=routing_gate(json.loads((work/'result/rt/violation_reporter/route_summary.json').read_text()))
    if stage=='drc':
        from .drc_counts import runtime_identity
        result['drc_gate']=drc_gate(json.loads((work/'result/report/drc_summary.json').read_text()),
            report_dir=work/'result/report',producer_sha256=runtime_identity(base.rt))
    if stage in ('legalization','filler','drc','routed_readback'):
        result['geometry']=validate_placement(after,after,after,[reference/p for p in base.manifest()['cell_lefs']],policy=base.manifest())
    if stage=='timing':
        report=work/'result/timing/gcd.rpt'
        result['timing']={'passed':report.is_file() and 'core_clock' in report.read_text(),'report':str(report),
           'parasitics':'none; no SPEF loaded','scope':'cell-delay diagnostic only','signoff_clean':False,
           'routed_timing':None,'power':None,'ir_drop':None}
    if stage=='routed_readback':
        result['readback_equal']=before==after and route_records(work/'result'/inp)==route_records(output)
        result['readback_coverage']=['DEF logical and physical semantics','full per-net route records']
    (work/'backend-checks.json').write_text(json.dumps(result,indent=2))
    if any(isinstance(v,dict) and v.get('passed') is False for v in result.values()) or result.get('readback_equal') is False:
        raise ValueError('FULL_BACKEND_GATE_FAILED: '+str(work/'backend-checks.json'))
    return result

def package(state,folder,backend):
    from .task_artifacts import package as base_package,write,write_report,ref
    folder=Path(folder);work=Path(state['accepted_work']);shadow=copy.deepcopy(state)
    shadow['results']['export_def']=state['results']['routed_readback']
    shadow['results']['validate']['independent']=state['results']['routed_readback']['geometry']
    outputs=base_package(shadow,folder,backend,final_source=work/'result/routed_readback.def')
    for name,source in [('final.gds','final.gds'),('final.v','routed_readback.v')]:shutil.copyfile(work/'result'/source,folder/name)
    outputs.update(final_gds=ref(folder/'final.gds'),final_netlist=ref(folder/'final.v'))
    acceptance=json.loads((folder/'acceptance.json').read_text())
    acceptance.update(scope='Registered HD GCD iEDA backend workflow; LEF abstract GDS; no signoff',
       full_backend_workflow_completed=True,signoff_clean=False,
       routing=state['results']['routing']['routing_gate'],drc=state['results']['drc']['drc_gate'],
       native_gds=state['results']['gds_export']['validation'],timing=state['results']['timing']['timing'],
       optional_unavailable=backend.manifest()['full_backend_policy']['optional_unavailable'],
       transformations={s:state['results'][s]['transformation'] for s in STAGES if 'transformation' in state['results'][s]})
    acceptance['checks'].update(A1='registered flat netlist independently checked',A2='all 16 registered backend stages executed; Maker=0',
       A3='CTS buffer contraction; other stages preserve logical semantics; iTO admitted only on unchanged design',
       A8='fresh iEDA DEF readback and independently read native iDB abstract GDS')
    write(folder/'acceptance.json',acceptance);write_report(folder)
    report=folder/'report.html';report.write_text(report.read_text(encoding='utf-8').replace('iEDA netlist → placement DEF','iEDA netlist → routed DEF / abstract GDS'),encoding='utf-8')
    outputs['acceptance']=ref(folder/'acceptance.json');outputs['report']=ref(report);return outputs
