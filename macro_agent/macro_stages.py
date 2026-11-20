"""Registered two-SRAM path. Native iEDA computes all placement coordinates."""
import copy
from functools import partial
import json
from pathlib import Path
import re
import subprocess
import time
from types import SimpleNamespace
import uuid
from . import ieda_stages as placement
from .portable_ieda import ENV
from .def_validation import read_def,lef_cells,validate_placement
from .netlist_check import verify_import,liberty_bus_ports

VERSION=placement.BACKEND_VERSION+'-sram-v1'
STAGES=['import_netlist','floorplan','macro_placement','placement','validate','export_def']


def accept_macro_candidate(original,native,cells,manifest):
    errors=[];expected=copy.deepcopy(original);boxes=[];sentinels=[]
    names=sorted(n for n,c in original['components'].items() if cells[c['master']]['hard_macro'])
    if names!=sorted(manifest['macro_placement']['macros']):errors.append('unexpected_macro_set')
    core=[round(x*original['units']) for x in manifest['core_area_microns']]
    for name in names:
        before=original['components'][name];after=native['components'].get(name)
        if before['placement'] is not None:errors.append('hidden_macro_placement:'+name)
        p=after['placement'] if after else None
        if not after or after['master']!=before['master'] or not p or p[0]!='PLACED' or p[3]!='N':
            errors.append('unsupported_native_macro:'+name);continue
        x,y=p[1:3];w,h=cells[before['master']]['size'];box=(x,y,x+w,y+h,name)
        if not(core[0]<=x and core[1]<=y and x+w<=core[2] and y+h<=core[3]):errors.append('macro_outside_core:'+name)
        if any(min(box[2],b[2])>max(box[0],b[0]) and min(box[3],b[3])>max(box[1],b[1]) for b in boxes):errors.append('macro_overlap')
        boxes.append(box);expected['components'][name]=after
    for name,before in original['components'].items():
        if name not in names and before['placement'] is None and native['components'].get(name)=={'master':before['master'],'placement':['PLACED',-1,-1,'N']}:
            sentinels.append(name);expected['components'][name]=native['components'][name]
    if expected!=native:errors.append('unexpected_non_macro_semantic_change')
    return {'passed':not errors,'errors':errors,'macros':names,'boxes':boxes,'restored_unplaced_stdcell_sentinels':sentinels,
            'scope':'native macro geometry/identity, core bounds, no overlap, original logical and physical semantics; no coordinate synthesis'}


def decorate(base,reference):
    return SimpleNamespace(rt=base.rt,BACKEND_VERSION=VERSION,STAGES=STAGES,manifest=base.manifest,
        input_files=lambda:base.input_files()+[Path(__file__),Path(__file__).with_name('netlist_check.py')],
        setup=partial(setup,base=base),execute=partial(execute,base=base,reference=Path(reference)))


def setup(work,base):
    base.setup(work);work=Path(work);m=base.manifest()
    p=work/'config/pl_default_config.json';cfg=json.loads(p.read_text())
    cfg['PL']['GP']['Density'].update(m['placement_profile']);cfg['PL']['num_threads']=m['budget']['cpu_threads']
    p.write_text(json.dumps(cfg,indent=2))
    p=work/'script/iPL_script/run_iPL.tcl';text=p.read_text()
    if text.count('iFP_result.def')!=1:raise ValueError('Unexpected standard-cell script input')
    p.write_text(text.replace('iFP_result.def','macros_fixed.def'))


def execute(stage,work,base,reference):
    work=Path(work);m=base.manifest();lefs=[reference/p for p in m['cell_lefs']]
    if stage=='import_netlist':
        result=base.execute(stage,work)
        result['independent_netlist']=verify_import(reference/m['netlist'],Path(result['artifact']),liberty_bus_ports(reference/m['sram_bus_lib']))
        if not result['independent_netlist']['passed']:raise ValueError('Independent SRAM input mismatch')
        return result
    if stage=='validate':
        report=base.rt.parse_placement_report(work/'result/pl/report/summary_report.txt')
        check=validate_placement(read_def(work/'result/import.def'),read_def(work/'result/macros_fixed.def'),read_def(work/'result/iPL_result.def'),lefs,policy=m)
        result={'backend':report,'independent':check}
        (work/'validation.json').write_text(json.dumps(result,indent=2))
        if not check['passed'] or not report['placement_checks_passed']:raise ValueError('SRAM placement validation failed')
        return result
    if stage!='macro_placement':return base.execute(stage,work)
    script='''flow_init -config /work/config/flow_config.json
db_init -config /work/config/db_default_config.json
source /work/script/DB_script/db_path_setting.tcl
source /work/script/DB_script/db_init_lef.tcl
db_init -lib_path $LIB_PATH
db_init -sdc_path $SDC_PATH
def_init -path /work/result/iFP_result.def
init_pl -config /work/config/pl_default_config.json
placer_run_mp
def_save -path /work/result/native_macros.def
puts "NATIVE_MP_OK"
'''
    (work/'macro-stage.tcl').write_text('if {[catch {\n'+script+'} message]} {puts stderr $message; exit 1}\nflow_exit\n')
    b=m['budget'];name='aieda-mp-'+uuid.uuid4().hex[:12]
    args=base.rt.docker()+['run','--rm','--pull=never','--name',name,'--network','none','--cpus',str(b['cpu_threads']),
        '--memory',str(b['memory_gb'])+'g','--pids-limit','256','--ulimit','core=0','--workdir','/work',
        '--mount',f'type=bind,source={reference},target=/reference,readonly',
        '--mount',f'type=bind,source={work},target=/work',
        '--mount',f'type=bind,source={reference / m["macro_placement"]["hmetis"]},target=/src/third_party/hmetis/hmetis2.0pre1,readonly']
    for k,v in {**ENV,'OMP_NUM_THREADS':str(b['cpu_threads']),'RESULT_DIR':'/work/result','CONFIG_DIR':'/work/config','TCL_SCRIPT_DIR':'/work/script'}.items():args+=['--env',k+'='+v]
    args += [base.rt.IMAGE,'timeout','--kill-after=5',str(b['container_seconds']),'iEDA','-script','/work/macro-stage.tcl']
    started=time.monotonic();log=work/'logs/macro_placement.log'
    with log.open('w') as out:
        try:code=subprocess.run(args,stdout=out,stderr=subprocess.STDOUT,timeout=b['host_seconds'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode
        except subprocess.TimeoutExpired:
            try:base.rt.invoke(['kill',name])
            except RuntimeError:pass
            raise RuntimeError('Native MP timeout; container stopped') from None
    if code or 'NATIVE_MP_OK' not in log.read_text(errors='replace'):raise ValueError('Native MP failed; see '+str(log))
    before=read_def(work/'result/iFP_result.def');native=read_def(work/'result/native_macros.def');cells={}
    for lef in lefs:cells.update(lef_cells(lef,native['units']))
    check=accept_macro_candidate(before,native,cells,m)
    (work/'result/macro-check.json').write_text(json.dumps(check,indent=2))
    if not check['passed']:raise ValueError('Native macro candidate rejected: '+str(check['errors']))
    text=(work/'result/native_macros.def').read_text();expected=copy.deepcopy(native)
    for n in check['macros']:
        text,count=re.subn(r'(^\s*-\s+'+re.escape(n)+r'\s+[^\n]*?\+)\s+PLACED\b',r'\1 FIXED',text,count=1,flags=re.M)
        if count!=1:raise ValueError('Cannot freeze macro record')
        expected['components'][n]['placement'][0]='FIXED'
    for n in check['restored_unplaced_stdcell_sentinels']:
        text,count=re.subn(r'(^\s*-\s+'+re.escape(n)+r'\s+[^\n]*?\+)\s+PLACED\s+\(\s*-1\s+-1\s*\)\s+N\b',r'\1 UNPLACED',text,count=1,flags=re.M)
        if count!=1:raise ValueError('Cannot restore sentinel record')
        expected['components'][n]['placement']=None
    fixed=work/'result/macros_fixed.def';fixed.write_text(text)
    if read_def(fixed)!=expected:raise ValueError('Status-only macro freeze changed other semantics')
    return {'artifact':str(fixed),'native_artifact':str(work/'result/native_macros.def'),
        'independent_macro_check':check,'log':str(log),'seconds':round(time.monotonic()-started,3),
        'instances':len(native['components']),'nets':len(native['nets']),'units':native['units']}
