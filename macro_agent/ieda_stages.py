"""Deterministic iEDA stages shared by desktop and future workbench callers."""
from pathlib import Path
import json
import subprocess
import time
import uuid
import shutil
from functools import partial
from types import SimpleNamespace
import sys

from . import ieda_runtime as rt
from .portable_ieda import ENV, adapt_placement_config
from .def_validation import read_def, validate_placement

BACKEND_VERSION = 'ieda-manifest-stages-v3-server-d9ae2896'
STAGES = ['import_netlist', 'floorplan', 'placement', 'validate', 'export_def']


REGISTERED_CASES = {
    'sky130_gcd': (rt.REFERENCE, rt.ROOT/'cases/sky130_gcd/manifest.json'),
    'ibench_gcd_legacy': (rt.ROOT/'cases/ibench/gcd_legacy', rt.ROOT/'cases/ibench/gcd_legacy/manifest.json'),
    'sky130_sram_pair': (rt.ROOT/'cases/sky130_sram_pair', rt.ROOT/'cases/sky130_sram_pair/manifest.json'),
}
for _aes_name in ('aes_sky130_t','aes_legacy','aes_core_sky130_t','swerv_nangate45','bp_be','bp_fe','bp_multi','s35932_nangate45_t'):
    REGISTERED_CASES[_aes_name]=(rt.ROOT/'cases/ibench'/_aes_name,rt.ROOT/'cases/ibench'/_aes_name/'manifest.json')


def for_case(case_id, reference_root=None):
    if case_id not in REGISTERED_CASES:
        raise ValueError('unsupported_case: registered iEDA input package required')
    if case_id == 'sky130_gcd' and reference_root is None:
        return sys.modules[__name__]
    result=SimpleNamespace(
        rt=rt, BACKEND_VERSION=BACKEND_VERSION, STAGES=STAGES,
        manifest=partial(manifest, case_id=case_id, reference_root=reference_root),
        input_files=partial(input_files, case_id=case_id, reference_root=reference_root),
        setup=partial(setup, case_id=case_id, reference_root=reference_root),
        execute=partial(execute, case_id=case_id, reference_root=reference_root),
    )
    if case_id=='sky130_sram_pair':
        from .macro_stages import decorate
        return decorate(result,reference_root or REGISTERED_CASES[case_id][0])
    return result


def manifest(case_id='sky130_gcd', reference_root=None):
    manifest_path = Path(reference_root)/'manifest.json' if reference_root else REGISTERED_CASES[case_id][1]
    value=json.loads(manifest_path.read_text(encoding='utf-8'))
    if value['case_id'] != case_id or value['backend']!='iEDA' or value['hidden_reference_coordinates']:
        raise ValueError('Unsupported case input policy')
    return value


def input_files(case_id='sky130_gcd', reference_root=None):
    reference, manifest_path = REGISTERED_CASES[case_id]
    if reference_root:
        reference = Path(reference_root)
        manifest_path = reference/'manifest.json'
    m=manifest(case_id, reference_root)
    names=[m['netlist'],m['tech_lef'],*m['cell_lefs'],*m['libs'],m['sdc']]
    return [reference/n for n in names] + sorted((reference/m['scripts_dir']).rglob('*.tcl')) + sorted((reference/m['config_dir']).glob('*.json')) + [manifest_path] + [reference/p for p in m.get('provenance', [])]


def setup(work, case_id='sky130_gcd', reference_root=None):
    reference = Path(reference_root) if reference_root else REGISTERED_CASES[case_id][0]
    m=manifest(case_id, reference_root)
    shutil.copytree(reference/m['scripts_dir'],work/'script')
    shutil.copytree(reference/m['config_dir'],work/'config')
    adapt_placement_config(work/'config/pl_default_config.json')
    for folder in ['result/report','result/pl','result/feature','result/sta','logs']:
        (work/folder).mkdir(parents=True,exist_ok=True)
    def tcl_paths(items):return '[list '+' '.join('{/reference/'+p+'}' for p in items)+']'
    (work/'script/DB_script/db_path_setting.tcl').write_text('\n'.join([
        'set TECH_LEF_PATH '+tcl_paths([m['tech_lef']]),'set LEF_PATH '+tcl_paths(m['cell_lefs']),
        'set LIB_PATH '+tcl_paths(m['libs']),'set SDC_PATH '+tcl_paths([m['sdc']])])+'\n',encoding='utf-8')
    placement=work/'script/iPL_script/run_iPL.tcl'
    placement.write_text(placement.read_text(encoding='utf-8').replace('iTO_fix_fanout_result.def','iFP_result.def'),encoding='utf-8')
    base = '''flow_init -config $::env(CONFIG_DIR)/flow_config.json
db_init -config $::env(CONFIG_DIR)/db_default_config.json
source $::env(TCL_SCRIPT_DIR)/DB_script/db_path_setting.tcl
source $::env(TCL_SCRIPT_DIR)/DB_script/db_init_lef.tcl
'''
    (work/'import.tcl').write_text(base + '''verilog_init -path $::env(NETLIST_FILE) -top $::env(DESIGN_TOP)
def_save -path /work/result/import.def
flow_exit
''', encoding='utf-8')
    (work/'readback.tcl').write_text(base + '''def_init -path /work/result/iPL_result.def
def_save -path /work/result/readback.def
flow_exit
''', encoding='utf-8')


def execute(stage, work, case_id='sky130_gcd', reference_root=None):
    work = Path(work)
    reference = Path(reference_root) if reference_root else REGISTERED_CASES[case_id][0]
    m=manifest(case_id, reference_root);budget=m['budget']
    if stage == 'validate':
        report = rt.parse_placement_report(work/'result/pl/report/summary_report.txt')
        independent = validate_placement(read_def(work/'result/import.def'), read_def(work/'result/iFP_result.def'),
                                         read_def(work/'result/iPL_result.def'), [reference/p for p in m['cell_lefs']], policy=m)
        value = {'backend': report, 'independent': independent}
        (work/'validation.json').write_text(json.dumps(value,indent=2),encoding='utf-8')
        if not report['placement_checks_passed'] or not independent['passed']:
            raise ValueError('Placement validation failed: ' + json.dumps(independent['errors']))
        return value
    scripts = {'import_netlist':'/work/import.tcl','floorplan':'/work/script/iFP_script/run_iFP.tcl',
               'placement':'/work/script/iPL_script/run_iPL.tcl','export_def':'/work/readback.tcl'}
    env = {'CONFIG_DIR':'/work/config','FOUNDRY_DIR':'/reference/'+m['foundry_dir'],
           'RESULT_DIR':'/work/result','TCL_SCRIPT_DIR':'/work/script','DESIGN_TOP':m['top'],
           'NETLIST_FILE':'/reference/'+m['netlist'],'SDC_FILE':'/reference/'+m['sdc'],
           'DIE_AREA':' '.join(map(str,m['die_area_microns'])),'CORE_AREA':' '.join(map(str,m['core_area_microns'])),
           'OMP_NUM_THREADS':str(budget['cpu_threads']), **ENV}
    name='aieda-stage-'+uuid.uuid4().hex[:12]
    args=['run','--pull=never','--rm','--name',name,'--network','none','--cpus',str(budget['cpu_threads']),'--memory',str(budget['memory_gb'])+'g','--pids-limit','256',
          '--mount',f'type=bind,source={reference},target=/reference,readonly',
          '--mount',f'type=bind,source={work},target=/work','--workdir','/work']
    for key,value in env.items():
        args += ['--env',key+'='+value]
    args += [rt.IMAGE,'/usr/bin/timeout','--kill-after=5',str(budget['container_seconds']),'iEDA','-script',scripts[stage]]
    log = work/'logs'/f'{stage}.log'
    started=time.monotonic()
    with log.open('w',encoding='utf-8') as stream:
        try:
            process=subprocess.run(rt.docker()+args,stdout=stream,stderr=subprocess.STDOUT,timeout=budget['host_seconds'],
                                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except subprocess.TimeoutExpired:
            try: rt.invoke(['kill',name],timeout=10)
            except RuntimeError: pass  # Container may have exited before the kill request.
            raise RuntimeError('Stage deadline exceeded; container stopped') from None
    if process.returncode:
        raise RuntimeError(f'iEDA {stage} exited {process.returncode}; see {log}')
    output=work/'result'/ {'import_netlist':'import.def','floorplan':'iFP_result.def',
                          'placement':'iPL_result.def','export_def':'readback.def'}[stage]
    design=read_def(output)
    value={'artifact':str(output),'log':str(log),'seconds':round(time.monotonic()-started,3),
           'instances':len(design['components']),'nets':len(design['nets']),'units':design['units']}
    if stage=='export_def':
        if read_def(work/'result/iPL_result.def') != design:
            raise ValueError('Fresh iEDA database readback differs from placed DEF')
        value['readback_equal']=True
        value['readback_coverage']=['design','units','die','components_and_placement','normal_nets','pins','rows','tracks','specialnets','vias','blockages','regions','groups']
    return value
