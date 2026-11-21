"""One registered Nangate45 macro case; server-only bounded first qualification run."""
from pathlib import Path
from types import SimpleNamespace
import copy,hashlib,json,os,re,shutil,subprocess,time,uuid
from . import ieda_runtime as rt
from .def_validation import read_def,lef_cells,validate_placement
from .portable_ieda import ENV,IMAGE,BINARY_SHA256

ROOT=Path(__file__).resolve().parents[1]
CASE='swerv_nangate45'
VERSION='swerv-nangate-native-v1'
CTS_SHA256='e756b7a9a29238ff0b658acfb95728ab00681dbdd3110ec4eeb58359019cc5e8'
STAGES=['import_netlist','floorplan','macro_placement','fanout','placement','validate','export_def','cts','to_drv','to_hold','legalization','routing','filler','drc','timing','gds_export','routed_readback']
BUFFERS={f'BUF_X{i}':('A','Z') for i in (1,2,4,8,16,32)}
PREVIOUS={'macro_placement':'floorplan','fanout':'macro_placement','placement':'fanout','export_def':'placement','cts':'export_def','to_drv':'cts','to_hold':'to_drv','legalization':'to_hold','routing':'legalization','filler':'routing','drc':'filler','timing':'filler','routed_readback':'filler'}

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def manifest(reference=None):return json.loads(((Path(reference) if reference else ROOT/'cases/ibench'/CASE)/'manifest.json').read_text())

def cells_and_buses(reference,m):
    from .liberty_buses import read_buses
    cells={}
    for name in m['cell_lefs']:cells.update(lef_cells(reference/name,2000))
    return cells,read_buses([reference/n for n in m['libs']],cells)

def preflight(reference):
    from .aes_netlist import parse
    reference=Path(reference);m=manifest(reference);cells,buses=cells_and_buses(reference,m)
    data=parse(reference/m['netlist'],buses)
    if set(data['components'].values())-set(cells):raise ValueError('Unresolved input master')
    macros={n:c for n,c in data['components'].items() if cells[c]['hard_macro']}
    if macros!=m['expected_macro_masters'] or len(data['components'])!=6780:raise ValueError('Unexpected registered design')
    for partition in data['partitions']:
        for inst,pin in partition:
            if inst!='PIN' and pin not in cells[data['components'][inst]]['pins']:raise ValueError('Unresolved leaf pin')
    for item in json.loads((reference/'provenance/sources.json').read_text()):
        if sha(reference/item['relative'])!=item['sha256']:raise ValueError('Source identity changed')
    return {'passed':True,'instances':6780,'standard_cells':6777,'hard_macros':macros,'native_fullflow_qualified':False}

def for_case(case_id,reference_root=None):
    if case_id!=CASE:raise ValueError('Unsupported macro fullflow case')
    ref=Path(reference_root) if reference_root else ROOT/'cases/ibench'/CASE
    from .native_gds import input_files
    files=lambda:sorted(p for p in ref.rglob('*') if p.is_file())+[Path(__file__),ROOT/'macro_agent/liberty_buses.py',ROOT/'macro_agent/aes_netlist.py',ROOT/'macro_agent/aes_transforms.py',ROOT/'macro_agent/macro_stages.py',ROOT/'environments/ieda-aes-router/iEDA',ROOT/'environments/ieda-aes-router/manifest.json',ROOT/'environments/ieda-swerv-cts/iEDA']+input_files()
    return SimpleNamespace(rt=rt,BACKEND_VERSION=VERSION,STAGES=STAGES,manifest=lambda:manifest(ref),input_files=files,setup=lambda w:setup(w,ref),execute=lambda s,w:execute(s,w,ref),package=package)

def setup(work,reference):
    work=Path(work);preflight(reference);shutil.copytree(reference/'config',work/'config')
    for name in ('logs','result/report','result/pl','result/cts','result/no','result/to','result/to_drv','result/to_hold','result/rt','result/drc','result/timing'):(work/name).mkdir(parents=True,exist_ok=True)
    write(work/'run-start.json',{'time':time.time(),'wall_seconds':7200,'case_id':CASE})

def previous_stage(stage,m):
    if stage=="fanout" and not m["macro_placement"]["macros"]:
        return "floorplan"
    return PREVIOUS[stage]


def script(stage,m):
    pre='flow_init -config /work/config/flow_config.json\ndb_init -config /work/config/db_default_config.json\n'
    pre+=f'tech_lef_init -path /reference/{m["tech_lef"]}\nlef_init -path [list '+ ' '.join('/reference/'+p for p in m['cell_lefs'])+']\n'
    pre+='db_init -lib_path [list '+' '.join('/reference/'+p for p in m['libs'])+']\ndb_init -sdc_path /reference/'+m['sdc']+'\n'
    if stage in ('import_netlist','floorplan'):
        body=pre+f'verilog_init -path /reference/{m["netlist"]} -top {{{m["top"]}}}\n'
        if stage=='floorplan':
            body+='init_floorplan -die_area {'+' '.join(map(str,m['die_area_microns']))+'} -core_area {'+' '.join(map(str,m['core_area_microns']))+'} -core_site '+m['core_site']+'\n'
            for i,pitch in enumerate((280,380,280,560,560,560,1600,1600,3200,3200),1):body+=f'gern_track -layer metal{i} -x_start 190 -x_step {pitch} -y_start 140 -y_step {pitch}\n'
            body+='auto_place_pins -layer metal5 -width 800 -height 800\n'
            port=m.get('clock_port','clk')
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',port):raise ValueError('Invalid clock port')
            body+=f'set_net -net_name {port} -type CLOCK\n'
    else:
        body=pre+'def_init -path /work/result/'+previous_stage(stage,m)+'.def\n'
        commands={'macro_placement':'init_pl -config /work/config/pl_default_config.json\nplacer_run_mp',
            'fanout':'run_no_fixfanout -config /work/config/no_default_config_fixfanout.json',
            'placement':'run_placer -config /work/config/pl_default_config.json','export_def':'',
            'cts':'run_cts -config /work/config/cts_default_config.json -work_dir /work/result/cts\ncts_report -path /work/result/cts',
            'to_drv':'run_to_drv -config /work/config/to_default_config_drv.json','to_hold':'run_to_hold -config /work/config/to_default_config_hold.json',
            'legalization':'run_incremental_flow -config /work/config/pl_default_config.json',
            'routing':'init_rt -temp_directory_path /work/result/rt -bottom_routing_layer metal2 -top_routing_layer metal6 -thread_number 4\nrun_rt\ndestroy_rt',
            'filler':'run_filler -config /work/config/pl_default_config.json',
            'drc':'run_drc -config /work/config/drc_default_config.json -path /work/result/report/drc.rpt\nsave_drc -path /work/result/drc/detail.drc',
            'timing':'run_sta -output /work/result/timing','routed_readback':''}
        body+=commands[stage]+'\n'
    body+=f'def_save -path /work/result/{stage}.def\nnetlist_save -path /work/result/{stage}.v -exclude_cell_names {{}}\nreport_db -path /work/result/report/{stage}.rpt\nputs "SWERV_STAGE_OK {stage}"\n'
    return 'if {[catch {\n'+body+'} message]} {puts stderr $message; exit 1}\nflow_exit\n'

def freeze_macros(work,reference,m):
    from .macro_stages import accept_macro_candidate
    artifact=work/'result/macro_placement.def';original=read_def(work/'result/floorplan.def');native=read_def(artifact);cells={}
    for p in m['cell_lefs']:cells.update(lef_cells(reference/p,native['units']))
    check=accept_macro_candidate(original,native,cells,m);write(work/'result/macro-check.json',check)
    if not check['passed']:raise ValueError('Native macro candidate rejected: '+str(check['errors']))
    shutil.copyfile(artifact,work/'result/native_macros.def');text=artifact.read_text();expected=copy.deepcopy(native)
    for n in check['macros']:
        text,count=re.subn(r'(^\s*-\s+'+re.escape(n)+r'\s+[^\n]*?\+)\s+PLACED\b',r'\1 FIXED',text,count=1,flags=re.M)
        if count!=1:raise ValueError('Cannot freeze macro')
        expected['components'][n]['placement'][0]='FIXED'
    for n in check['restored_unplaced_stdcell_sentinels']:
        text,count=re.subn(r'(^\s*-\s+'+re.escape(n)+r'\s+[^\n]*?\+)\s+PLACED\s+\(\s*-1\s+-1\s*\)\s+N\b',r'\1 UNPLACED',text,count=1,flags=re.M)
        if count!=1:raise ValueError('Cannot restore sentinel')
        expected['components'][n]['placement']=None
    artifact.write_text(text)
    if read_def(artifact)!=expected:raise ValueError('Unexpected macro freeze changes')
    return check


def normalize_unplaced(artifact):
    """Repair iDB's orientation-less UNPLACED sentinel export, no coordinate design."""
    artifact=Path(artifact);before=read_def(artifact);text=artifact.read_text()
    fixed,count=re.subn(r'\+ UNPLACED\s+\(\s*-1\s+-1\s*\)\s*(?=;)', '+ UNPLACED ',text)
    if not count:return {'changed_records':0}
    raw=artifact.with_suffix('.native.def');shutil.copyfile(artifact,raw);artifact.write_text(fixed)
    if read_def(artifact)!=before:raise ValueError('UNPLACED syntax repair changed DEF semantics')
    return {'changed_records':count,'native_source':str(raw),'native_sha256':sha(raw),'semantic_equality':True,'scope':'Remove invalid optional -1 coordinate pair without orientation from UNPLACED records'}

def native_deadline(stage,work,now=None):
    """Honor an audited, task-local retry amendment; never reset old clocks."""
    work=Path(work);now=time.time() if now is None else now
    extension=work.parent.parent/'approved-budget-extension-6h.json'
    if not extension.exists():extension=work.parent.parent/'approved-budget-extension.json'
    if extension.is_file():
        e=json.loads(extension.read_text())
        if (e.get('schema_version')!='swerv_budget_extension_v1' or
            e.get('task_id')!=work.parent.parent.name or
            work.parent.name!='attempts' or e.get('case_id')!=CASE or
            (e.get('routing_seconds'),e.get('expires_at',0)-e.get('issued_at',0)) not in ((10800,14400),(21600,25200)) or
            (e.get('routing_seconds')==21600 and (extension.name!='approved-budget-extension-6h.json' or e.get('routing_attempt_limit')!=3)) or
            e.get('other_stage_seconds')!=600 or now<e['issued_at'] or
            e.get('cpu_threads')!=4 or e.get('memory_gb')!=8 or
            not e.get('original_budget_failed') or not e.get('authorization')):
            raise ValueError('Invalid audited SWERV budget extension')
        if sha(work/'result/legalization.def')!=e['checkpoint_sha256']:
            raise ValueError('Retry legalization checkpoint changed')
        seconds=min(e['routing_seconds'] if stage=='routing' else e['other_stage_seconds'],int(e['expires_at']-now)-10)
    else:
        start=json.loads((work/'run-start.json').read_text())['time']
        seconds=min(5400 if stage=='routing' else 600,int(7200-(now-start))-10)
    if seconds<=0:raise ValueError('Native workflow budget exhausted; no automatic extension')
    return seconds


def sample_route_progress(work,root_pid):
    """Read only this worker's descendant processes; CPU activity is not progress."""
    if os.name!='posix':return
    processes={}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            if p.stat().st_uid!=os.getuid():continue
            data=(p/'stat').read_text().rsplit(')',1)[1].split()
            processes[int(p.name)]={'pid':int(p.name),'ppid':int(data[1]),'start_ticks':data[19],
                'cpu_seconds':(int(data[11])+int(data[12]))/os.sysconf('SC_CLK_TCK'),
                'rss_bytes':int(data[21])*os.sysconf('SC_PAGE_SIZE'),'state':data[0],
                'name':(p/'comm').read_text().strip()}
        except (OSError,ValueError,IndexError):continue
    owned={root_pid}
    while True:
        expanded=owned|{pid for pid,v in processes.items() if v['ppid'] in owned}
        if expanded==owned:break
        owned=expanded
    log=Path(work)/'result/rt/rt.log';tail=''
    if log.is_file():
        with log.open('rb') as f:
            f.seek(max(0,log.stat().st_size-4096));tail=f.read().decode(errors='replace')
    item={'time':time.time(),'root_pid':root_pid,'processes':[processes[p] for p in sorted(owned) if p in processes],
        'log_bytes':log.stat().st_size if log.exists() else 0,'last_lines':tail.splitlines()[-4:],
        'interpretation':'CPU utilization does not prove algorithm progress; TG counts are not full-route completion'}
    with (Path(work)/'logs/routing-progress.jsonl').open('a') as f:f.write(json.dumps(item)+'\n')


def execute(stage,work,reference):
    from .aes_flow import ROUTER_SHA256,prune_duplicate_drc_exports
    from .aes_transforms import check
    from .backend_checks import route_records
    work=Path(work).resolve();reference=Path(reference).resolve();m=manifest(reference)
    if stage not in STAGES:raise ValueError('Unknown stage')
    lefs=[reference/p for p in m['cell_lefs']]
    if stage=='validate':
        placed=read_def(work/'result/placement.def');before=read_def(work/'result/fanout.def')
        reports=list((work/'result/pl').rglob('summary_report.txt'))
        if len(reports)!=1:raise ValueError('Expected native placement summary')
        v={'backend':rt.parse_placement_report(reports[0]),'independent':validate_placement(before,before,placed,lefs,m)}
        v['passed']=v['backend']['placement_checks_passed'] and v['independent']['passed'];write(work/'validation.json',v)
        if not v['passed']:raise ValueError('Placement validation failed: '+str(v['independent']['errors']))
        return v
    seconds=native_deadline(stage,work)
    export=stage=='gds_export';router=ROOT/'environments/ieda-aes-router/iEDA';exporter=ROOT/'environments/ieda-export/bin/ieda-idb-export'
    env={**ENV,'OMP_NUM_THREADS':'4','OMP_THREAD_LIMIT':'4','OPENBLAS_NUM_THREADS':'1','RESULT_DIR':'/work/result','CONFIG_DIR':'/work/config','TCL_SCRIPT_DIR':'/work/script'}
    name='aieda-swerv-'+uuid.uuid4().hex[:12]
    args=rt.docker()+['run','--rm','--pull=never','--name',name,'--network','none','--cpus','4','--memory','8g','--pids-limit','256','--ulimit','core=0','--ulimit','fsize=1073741824','--workdir','/work','--mount',f'type=bind,source={reference},target=/reference,readonly','--mount',f'type=bind,source={work},target=/work']
    target=['iEDA','-script','/work/stage.tcl'];binary=BINARY_SHA256;image=IMAGE
    if stage=='macro_placement':args+=['--mount',f'type=bind,source={reference/m["macro_placement"]["hmetis"]},target=/src/third_party/hmetis/hmetis2.0pre1,readonly']
    if stage=='cts':
        cts=ROOT/'environments/ieda-swerv-cts/iEDA'
        if sha(cts)!=CTS_SHA256:raise ValueError('Registered CTS identity changed')
        args+=['--mount',f'type=bind,source={cts.parent},target=/cts,readonly'];target=['/cts/iEDA','-script','/work/stage.tcl'];binary=CTS_SHA256
    if stage=='to_hold' and m.get('hold_compatibility_guard'):
        guard=ROOT/'environments/ieda-hold-guard-v1'
        spec=json.loads((guard/'manifest.json').read_text())
        expected='f881cd0b0118bbfdab115a1cd793f18a666a6148da0a755eb591851c88df6abd'
        if (m['hold_compatibility_guard']!=expected or spec['binary_sha256']!=expected
            or spec['base_sha256']!=BINARY_SHA256 or spec['unit_test']!='GUARD_BOUNDARIES_OK'
            or sha(guard/'iEDA')!=expected):raise ValueError('Hold compatibility guard identity changed')
        args+=['--mount',f'type=bind,source={guard},target=/hold,readonly']
        target=['/hold/iEDA','-script','/work/stage.tcl'];binary=expected
    if stage=='routing':
        if sha(router)!=ROUTER_SHA256:raise ValueError('Router hash changed')
        args+=['--mount',f'type=bind,source={router.parent},target=/router,readonly'];target=['/router/iEDA','-script','/work/stage.tcl'];binary=ROUTER_SHA256
        env.update(IEDA_RT_NATIVE_LAYER_GRAPH='0',IEDA_RT_MAX_ITERATIONS='1',IEDA_RT_NATIVE_LAYER_TRACKS='1',IEDA_RT_MAX_MEMORY_MB='8192')
    if export:
        spec=json.loads((ROOT/'environments/ieda-export/runtime-manifest.json').read_text());binary=sha(exporter)
        if binary!=spec['executable_sha256']:raise ValueError('Exporter hash changed')
        args+=['--mount',f'type=bind,source={exporter.parent},target=/native,readonly'];image=spec['image']
        target=['/native/ieda-idb-export','/work/result/filler.def','/work/result/final.gds','/reference/'+m['tech_lef'],*['/reference/'+p for p in m['cell_lefs']]]
    for k,v in env.items():args+=['--env',k+'='+v]
    args += [image,'timeout','--kill-after=5',str(seconds),*target]
    (work/'stage.tcl').write_text('# Native abstract GDS export\n' if export else script(stage,m))
    shutil.copyfile(work/'stage.tcl',work/(stage+'.tcl'));log=work/'logs'/(stage+'.log');started=time.monotonic()
    with log.open('w') as out:
        proc=subprocess.Popen(args,stdout=out,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        next_sample=0
        try:
            while proc.poll() is None:
                time.sleep(1)
                if stage=='routing' and time.monotonic()>=next_sample:
                    try:sample_route_progress(work,proc.pid)
                    except OSError as exc:
                        with (work/'logs/progress-monitor-errors.txt').open('a') as f:f.write(str(exc)+'\n')
                    next_sample=time.monotonic()+30
                if time.monotonic()-started>seconds+15 or sum(p.stat().st_size for p in work.rglob('*') if p.is_file())>4*1024**3:raise RuntimeError('Native time or storage budget exceeded')
        finally:
            if proc.poll() is None:
                rt.invoke(['kill',name]);proc.wait(timeout=10)
    v={'stage':stage,'seconds':round(time.monotonic()-started,3),'returncode':proc.returncode,'log':str(log),'binary_sha256':binary,'deadline_seconds':seconds,'passed':False}
    artifact=work/'result'/('final.gds' if export else stage+'.def')
    if proc.returncode or not artifact.is_file() or ('IDB_NATIVE_EXPORT_OK' if export else 'SWERV_STAGE_OK '+stage) not in log.read_text(errors='replace'):
        write(work/(stage+'-evidence.json'),v);raise ValueError('Native stage failed: '+stage+'; '+str(log))
    v.update(artifact=str(artifact),artifact_sha256=sha(artifact),passed=True)
    if export:
        from .native_gds import validate
        v['validation']=validate(artifact,work/'result/filler.def',reference/m['tech_lef'],lefs)
    else:
        v['unplaced_syntax_normalization']=normalize_unplaced(artifact);v['artifact_sha256']=sha(artifact)
        after=read_def(artifact)
        if stage=='import_netlist':
            from .aes_netlist import verify
            _,buses=cells_and_buses(reference,m);v['import_check']=verify(reference/m['netlist'],artifact,buses)
            if not v['import_check']['passed'] or len(after['components'])!=m.get('expected_instances',6780):raise ValueError('Imported instance count changed')
        elif stage=='macro_placement':
            v['independent_macro_check']=freeze_macros(work,reference,m);v['artifact_sha256']=sha(artifact)
        elif stage=='floorplan':
            before=read_def(work/'result/import_netlist.def')
            v['floorplan_preservation']={'passed':before['nets']==after['nets'] and set(before['pins'])==set(after['pins']) and before['components']==after['components']}
        else:
            before=read_def(work/'result'/(previous_stage(stage,m)+'.def'))
            v['transformation']=check(before,after,stage,BUFFERS,r'FILLCELL_X(1|2|4|8|16|32)')
        if stage in ('export_def','routed_readback'):
            src=work/'result'/(previous_stage(stage,m)+'.def');v.update(readback_equal=read_def(src)==after and route_records(src)==route_records(artifact),readback_coverage=['parsed DEF semantics','per-net route records'])
            if not v['readback_equal']:v['passed']=False
        if stage in ('legalization','filler','routed_readback'):
            v['geometry']=validate_placement(after,after,after,lefs,m)
            if v['geometry']['hard_macros']!=len(m['expected_macro_masters']):v['geometry']['passed']=False
        if stage=='routing':
            from .aes_reproduction import routing_observation
            v['routing_gate']=routing_observation(json.loads((work/'result/rt/violation_reporter/route_summary.json').read_text()))
            route_log=(work/'result/rt/rt.log').read_text(errors='replace')
            begins=re.findall(r'DetailedRouter[^\n]*Begin iteration (\d+)/(\d+)',route_log);ends=re.findall(r'DetailedRouter[^\n]*End Iteration (\d+)/(\d+)',route_log)
            v['routing_profile']={'passed':begins==[('1','1')] and ends==begins,'requested':{'max_dr_iterations':1,'layers':['metal2','metal6']},'observed_iterations':begins}
        if stage=='drc':
            from .aes_reproduction import drc_observation
            v['drc_gate']=drc_observation(json.loads((work/'result/report/drc_summary.json').read_text()),report_dir=work/'result/report',producer_sha256=BINARY_SHA256)
        if stage=='timing':
            p=work/'result/timing'/(m['top']+'.rpt');v['timing']={'passed':p.is_file() and m.get('clock_name','core_clock') in p.read_text(),'parasitics':'No extracted SPEF; diagnostic only','signoff_clean':False,'report':str(p)}
        if stage in ('to_drv','to_hold'):
            p=work/'result/to/ito_pass_report.json';data=json.loads(p.read_text());passes=[x for x in data.get('passes',[]) if x.get('phase')==stage[3:]]
            v['native_optimization']={'passed':len(passes)==1 and passes[0].get('status')=='OK' and not passes[0].get('rolled_back'),'passes':passes}
    if any(isinstance(x,dict) and x.get('passed') is False for x in v.values()):v['passed']=False
    write(work/(stage+'-evidence.json'),v)
    if not v['passed']:raise ValueError('Swerv evidence gate failed: '+stage+'; '+str(work/(stage+'-evidence.json')))
    if stage=='drc':prune_duplicate_drc_exports(work)
    return v

def package(state,folder,backend):
    from .task_artifacts import package as basic,ref,write_report
    folder=Path(folder);work=Path(state['accepted_work']);shadow=copy.deepcopy(state)
    shadow['results']['export_def']=state['results']['routed_readback'];shadow['results']['validate']['independent']=state['results']['routed_readback']['geometry']
    out=basic(shadow,folder,backend,final_source=work/'result/routed_readback.def')
    for key,name,src in [('final_gds','final.gds','final.gds'),('final_netlist','final.v','routed_readback.v')]:shutil.copyfile(work/'result'/src,folder/name);out[key]=ref(folder/name)
    a=json.loads((folder/'acceptance.json').read_text());drc=state['results']['drc']['drc_gate']
    a.update(scope='Registered swerv_wrapper research macro fullflow; not manufacturing signoff',hard_macros=3,initial_standard_cells=6777,full_backend_workflow_completed=True,physical_quality_passed=drc['quality_clean'],drc=drc,signoff_clean=False,macro_placement=state['results']['macro_placement']['independent_macro_check'],limitations=backend.manifest()['full_backend_policy'])
    if state['contract'].get('budget_amendment'):
        a['budget_amendment']=state['contract']['budget_amendment']
        a['original_two_hour_budget_passed']=False
        a['reused_stages']=state['contract']['budget_amendment']['reused_stages']
    a['checks']['A7']='Three research hard macros preserved and placed; not foundry-qualified SRAM';write(folder/'acceptance.json',a);write_report(folder)
    p=folder/'report.html';text=p.read_text().replace('iEDA netlist → placement DEF','iEDA swerv_wrapper：netlist → routed DEF / abstract GDS')
    for original in ('当前案例输出完成；整体第一阶段验收仍为部分完成，尚不能证明自动宏布局。','当前双 SRAM 宏布局案例输出完成；整体第一阶段和完整后端验收另列，不由本次案例单独认证。'):
        text=text.replace(original,'本次登记流程含6,777个初始标准单元和3个研究硬宏；宏布局、标准单元布局及后端阶段均须以本次凭据为准。')
    text=text.replace('</h1>','</h1><p>流程执行与版图质量分开验收。研究用 SRAM 抽象模型；不代表制造签核。DRC质量状态：'+('支持规则内无违规' if drc['quality_clean'] else '残余违规，质量未通过')+'</p>',1)
    if state['contract'].get('budget_amendment'):
        b=state['contract']['budget_amendment']
        text=text.replace('</h1>','</h1><p>预算例外：原两小时目标未通过；历史布线超时记录保留。本次复用已验收的前11阶段，按布线'+str(b.get('routing_seconds',10800)//3600)+'小时、续接总计'+str(b.get('continuation_seconds',14400)//3600)+'小时的扩展预算重试。</p>',1)
    p.write_text(text)
    out['acceptance']=ref(folder/'acceptance.json');out['report']=ref(p);return out
