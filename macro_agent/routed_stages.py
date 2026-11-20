"""Experimental registered HD routed-DEF profile in the SAME main-task core.

Does not claim complete server flow parity, native GDS or signoff.
"""
from pathlib import Path
from types import SimpleNamespace
from functools import partial
import copy
import json
import subprocess
import time
import uuid
from . import ieda_stages as placement
from .portable_ieda import ENV
from .def_validation import read_def,validate_placement
from .backend_checks import routing_gate,drc_gate,transformation_check,route_records,io_policy_check,pdn_policy_check

VERSION=placement.BACKEND_VERSION+'-routed-v3-pdn'
STAGES=placement.STAGES+['cts','legalization','routing','filler','drc','routed_readback']
BUDGET={'executions':16,'model_calls':32,'wall_seconds':3600,'cpu_threads':4,'memory_gb':8,'container_seconds':120,'host_seconds':140}
IO_RULE={'method':'auto_place_pins','layer':'met3','allowed_layers':['met3','met4'],'width_dbu':800,'height_dbu':800,
         'reason':'reviewed native direction-paired IO policy; avoid met5 IO/PDN conflicts observed in routed-v1'}
PDN_RULE={'widths_dbu':{'met1':460,'met4':3200,'met5':3200},
          'reason':'native via-array landing-pad commissioning; electrical/IR adequacy not established',
          'evidence':'runs/stage1-pdn-rail046-20261106/verification.json'}

def setup(work,base):
    base.setup(work)
    p=Path(work)/'script/iFP_script/run_iFP.tcl';text=p.read_text()
    old='auto_place_pins -layer met5 -width 2000 -height 2000'
    if text.count(old)!=1:raise ValueError('Unsupported case IO script; do not silently override')
    p.write_text(text.replace(old,'auto_place_pins -layer met3 -width 800 -height 800'))
    p=Path(work)/'script/iFP_script/module/pdn.tcl';text=p.read_text()
    if text.count('-width 1.60')!=2 or text.count('-width 0.48')!=1:
        raise ValueError('Unsupported case PDN script; do not silently override')
    p.write_text(text.replace('-width 1.60','-width 3.20').replace('-width 0.48','-width 0.46'))

def for_case(case_id,reference_root=None):
    if case_id!='ibench_gcd_legacy':raise ValueError('routed_def requires registered HD GCD')
    base=placement.for_case(case_id,reference_root)
    def manifest():
        m=copy.deepcopy(base.manifest());m['budget']=dict(BUDGET);m['io_rule']=copy.deepcopy(IO_RULE);m['pdn_rule']=copy.deepcopy(PDN_RULE);return m
    return SimpleNamespace(rt=base.rt,BACKEND_VERSION=VERSION,STAGES=STAGES,manifest=manifest,
        input_files=lambda:base.input_files()+[Path(__file__),Path(__file__).with_name('backend_checks.py'),Path(__file__).with_name('netlist_check.py')],
        setup=partial(setup,base=base),execute=partial(execute,base=base),package=package)

def execute(stage,work,base):
    work=Path(work)
    if stage in placement.STAGES:
        value=base.execute(stage,work)
        if stage=='import_netlist':
            from .netlist_check import verify_import
            value['independent_netlist']=verify_import(base.input_files()[0],Path(value['artifact']))
            (work/'backend-checks.json').write_text(json.dumps(value,indent=2))
            if not value['independent_netlist']['passed']:raise ValueError('Independent netlist/import mismatch')
        if stage=='floorplan':
            value['io_policy']=io_policy_check(read_def(Path(value['artifact'])),IO_RULE,base.manifest().get('logical_only_pdn_pins',[]))
            value['pdn_policy']=pdn_policy_check(read_def(Path(value['artifact'])),PDN_RULE)
            (work/'backend-checks.json').write_text(json.dumps(value,indent=2))
            if not all(value[k]['passed'] for k in ('io_policy','pdn_policy')):raise ValueError('Frozen IO/PDN policy mismatch')
        return value
    m=base.manifest();b=BUDGET
    reference=base.input_files()[0]
    # Locate the reference root from the registered manifest-relative netlist.
    for _ in Path(m['netlist']).parts:reference=reference.parent
    for name in ('cts','rt','drc'):(work/'result'/name).mkdir(exist_ok=True)
    cts=work/'config/cts_default_config.json';cfg=json.loads(cts.read_text())
    keys=('skew_bound','max_buf_tran','max_sink_tran','max_cap','max_fanout','max_length','routing_layer','buffer_type')
    cts.write_text(json.dumps({k:cfg[k] for k in keys},indent=2))
    commands={
        'cts':('readback.def','run_cts -config /work/config/cts_default_config.json -work_dir /work/result/cts\ncts_report -path /work/result/cts'),
        'legalization':('cts.def','run_incremental_flow -config /work/config/pl_default_config.json'),
        'routing':('legalization.def','init_rt -temp_directory_path /work/result/rt -bottom_routing_layer met1 -top_routing_layer met5 -thread_number 4\nrun_rt\ndestroy_rt'),
        'filler':('routing.def','run_filler -config /work/config/pl_default_config.json'),
        'drc':('filler.def','run_drc -config /work/config/drc_default_config.json -path /work/result/report/drc.rpt\nsave_drc -path /work/result/drc/detail.drc'),
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
    script='if {[catch {\n'+script+'} message]} {puts stderr $message; exit 1}\nflow_exit\n'
    (work/'backend-stage.tcl').write_text(script)
    name='aieda-routed-'+uuid.uuid4().hex[:12]
    args=['run','--rm','--pull=never','--name',name,'--network','none','--cpus','4','--memory','8g','--pids-limit','256',
        '--mount',f'type=bind,source={reference},target=/reference,readonly','--mount',f'type=bind,source={work},target=/work','--workdir','/work']
    for k,v in {**ENV,'OMP_NUM_THREADS':'4','RESULT_DIR':'/work/result','CONFIG_DIR':'/work/config'}.items():args+=['--env',k+'='+v]
    args += [base.rt.IMAGE,'timeout','--kill-after=5','120','iEDA','-script','/work/backend-stage.tcl']
    started=time.monotonic();log=work/'logs'/f'{stage}.log'
    with log.open('w',encoding='utf-8') as out:
        try:p=subprocess.run(base.rt.docker()+args,stdout=out,stderr=subprocess.STDOUT,timeout=b['host_seconds'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except subprocess.TimeoutExpired:
            try:base.rt.invoke(['kill',name])
            except RuntimeError:pass
            raise RuntimeError('BACKEND_TIMEOUT: bounded container stopped') from None
    if p.returncode or f'STAGE_OK {stage}' not in log.read_text(errors='replace'):raise ValueError('Backend failed; see '+str(log))
    before=read_def(work/'result'/inp);after=read_def(output)
    check=transformation_check(before,after,stage)
    result={'artifact':str(output),'log':str(log),'seconds':round(time.monotonic()-started,3),
        'instances':len(after['components']),'nets':len(after['nets']),'units':after['units'],'transformation':check}
    if stage=='routing':result['routing_gate']=routing_gate(json.loads((work/'result/rt/violation_reporter/route_summary.json').read_text()))
    if stage=='drc':
        from .drc_counts import runtime_identity
        result['drc_gate']=drc_gate(json.loads((work/'result/report/drc_summary.json').read_text()),
            report_dir=work/'result/report',producer_sha256=runtime_identity(base.rt))
    if stage in ('legalization','filler','drc','routed_readback'):
        # Connectivity checked independently above; this checks the new geometry and pins.
        result['geometry']=validate_placement(after,after,after,[reference/p for p in m['cell_lefs']],policy=m)
    if stage=='routed_readback':
        result['readback_equal']=before==after and route_records(work/'result'/inp)==route_records(output)
        result['readback_coverage']=['DEF design and placement semantics','full per-net route tokens','physical sections']
    (work/'backend-checks.json').write_text(json.dumps(result,indent=2))
    if any(not result[k]['passed'] for k in ('transformation','routing_gate','drc_gate','geometry') if k in result) or result.get('readback_equal') is False:
        raise ValueError('BACKEND_ACCEPTANCE_FAILED: '+json.dumps({k:v.get('errors',[]) for k,v in result.items() if isinstance(v,dict) and not v.get('passed',True)})+'; see '+str(work/'backend-checks.json'))
    return result

def package(state,folder,backend):
    # Only reachable after quality gates. Placement metrics remain explicitly stage-labelled.
    from .task_artifacts import package as placement_package,write,write_report,ref
    work=Path(state['accepted_work']);shadow=copy.deepcopy(state)
    shadow['results']['export_def']=state['results']['routed_readback']
    shadow['results']['validate']['independent']=state['results']['routed_readback']['geometry']
    outputs=placement_package(shadow,folder,backend,final_source=work/'result/routed_readback.def')
    report=Path(folder)/'report.html'
    acceptance=json.loads((Path(folder)/'acceptance.json').read_text())
    acceptance.update(scope='registered routed DEF subset; not full server flow or signoff',
        routing=state['results']['routing']['routing_gate'],drc=state['results']['drc']['drc_gate'],
        independent_netlist=state['results']['import_netlist']['independent_netlist'],
        transformations={k:state['results'][k]['transformation'] for k in ('cts','legalization','routing','filler','drc','routed_readback')},
        full_backend_certified=False,
        missing_full_backend=['fanout and DRV/hold optimization acceptance','native GDS','macro case','RC/STA and signoff'])
    acceptance['checks'].update(
        A1='pass for registered flat HD input: independent netlist/import comparison; not general Verilog equivalence',
        A2='pass for experimental routed-DEF subset only; full backend flow acceptance pending',
        A3='original endpoints verified through approved CTS buffer-tree contraction; other stages preserve logical connectivity',
        A8='fresh iEDA readback: parsed DEF semantics and full per-net route tokens agree')
    write(Path(folder)/'acceptance.json',acceptance)
    write_report(folder)
    report.write_text(report.read_text(encoding='utf-8').replace('iEDA netlist → placement DEF','iEDA netlist → routed DEF').replace('当前案例输出完成；','当前登记布线 DEF 子流程输出完成；'),encoding='utf-8')
    outputs['report']=ref(report);outputs['acceptance']=ref(Path(folder)/'acceptance.json')
    return outputs
