"""Pinned OpenROAD Hier-RTLMP + iEDA iPL integration fixture, bounded stages."""
import json,subprocess,time,uuid,shutil
from pathlib import Path
from . import ieda_runtime as rt
from .def_validation import read_def,lef_cells,validate_placement

ROOT=Path(__file__).resolve().parents[1]
REFERENCE=ROOT/'third_party/openroad-macro-reference'
CASE=ROOT/'cases/nangate_macro_smoke'
BACKEND_VERSION='nangate-macro-smoke-v1'
STAGES=['import_netlist','floorplan','macro_placement','placement','validate','export_def']

def config_path():
    local=ROOT/'.cache/openroad/backend.json'
    return local if local.is_file() else ROOT/'environments/openroad/backend.lock.json'

def config():
    value=json.loads(config_path().read_text(encoding='utf-8'))
    locked=json.loads((ROOT/'environments/openroad/backend.lock.json').read_text(encoding='utf-8'))
    if value['image']!=locked['image'] or value['executable']!=locked['executable']:
        raise ValueError('Local OpenROAD configuration differs from reviewed lock')
    return value

def input_files():
    return [CASE/'macro_smoke.v',REFERENCE/'test/Nangate45/Nangate45_tech.lef',
            REFERENCE/'test/Nangate45/Nangate45_stdcell.lef',REFERENCE/'src/mpl/test/testcases/macro_only.lef',
            REFERENCE/'test/Nangate45/Nangate45_typ.lib',REFERENCE/'src/mpl/test/testcases/macro_only.lib',
            CASE/'constraints.sdc',CASE/'manifest.json',REFERENCE/'SOURCE.json',config_path(),ROOT/'environments/openroad/backend.lock.json',
            rt.REFERENCE/'scripts/design/sky130_gcd/iEDA_config/pl_default_config.json',
            rt.REFERENCE/'scripts/design/sky130_gcd/iEDA_config/flow_config.json',
            rt.REFERENCE/'scripts/design/sky130_gcd/iEDA_config/db_default_config.json']

LEFS='''read_lef /reference/test/Nangate45/Nangate45_tech.lef
read_lef /reference/test/Nangate45/Nangate45_stdcell.lef
read_lef /reference/src/mpl/test/testcases/macro_only.lef
'''
LIBS='''read_liberty /reference/test/Nangate45/Nangate45_typ.lib
read_liberty /reference/src/mpl/test/testcases/macro_only.lib
'''
IEDA='''flow_init -config /work/config/flow_config.json
db_init -config /work/config/db_default_config.json
tech_lef_init -path /reference/test/Nangate45/Nangate45_tech.lef
lef_init -path {/reference/test/Nangate45/Nangate45_stdcell.lef /reference/src/mpl/test/testcases/macro_only.lef}
'''

def setup(work):
    for name in ('result','logs','config','result/report','result/pl'): (work/name).mkdir(parents=True,exist_ok=True)
    source=rt.REFERENCE/'scripts/design/sky130_gcd/iEDA_config'
    for name in ('flow_config.json','db_default_config.json','pl_default_config.json'):
        shutil.copy2(source/name,work/'config'/name)
    p=work/'config/db_default_config.json';c=json.loads(p.read_text());c['LayerSettings']['routing_layer_1st']='metal1';p.write_text(json.dumps(c))
    p=work/'config/pl_default_config.json';c=json.loads(p.read_text());pl=c['PL']
    pl['num_threads']=4;pl['BUFFER']['buffer_type']=['BUF_X1'];pl['GP']['Density'].update(target_density=0.7,bin_cnt_x=64,bin_cnt_y=64)
    pl['Filler'].update(first_iter=['FILLCELL_X1'],second_iter=['FILLCELL_X1'])
    p.write_text(json.dumps(c))
    (work/'import.tcl').write_text(LEFS+LIBS+'''read_verilog /case/macro_smoke.v
link_design macro_smoke
write_def /work/result/import.def
exit
''')
    (work/'floorplan.tcl').write_text(LEFS+LIBS+'''read_verilog /case/macro_smoke.v
link_design macro_smoke
initialize_floorplan -die_area {0 0 600 600} -core_area {5 5 595 595} -site FreePDK45_38x28_10R_NP_162NW_34O
make_tracks
write_def /work/result/floorplan.def
exit
''')
    (work/'macro.tcl').write_text(LEFS+LIBS+'''read_verilog /case/macro_smoke.v
link_design macro_smoke
read_def /work/result/floorplan.def -floorplan_initialize
set_thread_count 4
rtl_macro_placer -report_directory /work/result/mpl
foreach inst [[ord::get_db_block] getInsts] {
  if {[[$inst getMaster] isBlock]} { $inst setPlacementStatus LOCKED }
}
write_def /work/result/macro.def
exit
''')
    (work/'placement.tcl').write_text(IEDA+'''db_init -lib_path {/reference/test/Nangate45/Nangate45_typ.lib /reference/src/mpl/test/testcases/macro_only.lib}
def_init -path /work/result/macro.def
run_placer -config /work/config/pl_default_config.json
def_save -path /work/result/placed.def
flow_exit
''')
    (work/'readback.tcl').write_text(LEFS+'''read_def /work/result/placed.def
write_def /work/result/readback.def
exit
''')

def run_script(stage,work):
    image=rt.IMAGE if stage=='placement' else config()['image']
    script={'import_netlist':'import','floorplan':'floorplan','macro_placement':'macro','placement':'placement','export_def':'readback'}[stage]
    executable='iEDA' if stage=='placement' else config()['executable']
    name='aieda-macro-'+uuid.uuid4().hex[:12]
    args=['run','--pull=never','--rm','--name',name,'--network','none','--cpus','4','--memory','8g','--pids-limit','512',
          '--mount',f'type=bind,source={REFERENCE},target=/reference,readonly',
          '--mount',f'type=bind,source={CASE},target=/case,readonly',
          '--mount',f'type=bind,source={work},target=/work','--workdir','/work',
          '--env','RESULT_DIR=/work/result','--env','CONFIG_DIR=/work/config',
          '--entrypoint','/usr/bin/timeout',image,'--kill-after=5','180',executable]
    args += ['-script',f'/work/{script}.tcl'] if stage=='placement' else ['-exit',f'/work/{script}.tcl']
    log=work/'logs'/(stage+'.log')
    with log.open('w',encoding='utf-8') as stream:
        try: p=subprocess.run(rt.docker()+args,stdout=stream,stderr=subprocess.STDOUT,timeout=195,creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:
            try:rt.invoke(['kill',name],timeout=8)
            except RuntimeError:pass
            raise RuntimeError(f'Backend deadline exceeded; see {log}') from None
    if p.returncode:raise RuntimeError(f'{stage} exited {p.returncode}; see {log}')
    return str(log)

def execute(stage,work):
    work=Path(work);lefs=input_files()[2:4]
    if stage=='validate':
        report=rt.parse_placement_report(work/'result/pl/report/summary_report.txt')
        independent=validate_placement(read_def(work/'result/import.def'),read_def(work/'result/macro.def'),read_def(work/'result/placed.def'),lefs)
        if not report['placement_checks_passed'] or not independent['passed']:
            raise ValueError('Placement check failed: '+json.dumps({'backend':report,'independent':independent}))
        return {'backend':report,'independent':independent}
    started=time.monotonic();log=run_script(stage,work)
    name={'import_netlist':'import','floorplan':'floorplan','macro_placement':'macro','placement':'placed','export_def':'readback'}[stage]
    path=work/'result'/(name+'.def');design=read_def(path)
    cells={};[cells.update(lef_cells(p,design['units'])) for p in lefs]
    macros={k:v for k,v in design['components'].items() if cells[v['master']]['hard_macro']}
    result={'artifact':str(path),'log':log,'seconds':round(time.monotonic()-started,3),'instances':len(design['components']),
            'nets':len(design['nets']),'units':design['units'],'hard_macros':len(macros),
            'movable_hard_macros':sum(not v['placement'] or v['placement'][0]!='FIXED' for v in macros.values())}
    if stage=='macro_placement':
        floor=read_def(work/'result/floorplan.def')
        source={**floor,'components':{k:v for k,v in floor['components'].items() if k in macros}}
        macro_design={**design,'components':macros}
        check=validate_placement(source,source,macro_design,lefs)
        if not check['passed'] or not macros or result['movable_hard_macros']:
            raise ValueError('Macro placement not accepted: '+json.dumps(check))
        result.update(independent_macro_check=check,previously_unplaced=sum(v['placement'] is None for v in source['components'].values()))
    if stage=='export_def':
        if read_def(work/'result/placed.def')!=design:raise ValueError('Fresh OpenDB readback differs from iEDA placement')
        result.update(readback_equal=True,readback_coverage=['design','units','die','components_and_placement','normal_nets','pins'])
    return result
