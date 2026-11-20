"""Bounded main-Agent via ECO: native proposal, spatially restricted patch, reject-safe validation.

This is a fixed tool adapter, not code generation. Production artifacts are never overwritten.
"""
import json, os, re, subprocess, time
from pathlib import Path
from collections import Counter
from html import escape
from . import main_task as task
from .route_quality import sha, preservation
from .drc_counts import marker_stream, reconcile, AUDITED_BINARY
from .def_validation import section

VERSION='local-via-eco-v3-fixed-template-trial'
WORK='local-eco-v3'
PLAN='local-eco-plan-v3.json'
OFFICIAL_SHA='6e50227803fcf3162d64f6bfa739cf63521c72c63aa44b07d16121fbc25f36ea'
PARENT='3b00977c7654b5348d6c95d46b3f3db9a604720ddcf081a5a0ac50bd6857e533'
VIA=re.compile(r'\b(?:ROUTED|NEW)\s+(\w+)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(?!NEW\b)([A-Za-z_][\w.-]*)(?=\s|;|$)')

def validate_parent(state,folder):
    if os.name!='posix' or os.getuid()!=1015:raise ValueError('SERVER_ONLY_LOCAL_ECO')
    if state['status']!='target_met' or state['contract']['case_id']!='aes_sky130_t' or state.get('final_def',{}).get('sha256')!=PARENT:
        raise ValueError('LOCAL_ECO_NOT_QUALIFIED_FOR_PARENT')
    task.verify_refs([state['final_def']])
    from .decision_experiments import verify
    verify(state)  # Pin baseline PDK, checker libraries and configuration, not just the executable.
    r=state['results']['drc']
    if r['artifact_sha256']!=PARENT or r['binary_sha256']!=AUDITED_BINARY:raise ValueError('BASELINE_CHECKER_MISMATCH')
    task.verify_refs(r['artifact_refs'])
    binary=task.ROOT.parent/'portable-runtime-v1/iEDA'
    if sha(binary)!=AUDITED_BINARY:raise ValueError('ECO_BINARY_CHANGED')
    return Path(r['artifact']).parent/'report/violations.json'

def box(m):
    b=m.get('bbox');u=m.get('units',{}).get('dbu_per_micron')
    if not isinstance(b,list) or len(b)!=4 or u!=1000 or any(type(v) not in (int,float) for v in b):return None
    return b

def overlap(a,b):return a[0]<=b[2] and a[2]>=b[0] and a[1]<=b[3] and a[3]>=b[1]

def inspect(state,folder):
    source=validate_parent(state,folder);target=Path(folder)/'local-eco-diagnosis-v3.json'
    if target.exists():
        d=task.load(target)
        if d['parent_def_sha256']!=PARENT or d['source']['sha256']!=sha(source):raise ValueError('LOCAL_DIAGNOSIS_CHANGED')
        return d
    tiles=Counter();total=0;header=None
    for kind,m in marker_stream(source):
        if kind=='header':header=m;continue
        total+=1;b=box(m)
        if b and m.get('type') in ('cut_short','same_layer_cut_spacing','nonsufficient_metal_overlap'):
            tiles[(int((b[0]+b[2])//20000),int((b[1]+b[3])//20000))]+=1
    if not tiles or total!=header['summary']['total']:raise ValueError('NO_RELIABLE_VIA_HOTSPOT')
    tile,count=sorted(tiles.items(),key=lambda x:(-x[1],x[0]))[0];region=[tile[0]*10000,tile[1]*10000,(tile[0]+1)*10000,(tile[1]+1)*10000]
    rows=[];regional=[];rules=Counter();nets=set()
    for kind,m in marker_stream(source):
        if kind=='marker' and box(m) and overlap(box(m),region):
            regional.append(m)
            rules[m['type']]+=1;nets.update(m.get('net_ids') or [])
            if len(rows)<12:rows.append(m)
    d={'schema_version':VERSION,'parent_def_sha256':PARENT,'source':task.file_ref(source),'region_dbu':region,'units_dbu_per_micron':1000,
       'selection':'highest 10um via-rule marker-center bin; deterministic before native proposal','via_related_markers_in_bin':count,
       'regional_rules_intersecting':dict(rules),'regional_net_count':len(nets),'examples':rows,
       'observed':'Actual native DRC markers identify a via-related hotspot; root cause remains a hypothesis until geometry and candidate checks.',
       'hypothesis':'Native shape-based via master substitution may reduce local enclosure footprints or conflicts; not a general short remover.',
       'capability':{'command':'eco_repair_via -type shape','producer_sha256':OFFICIAL_SHA,'official_source_commit':'65c39fd28aa0dc0cdd56325df07f6e440069061b','checker_sha256':AUDITED_BINARY,'snapshot_interface':'legacy call rejected: requires structured shape request and ECO oracle; failed evidence retained in local-eco','native_bbox_parameter':False,'strategy':'generate with existing pinned official build on isolated full copy, copy only eligible via-name substitutions inside region; never adopt global output','pattern':'not admitted; official pinned source is empty'},
       'budget':{'candidates':1,'cpu_threads':4,'address_space_gib':8,'eco_seconds':180,'drc_seconds':180,'storage_bytes':2*1024**3},
       'unknowns':['electrical connectivity signoff','timing effect','full PDK rule coverage'],'maker_enabled':False}
    from .local_template_trial import select_template
    before=Path(state['final_def']['path']).read_text()
    tech=(task.ROOT/'cases/ibench/aes_sky130_t/pdk/lef/sky130_fd_sc_hd.tlef').read_text()
    d['template_trial']=select_template(via_map(before),via_shapes(tech,before),regional,region)
    if not d['template_trial']:raise ValueError('NO_QUALIFIED_TEMPLATE_TRIAL')
    prior=Path(folder)/'local-eco-v2/receipt.json'
    previous=task.load(prior)
    if previous.get('status')!='rejected' or previous.get('change_count')!=0 or previous.get('reasons')!=['no_eligible_local_via_change']:raise ValueError('NATIVE_NOOP_EVIDENCE_REQUIRED')
    d['native_noop_evidence']=task.file_ref(prior)
    d['capability']['active_action']='fixed_pdk_via_template_trial; not a native iECO command'
    d['capability']['strategy']='single PDK via-template substitution selected from existing marker geometry; same cut shapes and coordinates; no wire edits; original iDRC full-chip check'
    d['hypothesis']='A different existing PDK metal enclosure may avoid selected marker boxes; this proxy does not prove fewer DRC violations or electrical continuity.'
    d['budget']['eco_seconds']=0
    d['budget']['history']='one failed snapshot interface call, one official no-op; first and only changed candidate to be checked'
    d['evidence_id']=task.digest(d);task.save(target,d);return d

def plan(state,folder,req):
    d=inspect(state,folder)
    if req.get('evidence_id')!=d['evidence_id']:raise ValueError('CURRENT_LOCAL_DIAGNOSIS_REQUIRED')
    reason=req.get('reason','')
    if not isinstance(reason,str) or not 1<=len(reason)<=2000:raise ValueError('REASON_REQUIRED')
    p=Path(folder)/PLAN
    if p.exists():return task.load(p)
    old=Path(folder)/'local-eco/receipt.json'
    previous=task.load(old) if old.exists() else None
    if previous and (previous.get('status')!='failed' or previous.get('candidate') or 'LOCAL_NATIVE_FAILED' not in previous.get('error','')):raise ValueError('PREVIOUS_CANDIDATE_NOT_ELIGIBLE_FOR_INTERFACE_RECOVERY')
    value={'plan_id':'local-'+d['evidence_id'][:24],'state_id':task.state_id(state),'evidence_id':d['evidence_id'],
           'reason':reason,'status':'planned','created_at':time.time(),'implementation_sha256':sha(Path(__file__)),
           'selector_sha256':sha(Path(__file__).with_name('local_template_trial.py')),
           'budget':d['budget'],'production_modified':False,'prior_interface_failure':task.file_ref(old) if previous else None,'prior_native_noop':d['native_noop_evidence'],'budget_scope':'one changed candidate evaluation after preserved interface failure and native no-op; no repeat candidate generation or EDA retry'}
    task.save(p,value);return value

def selected(state,folder,plan_id):
    p=task.load(Path(folder)/PLAN)
    if p['plan_id']!=plan_id or p['state_id']!=task.state_id(state):raise ValueError('STALE_LOCAL_PLAN')
    if p['implementation_sha256']!=sha(Path(__file__)):raise ValueError('LOCAL_IMPLEMENTATION_CHANGED')
    if p['selector_sha256']!=sha(Path(__file__).with_name('local_template_trial.py')):raise ValueError('LOCAL_SELECTOR_CHANGED')
    validate_parent(state,folder)
    return p

def via_map(text):
    result={}
    for row in section(text,'NETS'):
        net=row.split()[0]
        for m in VIA.finditer(row):
            k=(net,m[1],int(m[2]),int(m[3]))
            if k in result and result[k]!=m[4]:raise ValueError('AMBIGUOUS_VIA_AT_COORDINATE')
            result[k]=m[4]
    return result

def local_patch(before,proposal,region,known_vias):
    old,new=via_map(before),proposal if isinstance(proposal,dict) else via_map(proposal);changes=[]
    # Keep original bytes everywhere except admitted via names. Native global output is never adopted.
    def net_replace(match):
        row=match[0];net=re.match(r'\s*-\s+(\S+)',row)[1]
        def replace(m):
            key=(net,m[1],int(m[2]),int(m[3]));name=new.get(key);x,y=key[2:]
            if name is None or name==m[4] or name not in known_vias:return m[0]
            old_shape=known_vias.get(m[4]);new_shape=known_vias[name]
            if not old_shape or set(old_shape)!=set(new_shape):return m[0]
            for shape in (old_shape,new_shape):
                for rects in shape.values():
                    for b in rects:
                        if not(region[0]<=x+b[0]<=x+b[2]<=region[2] and region[1]<=y+b[1]<=y+b[3]<=region[3]):return m[0]
            changes.append({'net':net,'layer':m[1],'xy':[x,y],'before':m[4],'after':name,'before_shapes':old_shape,'after_shapes':new_shape})
            return m[0][:m.start(4)-m.start()]+name+m[0][m.end(4)-m.start():]
        return VIA.sub(replace,row)
    sec=re.search(r'^NETS\s+\d+\s*;.*?^END NETS\s*$',before,re.M|re.S)
    if sec is None:raise ValueError('NETS_REQUIRED')
    patched=re.sub(r'^\s*-\s+[^;]+;',net_replace,sec[0],flags=re.M)
    return before[:sec.start()]+patched+before[sec.end():],changes

def via_shapes(tech,original):
    from decimal import Decimal
    result={}
    for m in re.finditer(r'^VIA\s+(\S+)[^\n]*\n(.*?)^END\s+\1\s*$',tech,re.M|re.S):
        shape={}
        for l in re.finditer(r'LAYER\s+(\S+)\s*;(.*?)(?=LAYER\s|$)',m[2],re.S):
            rects=[[int(Decimal(v)*1000) for v in r.split()] for r in re.findall(r'RECT\s+([^;]+);',l[2])]
            if any(len(b)!=4 for b in rects):raise ValueError('UNSUPPORTED_VIA_SHAPE')
            shape[l[1]]=rects
        if len(shape)==3 and all(shape.values()):result[m[1]]=shape
    for row in section(original,'VIAS'):
        shape={}
        for m in re.finditer(r'\+\s+RECT\s+(\S+)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)',row):shape.setdefault(m[1],[]).append(list(map(int,m.groups()[1:])))
        if len(shape)==3:result[row.split()[0]]=shape
    return result

def native(work,input_def,body,seconds,official=False):
    runtime=task.ROOT.parent/'portable-runtime-v1';ref=task.ROOT/'cases/ibench/aes_sky130_t'
    work.mkdir();(work/'result/report').mkdir(parents=True);(work/'result/drc').mkdir()
    init='flow_init -config /reference/config/flow_config.json\ndb_init -config /reference/config/db_default_config.json\ntech_lef_init -path /reference/pdk/lef/sky130_fd_sc_hd.tlef\nlef_init -path {/reference/pdk/lef/sky130_fd_sc_hd_merged.lef}\ndef_init -path /input.def\n'
    (work/'run.tcl').write_text(init+body+'\nputs LOCAL_ECO_STAGE_COMPLETE\nflow_exit\n')
    cmd=['bwrap','--die-with-parent','--unshare-user','--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts','--ro-bind','/usr','/usr','--ro-bind','/bin','/bin','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64','--proc','/proc','--dev','/dev','--tmpfs','/tmp','--ro-bind',str(runtime),'/runtime','--ro-bind',str(ref),'/reference','--ro-bind',str(input_def),'/input.def','--bind',str(work),'/work','--chdir','/work','--clearenv']
    for k,v in {'PATH':'/usr/bin:/bin','TCL_LIBRARY':'/runtime/tcl8.6','HOME':'/tmp','RESULT_DIR':'result','OMP_NUM_THREADS':'4','OMP_THREAD_LIMIT':'4'}.items():cmd+=['--setenv',k,v]
    binary=task.ROOT.parent/'ieda-rootcause-20261112/bin/iEDA' if official else runtime/'iEDA'
    binary_hash=sha(binary)
    if binary_hash!=(OFFICIAL_SHA if official else AUDITED_BINARY):raise ValueError('NATIVE_BINARY_CHANGED')
    if official:cmd+=['--ro-bind',str(binary),'/ieda']
    cmd+=['/usr/bin/timeout','--foreground','--kill-after=5',str(seconds)]
    cmd+=(['/ieda'] if official else ['/runtime/ld-linux-x86-64.so.2','--library-path','/runtime/lib','/runtime/iEDA'])+['-script','run.tcl']
    def limits():
        import resource
        os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:4]);resource.setrlimit(resource.RLIMIT_AS,(8*1024**3,8*1024**3));resource.setrlimit(resource.RLIMIT_FSIZE,(1024**3,1024**3));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    start=time.monotonic()
    with (work/'native.log').open('w') as log:
        p=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,preexec_fn=limits)
        try:
            while p.poll() is None:
                if time.monotonic()-start>seconds+10:raise TimeoutError('LOCAL_ECO_NATIVE_TIMEOUT')
                if sum(x.stat().st_size for x in work.parent.rglob('*') if x.is_file())>2*1024**3:raise ValueError('LOCAL_ECO_STORAGE_LIMIT')
                time.sleep(.5)
        finally:
            if p.poll() is None:p.kill();p.wait()
    (work/'logs').mkdir(exist_ok=True)
    (work/'logs/drc.log').write_bytes((work/'native.log').read_bytes())
    result={'returncode':p.returncode,'seconds':time.monotonic()-start,'binary_sha256':binary_hash,'log':task.file_ref(work/'native.log'),'script':task.file_ref(work/'run.tcl')}
    if p.returncode or 'LOCAL_ECO_STAGE_COMPLETE' not in (work/'native.log').read_text():raise ValueError('LOCAL_NATIVE_FAILED:'+json.dumps(result))
    return result

def marker_counts(source,region):
    header={};rules=Counter();local=Counter();outside=set();count=0
    for kind,m in marker_stream(source):
        if kind=='header':header=m;continue
        count+=1;rules[m['type']]+=1
        if box(m) and overlap(box(m),region):local[m['type']]+=1
        else:outside.add(m.get('canonical_key') or m['id'])
    if count!=header['count'] or count!=header['summary']['total'] or dict(rules)!=header['summary']['by_type']:raise ValueError('MARKER_COUNT_CONFLICT')
    return {'total':count,'rules':dict(rules),'local':dict(local),'coverage':header.get('coverage')},outside

def run(state,folder,plan_id):
    folder=Path(folder);p=selected(state,folder,plan_id)
    if p['status']!='planned':raise ValueError('LOCAL_ALREADY_ATTEMPTED')
    w=folder/WORK;w.mkdir();p['status']='running';task.save(folder/PLAN,p)
    source=validate_parent(state,folder);d=inspect(state,folder);parent=Path(state['final_def']['path']);parent_task_sha=sha(folder/'task.json')
    receipt={'schema_version':VERSION,'status':'running','plan_id':plan_id,'diagnosis':d,'production_modified':False,'native_stages_replayed':False,'steps':[],'parent_task_sha256':parent_task_sha,'parent_def_sha256':PARENT,'prior_interface_failure':p.get('prior_interface_failure'),'prior_native_noop':p['prior_native_noop'],'budget_scope':p['budget_scope']}
    save=lambda:task.save(w/'receipt.json',receipt)
    save()
    try:
        before=parent.read_text();choice=d['template_trial'];after={tuple(choice['key']):choice['after']}
        tech=(task.ROOT/'cases/ibench/aes_sky130_t/pdk/lef/sky130_fd_sc_hd.tlef').read_text()
        candidate,changes=local_patch(before,after,d['region_dbu'],via_shapes(tech,before));out=w/'candidate.def';out.write_text(candidate)
        if len(changes)!=1:raise ValueError('SINGLE_TEMPLATE_SUBSTITUTION_REQUIRED')
        receipt.update(proposal_source='fixed PDK-template adapter, not native iECO or Algorithm Agent',candidate=task.file_ref(out),changes=changes,change_count=len(changes),outside_region_geometry_changed=False,
                       proposal_scope='single via-template name inside frozen hotspot; cut geometry unchanged; every other original text byte retained',structure=preservation(parent,out));save()
        if not changes:
            validate_parent(state,folder)
            receipt.update(status='rejected',reasons=['no_eligible_local_via_change'],parent_unchanged=sha(folder/'task.json')==parent_task_sha)
            return finish(folder,p,receipt)
        receipt['steps'].append({'stage':'candidate_full_chip_drc',**native(w/'check',out,'run_drc -config /reference/config/drc_default_config.json -path result/report/drc.rpt\ndef_save -path /work/result/readback.def',180)});save()
        report=w/'check/result/report';counts=reconcile(task.load(report/'drc_summary.json'),report,AUDITED_BINARY)
        a,oa=marker_counts(source,d['region_dbu']);b,ob=marker_counts(report/'violations.json',d['region_dbu'])
        regressions=[k for k in set(a['rules'])|set(b['rules']) if b['rules'].get(k,0)>a['rules'].get(k,0)]
        # A changed via still requires connectivity/timing proof; never silently promote a candidate.
        receipt.update(baseline=a,candidate_quality=b,count_reconciliation=counts,regressed_rules=regressions,new_outside_markers=len(ob-oa),
          local_delta=sum(b['local'].values())-sum(a['local'].values()),global_delta=b['total']-a['total'],
          status='rejected',reasons=['electrical_connectivity_unverified','routed_timing_unverified'],automatic_promotion=False)
        if regressions:receipt['reasons'].append('rule_regression')
        if not counts['passed']:receipt['reasons'].append('count_reconciliation_failed')
        if ob-oa:receipt['reasons'].append('new_markers_outside_region')
        if sum(b['local'].values())>=sum(a['local'].values()):receipt['reasons'].append('no_local_improvement')
        if not receipt['structure']['passed']:receipt['reasons'].append('structural_preservation_failed')
        if a['coverage']!=b['coverage']:receipt['reasons'].append('coverage_mismatch')
        validate_parent(state,folder)
        if sha(folder/'task.json')!=parent_task_sha:raise ValueError('PARENT_STATE_CHANGED')
        receipt['parent_unchanged']=True
        return finish(folder,p,receipt)
    except BaseException as e:
        receipt.update(status='failed',error=str(e),production_modified=False);finish(folder,p,receipt);raise

def finish(folder,plan,receipt):
    receipt['finished_at']=time.time();task.save(folder/WORK/'receipt.json',receipt)
    plan['status']=receipt['status'];task.save(folder/PLAN,plan)
    task.save(folder/'local-repair-report.json',receipt)
    from .local_repair_report import render
    text=render(receipt)
    (folder/'local-repair-report.html').write_text(text,encoding='utf-8')
    return {'status':receipt['status'],'change_count':receipt.get('change_count',0),'baseline':receipt.get('baseline'),'candidate_quality':receipt.get('candidate_quality'),'local_delta':receipt.get('local_delta'),'global_delta':receipt.get('global_delta'),'new_outside_markers':receipt.get('new_outside_markers'),'regressed_rules':receipt.get('regressed_rules'),'reasons':receipt.get('reasons',[]),'production_modified':False,'report':task.file_ref(folder/'local-repair-report.html'),'download_via':'mp_task_download'}

def status(folder):
    folder=Path(folder);p=folder/PLAN
    value={'plan':task.load(p) if p.exists() else None,'maker_enabled':False}
    r=folder/WORK/'receipt.json'
    if r.exists():
        receipt=task.load(r);value['result']={k:receipt.get(k) for k in ('status','change_count','baseline','candidate_quality','local_delta','global_delta','new_outside_markers','regressed_rules','count_reconciliation','structure','reasons','production_modified','parent_unchanged','error')}
    return value
