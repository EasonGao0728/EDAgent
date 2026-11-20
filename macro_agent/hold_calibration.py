"""Fixed server-only hold calibration research, separate from production tasks.

Durable named probes/campaigns share the server scheduler. Original inputs and
completed results are never overwritten. Native stages use remote_native.
"""
from pathlib import Path
import json,os,sys,time,subprocess,hashlib,shutil,gzip,re

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/hold-calibration-20261115-v1'
SWERV=ROOT/'cases/ibench/swerv_nangate45'
SHARED=Path('/srv/benchmarks/iBench/benchmarks')
CASES=('gcd','apb4_timer_nangate45_t','s35932_nangate45_t','aes','jpeg','tinyram','bp_fe','swerv_nangate45')

def save(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);q=p.with_suffix('.tmp');q.write_text(json.dumps(v,ensure_ascii=False,indent=2));os.replace(q,p)

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def native(work,reference,body,label='probe',seconds=600,cts=False,holdfix=False,rc_reference=False):
    from .portable_ieda import IMAGE,ENV,BINARY_SHA256
    w=Path(work);ref=Path(reference)
    (w/'logs').mkdir(exist_ok=True);(w/'stage.tcl').write_text('if {[catch {\n'+body+'\nputs "CALIBRATION_OK"\n} message]} {puts stderr $message; exit 1}\nflow_exit\n')
    handles=OUT/'native-handles';handles.mkdir(exist_ok=True);os.environ['AIEDA_NATIVE_HANDLES']=str(handles)
    name='aieda-hold-'+hashlib.sha256(str(w).encode()).hexdigest()[:14]
    args=[sys.executable,'-B','-m','macro_agent.remote_native','run','--rm','--pull=never','--name',name,'--network','none','--cpus','4','--memory','8g','--pids-limit','256','--ulimit','core=0','--ulimit','fsize=268435456','--workdir','/work',
          '--mount',f'type=bind,source={ref},target=/reference,readonly','--mount',f'type=bind,source={w},target=/work']
    if cts:args+=['--mount',f'type=bind,source={ROOT}/environments/ieda-swerv-cts,target=/cts,readonly']
    if sum((bool(cts),bool(holdfix),bool(rc_reference)))>1:raise ValueError('Conflicting tool variants')
    if holdfix:args+=['--mount',f'type=bind,source={ROOT}/environments/ieda-hold-guard-v1,target=/hold,readonly']
    if rc_reference:args+=['--mount',f'type=bind,source={ROOT}/environments/ieda-rc-reference-v1,target=/rc-reference,readonly']
    for k,v in {**ENV,'OMP_NUM_THREADS':'4','OMP_THREAD_LIMIT':'4','OPENBLAS_NUM_THREADS':'1'}.items():args+=['--env',k+'='+v]
    args += [IMAGE,'timeout','--kill-after=5',str(seconds),'/rc-reference/iEDA' if rc_reference else '/hold/iEDA' if holdfix else '/cts/iEDA' if cts else 'iEDA','-script','/work/stage.tcl']
    start=time.time();log=w/'logs/native.log'
    with log.open('w') as f:
        p=subprocess.run(args,stdout=f,stderr=subprocess.STDOUT,timeout=seconds+30)
    text=log.read_text(errors='replace');receipt={'label':label,'returncode':p.returncode,'seconds':time.time()-start,
        'script_sha256':sha(w/'stage.tcl'),'log':str(log),'binary_sha256':sha(ROOT/'environments/ieda-rc-reference-v1/iEDA') if rc_reference else sha(ROOT/'environments/ieda-hold-guard-v1/iEDA') if holdfix else sha(ROOT/'environments/ieda-swerv-cts/iEDA') if cts else BINARY_SHA256,'execution_location':'server',
        'cpu_threads':4,'address_space_gib':8,'deadline_seconds':seconds,'passed':p.returncode==0 and 'CALIBRATION_OK' in text}
    save(w/'native-receipt.json',receipt)
    if not receipt['passed']:raise RuntimeError('NATIVE_PROBE_FAILED: '+str(log))
    return receipt

def probe_api(w):
    body='puts "AVAILABLE_TO [info commands *to*]"\nputs "AVAILABLE_STA [info commands *tim*]"\nputs "AVAILABLE_RC [info commands *parasit*]"\nputs "AVAILABLE_EVAL [info commands *eval*]"'
    return native(w,SWERV,body,seconds=60)

def worker(phase):
    from .remote_platform import install
    from .swerv_screening import active_jobs
    task=install();folder=OUT/phase;receipt=folder/'receipt.json'
    with task.locked(ROOT/'scheduler'):
        r=json.loads(receipt.read_text());r.update(status='running',started_at=time.time(),pid=os.getpid());save(receipt,r)
        try:
            if active_jobs():raise RuntimeError('SERVER_BUSY')
            result=probe_api(folder) if phase=='api' else run_phase(phase,folder)
            r.update(status='completed',result=result)
        except BaseException as e:r.update(status='failed',error=repr(e))
        r['finished_at']=time.time();save(receipt,r)

def checked_path(p,root):
    p=Path(p).resolve();p.relative_to(Path(root).resolve());return p

def copy_source(src,dst,root):
    src=checked_path(src,root);dst=Path(dst);dst.parent.mkdir(parents=True,exist_ok=True)
    if dst.exists():
        if sha(src)!=sha(dst):raise ValueError('SOURCE_CHANGED: '+str(src))
    else:shutil.copyfile(src,dst)
    return {'source':str(src),'copy':str(dst),'sha256':sha(src)}

def prepare_cases(folder):
    from .def_validation import read_def,lef_cells,validate_placement
    from . import pin_metrics
    rows=[]
    for name in CASES:
        row={'case':name,'status':'not_qualified','sources':[],'blockers':[]};rows.append(row)
        try:
            ref=OUT/'references'/name;ref.mkdir(parents=True,exist_ok=True)
            if name=='swerv_nangate45':
                m=json.loads((SWERV/'manifest.json').read_text());origin=json.loads((ROOT/'environments/swerv-quality-review-source.json').read_text())
                for f in [m['tech_lef'],*m['cell_lefs'],*m['libs'],m['sdc']]:row['sources'].append(copy_source(SWERV/f,ref/f,ROOT))
                row['sources'].append(copy_source(origin['drv_def'],ref/'checkpoint.def',ROOT))
                m['checkpoint_stage']='drv';m['clocks']=[{'name':'core_clock','port':'clk','period_ns':2}]
            else:
                base=checked_path(SHARED/'designs'/name,SHARED);hist=checked_path(SHARED/'results/full_2d_20261021'/name,SHARED)
                d=json.loads((hist/'config/design.input.json').read_text());package=json.loads((base/'benchmark_package.json').read_text())
                inp=d['inputs'];m={'case_id':name,'top':d['top'],'tech_lef':'pdk/lef/NangateOpenCellLibrary.tech.lef','cell_lefs':[],'libs':[],
                    'sdc':'sdc/design.sdc','clocks':d.get('clocks',[]),'checkpoint_stage':'placement','core_area_microns':list(map(float,d['floorplan']['core_area'].split()))}
                row['sources'].append(copy_source(base/inp['sdc'],ref/m['sdc'],SHARED))
                row['sources'].append(copy_source(SWERV/m['tech_lef'],ref/m['tech_lef'],ROOT))
                for kind,key,values in [('lef','cell_lefs',inp.get('cells_lefs',[inp['cells_lef']])),('lib','libs',inp.get('libs',[inp['lib']]))]:
                    for value in values:
                        fname=Path(value).name;rel='pdk/'+kind+'/'+fname;m[key].append(rel)
                        src=SWERV/rel if fname.startswith('Nangate') else SHARED/'common/2d_pdk/nangate45'/kind/fname
                        if not src.exists():row['blockers'].append('missing_authorized_library:'+fname);continue
                        row['sources'].append(copy_source(src,ref/rel,ROOT if fname.startswith('Nangate') else SHARED))
                entry=package['stages']['placement']['artifacts']['def'];src=checked_path(base/entry['path'],SHARED)
                if sha(src)!=entry['stored_sha256']:raise ValueError('ARCHIVE_HASH_CHANGED')
                raw=gzip.decompress(src.read_bytes())
                if hashlib.sha256(raw).hexdigest()!=entry['uncompressed_sha256']:raise ValueError('DEF_HASH_CHANGED')
                (ref/'checkpoint.def').write_bytes(raw);row['sources'].append({'source':str(src),'sha256':sha(src),'uncompressed_sha256':entry['uncompressed_sha256']})
                # Public libraries are a new frozen experiment profile, not historical equivalence.
                row['library_profile']='public ORFS standard library plus authorized shared fakeram; historical Liberty differs'
                if name=='bp_fe':row['blockers'].append('macro_libraries_require_authorized_models_before_checkpoint_reuse')
            save(ref/'manifest.json',m);row['reference']=str(ref);row['checkpoint_stage']=m['checkpoint_stage']
            sdc=(ref/m['sdc']).read_text();commands='\n'.join(l for l in sdc.splitlines() if not l.lstrip().startswith('#'))
            row['constraints']={'clocks':m['clocks'],'input_delay_present':bool(re.search(r'\bset_input_delay\b',commands)),
                'output_delay_present':bool(re.search(r'\bset_output_delay\b',commands)),'coverage':'command presence only; not endpoint coverage proof'}
            if not row['constraints']['input_delay_present'] or not row['constraints']['output_delay_present']:
                row['blockers'].append('incomplete_io_timing_constraints')
            if not row['blockers']:
                data=read_def(ref/'checkpoint.def');lefs=[ref/p for p in m['cell_lefs']];cells={}
                for p in lefs:cells.update(lef_cells(p,data['units']))
                missing=sorted({v['master'] for v in data['components'].values()}-set(cells))
                if missing:raise ValueError('UNRESOLVED_MASTERS: '+str(missing))
                libtext='\n'.join((ref/p).read_text() for p in m['libs'])
                libmasters=set(re.findall(r'\bcell\s*\(\s*"?([^\s")]+)',libtext))
                if set(v['master'] for v in data['components'].values())-libmasters:raise ValueError('MISSING_LIBERTY_MASTER')
                row['measurement']=pin_metrics.measure(ref/'checkpoint.def',lefs)
                row['geometry']=validate_placement(data,data,data,lefs,{'core_area_microns':m.get('core_area_microns')})
                if not row['geometry']['passed'] and m['checkpoint_stage']=='placement':row['blockers'].append('archived_placement_geometry_failed')
                row['status']='ready_for_native_qualification' if not row['blockers'] else 'not_qualified'
        except Exception as e:row['blockers'].append(str(e))
        save(folder/'qualification.json',rows)
    return {'rows':rows,'scope':'static qualification; native timing and checkpoint qualification pending'}

def configure(work,ref):
    w=Path(work);ref=Path(ref);m=json.loads((ref/'manifest.json').read_text());w.mkdir(parents=True,exist_ok=True)
    for n in ('config','result/cts','result/to_drv','result/to_hold','result/pl','result/timing','result/report'): (w/n).mkdir(parents=True,exist_ok=True)
    for p in (SWERV/'config').glob('*.json'):
        cfg=json.loads(p.read_text())
        if 'file_path' in cfg:
            f=cfg['file_path'];f['sdc_file']='/reference/'+m['sdc'];f['lib_files']=['/reference/'+x for x in m['libs']];f['lef_files']=['/reference/'+x for x in [m['tech_lef'],*m['cell_lefs']]];f['def_file']='/work/input.def'
        save(w/'config'/p.name,cfg)
    return m

def preamble(m):
    return 'flow_init -config /work/config/flow_config.json\ndb_init -config /work/config/db_default_config.json\n'+f'tech_lef_init -path /reference/{m["tech_lef"]}\nlef_init -path [list '+ ' '.join('/reference/'+x for x in m['cell_lefs'])+']\ndb_init -lib_path [list '+' '.join('/reference/'+x for x in m['libs'])+']\ndb_init -sdc_path /reference/'+m['sdc']+'\ndef_init -path /work/input.def\n'

def timing_probe(folder):
    from .def_io_compat import write_equivalent,equivalent
    ref=OUT/'references/swerv_nangate45';m=configure(folder,ref)
    write_equivalent(ref/'checkpoint.def',folder/'input.def')
    body=preamble(m)+'run_sta -output /work/result/timing\nrun_timing_eval -path /work/result/estimated -eval_output_path /work/result/timing-estimated.json -routing_type FLUTE\ndef_save -path /work/result/readback.def\n'
    r=native(folder,ref,body,'timing-estimate-probe')
    r['geometry_and_connectivity_unchanged']=equivalent(folder/'input.def',folder/'result/readback.def')
    p=folder/'result/timing-estimated.json/timing_result.json';r['estimated']=json.loads(p.read_text()) if p.exists() else None
    return r

def stage(ref,source,w,action,cap=None,seconds=600):
    from .def_io_compat import write_equivalent
    from .def_validation import read_def,validate_placement
    from .aes_transforms import check
    from .swerv_backend import BUFFERS
    w=Path(w);ref=Path(ref)
    if (w/'evidence.json').exists():
        r=json.loads((w/'evidence.json').read_text())
        if not r.get('passed'):raise ValueError('PRESERVED_FAILED_STAGE: '+str(w))
        if r['source']['sha256']!=sha(source) or r['artifact']['sha256']!=sha(r['artifact']['path']):raise ValueError('REUSE_IDENTITY_MISMATCH')
        if not r.get('reused_existing_stage') and (r.get('action')!=action or r.get('cap')!=cap):raise ValueError('REUSE_POLICY_MISMATCH')
        return r
    if (w/'stage.tcl').exists():raise ValueError('PRESERVED_INCOMPLETE_ATTEMPT: '+str(w))
    m=configure(w,ref);before=sha(source);adapt=write_equivalent(source,w/'input.def')
    commands={'cts':'run_cts -config /work/config/cts_default_config.json -work_dir /work/result/cts\ncts_report -path /work/result/cts',
        'drv':'run_to_drv -config /work/config/to_default_config_drv.json','hold':'run_to_hold -config /work/config/to_default_config_hold.json',
        'legal':'run_incremental_flow -config /work/config/pl_default_config.json',
        'measure':'run_sta -output /work/result/timing\nrun_timing_eval -path /work/result/estimated -eval_output_path /work/result/estimated -routing_type FLUTE'}
    if action=='hold':
        if cap not in (.01,.025,.05,.10,.20):raise ValueError('UNREVIEWED_CAP')
        p=w/'config/to_default_config_hold.json';cfg=json.loads(p.read_text());cfg['max_insert_instance_percent']=cap;save(p,cfg)
    if seconds<1 or seconds>600:raise ValueError('INVALID_STAGE_BUDGET')
    r=native(w,ref,preamble(m)+commands[action]+'\ndef_save -path /work/result/raw.def\n',action,seconds=seconds,cts=action=='cts')
    from .swerv_backend import normalize_unplaced
    normalize_unplaced(w/'result/raw.def')
    write_equivalent(w/'result/raw.def',w/'result/output.def',explicit=True)
    # Compare normalized IO representations: syntax adaptation is separately checked.
    write_equivalent(source,w/'before-canonical.def',explicit=True)
    a=read_def(w/'before-canonical.def');b=read_def(w/'result/output.def')
    trans=check(a,b,{'drv':'to_drv','hold':'to_hold','legal':'legalization','measure':'timing'}.get(action,action),BUFFERS)
    r.update(source={'path':str(source),'sha256':before},artifact={'path':str(w/'result/output.def'),'sha256':sha(w/'result/output.def')},
        transformation=trans,io_adaptation=adapt,action=action,cap=cap,source_unchanged=sha(source)==before)
    if action in ('legal','measure'):
        r['geometry']=validate_placement(b,b,b,[ref/p for p in m['cell_lefs']])
    r['passed']=r['passed'] and trans['passed'] and r['source_unchanged']
    save(w/'evidence.json',r)
    if not r['passed']:raise ValueError('STAGE_TRANSFORMATION_FAILED: '+str(w))
    return r

def estimated(w,clocks,initialization='sta_then_flute'):
    import math
    p=Path(w)/'result/estimated/timing_result.json';d=json.loads(p.read_text());rows=d['FLUTE']['clock_timings']
    expected={c['name'] for c in clocks}
    if {x['clock_name'] for x in rows}!=expected or not rows:raise ValueError('CLOCK_COVERAGE_MISMATCH')
    if not all(math.isfinite(x[k]) for x in rows for k in ('setup_wns','setup_tns','hold_wns','hold_tns')):raise ValueError('NONFINITE_TIMING')
    if initialization not in ('sta_then_flute','direct_flute'):raise ValueError('UNKNOWN_TIMING_INITIALIZATION')
    script=Path(w)/'stage.tcl'
    if script.exists():
        text=script.read_text();sta=text.find('run_sta -output');ev=text.find('run_timing_eval ')
        if ev<0 or (initialization=='sta_then_flute' and not 0<=sta<ev) or (initialization=='direct_flute' and sta>=0):
            raise ValueError('TIMING_PROTOCOL_SCRIPT_MISMATCH')
    return {'max_worst_slack_ns':min(x['setup_wns'] for x in rows),'max_tns_ns':sum(x['setup_tns'] for x in rows),
        'min_worst_slack_ns':min(x['hold_wns'] for x in rows),'min_tns_ns':sum(x['hold_tns'] for x in rows),
        'method':('fresh-process run_sta then run_timing_eval FLUTE' if initialization=='sta_then_flute' else 'direct run_timing_eval FLUTE without prior STA; diagnostic only')+', estimated RC; not extracted/signoff',
        'initialization':initialization,
        'clocks':rows,'source':{'path':str(p),'sha256':sha(p)}}

def checkpoints(folder):
    rows=json.loads((OUT/'prepare/qualification.json').read_text());results=[]
    for row in rows:
        item={'case':row['case'],'qualified':False,'status':'blocked','blockers':row['blockers'].copy()};results.append(item)
        try:
            if item['blockers']:continue
            ref=Path(row['reference']);src=ref/'checkpoint.def';w=folder/row['case'];m=json.loads((ref/'manifest.json').read_text())
            item['stages']=[]
            if row['checkpoint_stage']=='placement':
                for action in ('cts','drv'):
                    r=stage(ref,src,w/action,action);item['stages'].append(r);src=Path(r['artifact']['path'])
            item['frozen_checkpoint']={'path':str(src),'sha256':sha(src)}
            # Legalize a copy for comparable measurement; frozen DRV remains untouched.
            r=stage(ref,src,w/'baseline-legal','legal');item['stages'].append(r)
            if not r['geometry']['passed']:raise ValueError('BASELINE_LEGALITY_FAILED')
            src=Path(r['artifact']['path']);r=stage(ref,src,w/'baseline-measure','measure');item['stages'].append(r)
            item['baseline_timing']=estimated(w/'baseline-measure',m['clocks'])
            item['baseline_legal']=str(src);item['qualified']=True;item['status']='qualified_for_preroute_screening'
        except Exception as e:item['blockers'].append(repr(e));item['status']='blocked'
        finally:save(folder/'qualification.json',results)
    return {'cases':results,'scope':'estimated-RC pre-route hold screening only; no routing or production changes'}

def existing_swerv(cap,checkpoint):
    r=json.loads((ROOT/'runs/remote-ba81f7bdbfebcf944da30462/quality-review.json').read_text())
    if r['source']['sha256']!=checkpoint['sha256']:raise ValueError('SWERV_REUSE_CHECKPOINT_CHANGED')
    c=next((x for x in r['candidates'] if x['cap']==cap),None)
    if c is None:return None
    if sha(c['artifact']['path'])!=c['artifact']['sha256']:raise ValueError('SWERV_REUSE_ARTIFACT_CHANGED')
    if not c['geometry_passed'] or not c['connectivity_passed']:raise ValueError('SWERV_REUSE_NOT_VALID')
    return c

def timing_repeat(folder):
    q=json.loads((OUT/'checkpoints/qualification.json').read_text());out=[]
    for name in ('gcd','swerv_nangate45'):
        c=next(x for x in q if x['case']==name)
        if not c['qualified']:raise ValueError('REPEAT_BASELINE_NOT_QUALIFIED')
        ref=OUT/'references'/name;m=json.loads((ref/'manifest.json').read_text());w=folder/name
        r=stage(ref,Path(c['baseline_legal']),w,'measure');t=estimated(w,m['clocks'])
        keys=('max_worst_slack_ns','max_tns_ns','min_worst_slack_ns','min_tns_ns')
        same=all(t[k]==c['baseline_timing'][k] for k in keys)
        out.append({'case':name,'same_at_reported_precision':same,'first':c['baseline_timing'],'repeat':t,'evidence':r})
    save(folder/'comparison.json',out)
    if not all(x['same_at_reported_precision'] for x in out):raise ValueError('TIMING_REPEAT_INCONSISTENT')
    return out

def audit_qualification(folder):
    q=json.loads((OUT/'checkpoints/qualification.json').read_text())
    if len(q)!=8:raise ValueError('INCOMPLETE_QUALIFICATION')
    for c in q:
        if not c['qualified']:continue
        p=OUT/'checkpoints'/c['case']/'baseline-measure/logs/native.log';s=p.read_text(errors='replace')
        missing=sorted(set(re.findall(r'end vertex (\S+) has no clock data',s)))
        pruned=sorted(set(re.findall(r'pruned .*?from net (\S+)',s)))
        c['measurement_audit']={'log':str(p),'log_sha256':sha(p),'unclocked_endpoints':missing,
            'rc_pruned_net_count':len(pruned),'rc_pruned_net_examples':pruned[:20],
            'liberty_out_of_table_warning_count':s.count('val outside table ranges'),
            'rc_model_validation':'cycle-edge pruning not independently validated; diagnostic comparisons only'}
        c['default_calibration_qualified']=False
        c['default_blockers']=['estimated_RC_not_validated_against_reference_or_extraction','endpoint_coverage_not_fully_proven']
        if missing:
            c['qualified']=False;c['status']='blocked';c['blockers'].append('native_STA_unclocked_endpoints:'+str(len(missing)))
        else:c['status']='qualified_for_diagnostic_sweep'
    save(folder/'qualification.json',q)
    return {'cases':q,'production_default_calibration_qualified':False}

def sweep(folder):
    from . import pin_metrics,hold_policy
    q=json.loads((OUT/'audit/qualification.json').read_text())
    if len(q)!=8 or json.loads((OUT/'checkpoints/receipt.json').read_text())['status']!='completed':raise ValueError('EIGHT_CASE_QUALIFICATION_REQUIRED')
    if json.loads((OUT/'timing-repeat/receipt.json').read_text())['status']!='completed':raise ValueError('TIMING_REPEAT_REQUIRED')
    cases=[]
    for case in sorted(q,key=lambda x:x['case']=='jpeg'):
        name=case['case'];result={'case':name,'candidates':[],'status':'blocked','blockers':case['blockers'].copy()};cases.append(result)
        if not case['qualified']:save(folder/'results.json',cases);continue
        ref=OUT/'references'/name;m=json.loads((ref/'manifest.json').read_text());lefs=[ref/p for p in m['cell_lefs']]
        checkpoint=case['frozen_checkpoint'];start=time.monotonic()
        if sha(checkpoint['path'])!=checkpoint['sha256']:raise ValueError('CHECKPOINT_CHANGED')
        for label,cap in [('skip',None),('cap01',.01),('cap025',.025),('cap05',.05),('cap10',.1),('cap20',.2)]:
            w=folder/name/label;c={'label':label,'cap':cap,'hold_executed':cap is not None};result['candidates'].append(c)
            arm_start=time.monotonic()
            def remaining():
                seconds=int(min(600-(time.monotonic()-arm_start),3600-(time.monotonic()-start)))
                if seconds<1:raise TimeoutError('FROZEN_ARM_OR_CASE_BUDGET_EXHAUSTED')
                return seconds
            try:
                if time.monotonic()-start>3000:raise TimeoutError('CASE_3600_SECOND_BUDGET_INSUFFICIENT_FOR_NEXT_ARM')
                src=Path(checkpoint['path']);reuse=existing_swerv(cap,checkpoint) if name=='swerv_nangate45' else None
                if cap is None:
                    src=Path(case['baseline_legal']);t=case['baseline_timing'];c['reused_baseline']=True
                else:
                    if reuse:
                        src=Path(reuse['artifact']['path']);c['reused_hold_and_legalization']=True
                    else:
                        r=stage(ref,src,w/'hold','hold',cap,seconds=remaining());src=Path(r['artifact']['path']);c['hold_evidence']=r
                        r=stage(ref,src,w/'legal','legal',seconds=remaining());src=Path(r['artifact']['path']);c['legal_evidence']=r
                        if not r['geometry']['passed']:raise ValueError('CANDIDATE_LEGALITY_FAILED')
                    r=stage(ref,src,w/'measure','measure',seconds=remaining());c['measurement_evidence']=r;t=estimated(w/'measure',m['clocks'])
                c.update(status='measured',artifact=pin_metrics.ref(src),measurement=pin_metrics.measure(src,lefs),timing=t,
                    geometry_passed=True,connectivity_passed=True,congestion=None,drc=None)
            except Exception as e:c.update(status='failed',error=repr(e));result['blockers'].append(label+': '+repr(e))
            c['seconds_this_campaign']=time.monotonic()-arm_start;save(folder/'results.json',cases)
        valid=[c for c in result['candidates'] if c['status']=='measured']
        if valid and valid[0]['label']=='skip':
            policy={**hold_policy.POLICY,'version':'hold-calibration-estimated-flute-v1','caps':[.01,.025,.05,.1,.2],
                'scope':'uniform FLUTE estimated RC pilot; cost limits unchanged engineering policy, not learned optimum'}
            result['review']=hold_policy.review(valid,policy)
        result['status']='complete' if not result['blockers'] else 'partial';result['seconds']=time.monotonic()-start
        result['checkpoint_unchanged']=sha(checkpoint['path'])==checkpoint['sha256'];save(folder/'results.json',cases)
    return {'cases':cases,'production_modified':False,'full_routing_executed':False}

def run_phase(phase,folder):
    if phase=='prepare':return prepare_cases(folder)
    if phase=='timing':return timing_probe(folder)
    if phase=='checkpoints':return checkpoints(folder)
    if phase=='sweep':return sweep(folder)
    if phase=='timing-repeat':return timing_repeat(folder)
    if phase=='audit':return audit_qualification(folder)
    raise ValueError('Phase not yet registered')

def dispatch(op,phase):
    from .remote_platform import install
    from .swerv_screening import active_jobs
    task=install()
    if phase not in {'api','prepare','timing','checkpoints','timing-repeat','audit','sweep'}:raise ValueError('Unreviewed calibration phase')
    folder=OUT/phase;p=folder/'receipt.json'
    if op=='status':return json.loads(p.read_text()) if p.exists() else {'job_id':OUT.name+'-'+phase,'status':'not_started'}
    if op!='start':raise ValueError('Only fixed start/status supported')
    with task.locked(ROOT/'scheduler'):
        if p.exists():return dispatch('status',phase)
        if active_jobs():raise RuntimeError('SERVER_BUSY')
        folder.mkdir(parents=True,exist_ok=False);r={'job_id':OUT.name+'-'+phase,'phase':phase,'status':'queued','created_at':time.time(),'source_sha256':sha(__file__),'production_modified':False};save(p,r)
        cmd=f'cd {ROOT} && exec /usr/bin/timeout --kill-after=10 3600 python3 -B -m macro_agent.hold_calibration worker {phase}'
        v=subprocess.run(['tmux','new-session','-d','-s',r['job_id'],cmd],capture_output=True,text=True,timeout=10)
        if v.returncode:r.update(status='failed',error=v.stderr);save(p,r)
        return r

if __name__=='__main__':
    if sys.argv[1:2]==['worker']:worker(sys.argv[2])
    else:
        try:
            req=json.load(sys.stdin);print(json.dumps({'ok':True,'value':dispatch(req['operation'],req['phase'])}))
        except Exception as e:print(json.dumps({'ok':False,'error':str(e)}));sys.exit(1)
