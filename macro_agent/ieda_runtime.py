"""Bounded iEDA container adapter for a pinned public Sky130 GCD fixture.

This is a separate real-EDA smoke flow, not a converter for teaching JSON layouts.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT/'third_party/ieda-reference'
from .portable_ieda import IMAGE, ENV, adapt_placement_config
LEGACY_IMAGE = 'iedaopensource/release@sha256:8f6c311485c77374ccea149b2cc54d02ed789b189161daa223b1996ceb38f8e2'
DOCKER_CONFIG = ROOT/'.cache/ieda/docker-public'
ENGINE = 'npipe:////./pipe/dockerDesktopLinuxEngine'
VERIFIED = ROOT/'.cache/ieda/verified-portable.json'

def docker():
    executable=shutil.which('docker')
    if not executable: raise RuntimeError('Docker CLI not found')
    return [executable,'--config',str(DOCKER_CONFIG),'--host',ENGINE]

def invoke(args,timeout=20):
    p=subprocess.run(docker()+args,capture_output=True,text=True,encoding='utf-8',errors='replace',
                     timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if p.returncode: raise RuntimeError((p.stderr or p.stdout)[-1500:])
    return p.stdout

def status():
    result={'tool_id':'iEDA','source':'https://github.com/OSCC-Project/iEDA','image':IMAGE,
            'available':False,'capability':'public Sky130 GCD floorplan and standard-cell placement',
            'macro_placement_verified':False,'accepts_toy_layout':False}
    try:
        result['engine']=invoke(['info','--format','{{.OSType}}/{{.Architecture}}'],timeout=8).strip()
        result['image_id']=invoke(['image','inspect',IMAGE,'--format','{{.Id}}'],timeout=8).strip()
        if not (REFERENCE/'manifest.json').is_file(): raise RuntimeError('Pinned public fixture is not provisioned')
        if not VERIFIED.is_file(): raise RuntimeError('Fixture execution has not passed verification yet')
        evidence=json.loads(VERIFIED.read_text(encoding='utf-8'))
        if evidence.get('image')!=IMAGE or evidence.get('status')!='completed':
            raise RuntimeError('Verification evidence does not match installed image')
        result.update(available=True,verification_ref=evidence['report'])
    except (RuntimeError,subprocess.TimeoutExpired,OSError,ValueError) as exc:
        result['reason']=str(exc)
    return result

def prepare(run):
    source=REFERENCE/'scripts/design/sky130_gcd'
    shutil.copytree(source/'script',run/'script')
    shutil.copytree(source/'iEDA_config',run/'config')
    adapt_placement_config(run/'config/pl_default_config.json')
    for folder in ['result/report','result/pl','result/feature','result/sta','logs']:
        (run/folder).mkdir(parents=True,exist_ok=True)
    # GCD uses only HS standard cells. Do not load unrelated IO/SRAM libraries.
    (run/'script/DB_script/db_path_setting.tcl').write_text('''set TECH_LEF_PATH /reference/scripts/foundry/sky130/lef/sky130_fd_sc_hs.tlef
set LEF_PATH /reference/scripts/foundry/sky130/lef/sky130_fd_sc_hs_merged.lef
set LIB_PATH /reference/scripts/foundry/sky130/lib/sky130_fd_sc_hs__tt_025C_1v80.lib
set SDC_PATH /reference/scripts/foundry/sky130/sdc/gcd.sdc
''',encoding='utf-8')
    placement=run/'script/iPL_script/run_iPL.tcl'
    placement.write_text(placement.read_text(encoding='utf-8').replace('iTO_fix_fanout_result.def','iFP_result.def'),encoding='utf-8')
    (run/'commands.tcl').write_text('puts "IEDA_COMMANDS=[lsort [info commands *]]"\nexit\n',encoding='utf-8')

def parse_placement_report(path):
    text=Path(path).read_text(encoding='utf-8')
    fields={key.strip():value.strip() for key,value in re.findall(r'^\|\s*([^|]+)\|\s*([^|]+)\|',text,re.M)}
    names=['Core Range Violated Count','Row/Site Alignment Violated Count',
           'Power Alignment Violated Count','Overlap Violated Count']
    violations={name:int(fields[name]) for name in names}
    return {'instances':int(fields['Instances Count']),'nets':int(fields['Nets Count']),
            'hard_macros':int(fields['- Macro Count']), 'hpwl_dbu':int(fields['Total HPWL']),
            'violations':violations,'placement_checks_passed':all(v==0 for v in violations.values()),
            'validation_source':'iPL report (not independent signoff)','source':str(path)}

def run_case(run,case_id='sky130_gcd',verify=False):
    if case_id!='sky130_gcd': raise ValueError('Only the reviewed sky130_gcd fixture is supported')
    run=Path(run).resolve()
    if not run.is_relative_to((ROOT/'runs').resolve()): raise ValueError('Output must be under project runs')
    if run.exists():
        report=run/'ieda-report.json'
        if report.exists(): return json.loads(report.read_text(encoding='utf-8'))
        raise ValueError('Output directory already exists without a completed report; choose a new run')
    run.mkdir(parents=True)
    prepare(run)
    env={'CONFIG_DIR':'/work/config','FOUNDRY_DIR':'/reference/scripts/foundry/sky130',
         'RESULT_DIR':'/work/result','TCL_SCRIPT_DIR':'/work/script','DESIGN_TOP':'gcd',
         'NETLIST_FILE':'/reference/scripts/design/sky130_gcd/result/verilog/gcd.v',
         'SDC_FILE':'/reference/scripts/foundry/sky130/sdc/gcd.sdc',
         'DIE_AREA':'0.0 0.0 149.96 150.128','CORE_AREA':'9.996 10.08 139.964 140.048',
         'OMP_NUM_THREADS':'4', **ENV}
    report={'status':'running','case_id':case_id,'image':IMAGE,'run':str(run),'stages':[],
            'scope':'real Sky130 standard-cell floorplan/placement smoke test; no hard macros',
            'macro_placement_verified':False,'ppa_improvement_claimed':False,
            'adaptations':['load only GCD HS libraries','feed iFP DEF directly to iPL; skip fanout optimization']}
    try:
        for stage,script in [('hello','/reference/scripts/hello.tcl'),('commands','/work/commands.tcl'),
                             ('floorplan','/work/script/iFP_script/run_iFP.tcl'),('placement','/work/script/iPL_script/run_iPL.tcl')]:
            name='aieda-'+uuid.uuid4().hex[:16]
            args=['run','--rm','--name',name,'--network','none','--cpus','4','--memory','8g',
                  '--pids-limit','256','--mount',f'type=bind,source={REFERENCE},target=/reference,readonly',
                  '--mount',f'type=bind,source={run},target=/work','--workdir','/work']
            for key,value in env.items(): args+=['--env',key+'='+value]
            # Container-side deadline also bounds work if the DSH bridge is cancelled.
            args += [IMAGE,'/usr/bin/timeout','--kill-after=5','40','iEDA','-script',script]
            started=time.monotonic(); logfile=run/'logs'/f'{stage}.log'
            with logfile.open('w',encoding='utf-8') as log:
                try:
                    p=subprocess.run(docker()+args,stdout=log,stderr=subprocess.STDOUT,timeout=50,
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                except subprocess.TimeoutExpired:
                    invoke(['kill',name],timeout=10)
                    raise RuntimeError(f'{stage} timed out; container stopped') from None
            text=logfile.read_text(encoding='utf-8',errors='replace')
            report['stages'].append({'stage':stage,'exit_code':p.returncode,'seconds':round(time.monotonic()-started,2),'log':str(logfile)})
            if p.returncode: raise RuntimeError(f'{stage} failed, exit {p.returncode}: {text[-1800:]}')
            if stage=='hello' and 'Hello iEDA!' not in text: raise RuntimeError('Missing hello marker')
            if stage in ('floorplan','placement'):
                artifact=run/'result'/('iFP_result.def' if stage=='floorplan' else 'iPL_result.def')
                if not artifact.exists() or 'END DESIGN' not in artifact.read_text(encoding='utf-8'):
                    raise RuntimeError(f'{stage} did not produce a complete DEF')
        report['placement']=parse_placement_report(run/'result/pl/report/summary_report.txt')
        if not report['placement']['placement_checks_passed']: raise RuntimeError('iPL reported placement violations')
        report['status']='completed'
        # glog creates Linux symlinks which Windows cannot always stat. Record
        # explicit deliverables, not the solver's internal log links.
        artifacts = list((run/'result').glob('*.def')) + list((run/'result').glob('*.v')) + list((run/'result/report').glob('*.rpt')) + list((run/'result/pl/report').glob('*.txt'))
        report['artifacts']=[{'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                             for p in sorted(artifacts)]
    except Exception as exc:
        report.update(status='failed',error=str(exc))
    target=run/'ieda-report.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if verify and report['status']=='completed':
        VERIFIED.write_text(json.dumps({'status':'completed','image':IMAGE,'report':str(target)},indent=2),encoding='utf-8')
    return report

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['status','run'])
    parser.add_argument('--run-dir');parser.add_argument('--verify',action='store_true');args=parser.parse_args()
    if args.action=='status': result=status()
    else: result=run_case(args.run_dir or ROOT/'runs'/('ieda-gcd-'+time.strftime('%Y%m%d-%H%M%S')),verify=args.verify)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if args.action=='run' and result['status']!='completed': raise SystemExit(1)

if __name__=='__main__': main()
