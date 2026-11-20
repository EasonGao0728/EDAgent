"""Reviewed, server-only experimental tools. Existing stage artifacts are read-only."""
import json
import os
from pathlib import Path
import re
import subprocess
import time
from . import main_task as task
from .common import digest
from .route_quality import sha, preservation, routing_capabilities, compare_candidates


def registry():
    path=task.ROOT/'environments/decision-benchmark.json'
    return task.load(path) if path.exists() else None


def availability(state):
    r=registry()
    ok=bool(r and state['contract']['case_id']==r['case_id'] and state.get('final_def',{}).get('sha256')==r['parent_def_sha256'])
    return {'available':ok,'scope':'frozen 308-net local neighborhood of one verified AES parent',
            'reason':'matched parent artifact' if ok else 'No reviewed local experiment for this parent; do not fabricate one',
            'not_full_chip':True,'maker_enabled':False}


def verify(state):
    if not availability(state)['available']:raise ValueError('EXPERIMENT_CAPABILITY_GAP')
    r=registry();base=task.ROOT.parent.resolve()
    # Manifest contains only reviewed own-account paths, never a model path.
    for value in r['files'].values():
        p=Path(value['path']).resolve()
        if not p.is_relative_to(base) or not p.is_file() or sha(p)!=value['sha256']:
            raise ValueError('EXPERIMENT_SOURCE_CHANGED: '+p.name)
    task.verify_refs([state['final_def']])
    return r


def evidence(state,folder,kind,cursor,limit):
    from .task_queries import page
    r=verify(state);f=r['files']
    if kind=='local_short':
        obj=task.load(Path(f['local_geometry']['path']))
        rows=[{'type':'short','window_dbu':obj['window_dbu'],'selected_nets':obj['selected_nets'],
               'tracks':obj['tracks'],'rule_source':obj['met1_rule_source'],'limits':obj['scope_limits']}]
        for key in ('nearby_components','pin_and_obstacle_geometry','met1_segments','via_geometry','def_blockages'):
            rows.extend({'type':key,'value':x} for x in obj.get(key,[]))
        return {**page(rows,cursor,limit),'source_ref':f['local_geometry'],
                'parent_def_sha256':r['parent_def_sha256'],'units_dbu_per_micron':obj['units'],
                'scope':'Verified archived local geometry of the same parent, not a new whole-chip analysis'}
    if kind=='prior_comparison':
        obj=task.load(Path(f['prior_receipt']['path']))
        a,c=obj['baseline'],obj['candidate']
        if sha(Path(f['baseline_def']['path']))!=a['artifact_sha256'] or sha(Path(f['prior_def']['path']))!=c['artifact_sha256']:
            raise ValueError('COMPARISON_ARTIFACT_CHANGED')
        return {'scope':availability(state)['scope'],'baseline':a['drc'],'candidate':c['drc'],
                'factor':obj['changed_factor'],'comparison':compare_candidates(a,c),
                'source_ref':f['prior_receipt'],'reused':True,'native_executions':0}
    if kind=='experiment_result':
        paths=sorted((Path(folder)/'decision-experiments').glob('*/receipt.json'))
        return page([task.load(p) for p in paths],cursor,limit)
    raise ValueError('Unknown experiment evidence')


def run(state,folder,plan_id):
    from .remote_platform import is_worker_account
    if not is_worker_account():raise ValueError('SERVER_ONLY_EXPERIMENT')
    r=verify(state);f=r['files'];p=lambda key:Path(f[key]['path'])
    w=Path(folder)/'decision-experiments'/plan_id
    if w.exists():raise ValueError('EXPERIMENT_ALREADY_EXISTS: inspect receipt; never rerun')
    w.mkdir(parents=True);(w/'result/report').mkdir(parents=True)
    route=p('route_script').read_text()
    if route.count('-top_routing_layer met5')!=1:raise ValueError('Template no longer matches reviewed factor')
    (w/'route.tcl').write_text(route.replace('-top_routing_layer met5','-top_routing_layer met3'))
    (w/'check.tcl').write_bytes(p('check_script').read_bytes())
    old=task.load(p('prior_receipt'));baseline=old['baseline']
    receipt={'schema_version':'main-experiment-v1','status':'running','plan_id':plan_id,
             'baseline_reused':True,'production_modified':False,'parent_def_sha256':r['parent_def_sha256'],
             'scope':availability(state)['scope'],'factor':{'name':'top_routing_layer','baseline':'met5','candidate':'met3'},
             'started_at':time.time(),'stages':[],'baseline':baseline}
    save=lambda:task.save(w/'receipt.json',receipt)
    save()
    runtime=task.ROOT.parent/'portable-runtime-v1';ref=task.ROOT/'cases/ibench'/r['case_id']
    env=baseline['controls']['environment']
    try:
        for label,script,seconds in [('route','route.tcl',1800),('check','check.tcl',180)]:
            cmd=['bwrap','--die-with-parent','--unshare-user','--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts',
                 '--ro-bind','/usr','/usr','--ro-bind','/bin','/bin','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64',
                 '--proc','/proc','--dev','/dev','--tmpfs','/tmp','--ro-bind',str(runtime),'/runtime',
                 '--ro-bind',str(ref),'/reference','--ro-bind',str(p('input_def')),'/input.def',
                 '--ro-bind',str(p('router')),'/router','--bind',str(w),'/work','--chdir','/work','--clearenv']
            for key,value in env.items():cmd+=['--setenv',key,str(value)]
            cmd+=['/usr/bin/timeout','--foreground','--kill-after=5',str(seconds),
                  '/runtime/ld-linux-x86-64.so.2','--library-path','/runtime/lib',
                  '/router' if label=='route' else '/runtime/iEDA','-script',script]
            # Limits apply to the native child, not to the persistent service.
            def limits():
                import resource
                os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:4])
                resource.setrlimit(resource.RLIMIT_AS,(8*1024**3,8*1024**3))
                resource.setrlimit(resource.RLIMIT_FSIZE,(1024**3,1024**3))
                resource.setrlimit(resource.RLIMIT_CORE,(0,0))
            started=time.monotonic()
            with (w/(label+'.log')).open('w') as log:
                proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,preexec_fn=limits)
                # Inherit the worker process group, so explicit job cancellation reaches this child.
                try:
                    while proc.poll() is None:
                        if time.monotonic()-started>seconds+15:raise TimeoutError('Experiment stage timeout')
                        if sum(x.stat().st_size for x in w.rglob('*') if x.is_file())>4*1024**3:raise ValueError('Experiment storage budget')
                        time.sleep(1)
                finally:
                    if proc.poll() is None:proc.kill();proc.wait(timeout=10)
            receipt['stages'].append({'stage':label,'returncode':proc.returncode,'seconds':time.monotonic()-started});save()
            if proc.returncode:raise ValueError('Native '+label+' failed: '+str(proc.returncode))
        s=task.load(w/'result/report/violations.json')['summary'];coverage=task.load(w/'result/report/drc_summary.json')
        if not coverage.get('execution_started') or not coverage.get('checked') or coverage.get('skipped') or coverage.get('refused') or coverage['violation_count']!=s['total']:
            raise ValueError('INCOMPLETE_CHECKER_EVIDENCE')
        profile=routing_capabilities((w/'result/rt/rt.log').read_text(),{'max_dr_iterations':1})
        from .def_validation import section
        netrows='\n'.join(section((w/'result/routed.def').read_text(),'NETS'))
        layers=set(re.findall(r'\b(?:ROUTED|NEW)\s+(met\d|li1)\b',netrows))
        observed_top=not (layers-{'met1','met2','met3','li1'}) and not re.search(r'M3M4|M4M5',netrows)
        candidate={**baseline,'artifact_sha256':sha(w/'result/routed.def'),
                   'seconds':receipt['stages'][0]['seconds'],'drc':s,'checked_rules':sorted(coverage['checked']),
                   'structure':preservation(p('input_def'),w/'result/routed.def'),
                   'capabilities':profile,'required_capabilities_verified':profile['passed'] and observed_top,
                   'signal_route_layers':sorted(layers)}
        verify(state)  # Sources, libraries, production output and baseline remain unchanged.
        receipt.update(status='completed',candidate=candidate,comparison=compare_candidates(baseline,candidate),
                       finished_at=time.time(),sources_unchanged=True)
        save()
        return {'scope':receipt['scope'],'factor':receipt['factor'],'baseline_drc':baseline['drc'],
                'candidate_drc':s,'comparison':receipt['comparison'],'receipt_ref':task.file_ref(w/'receipt.json'),
                'native_stages':receipt['stages'],'production_modified':False,'baseline_reused':True}
    except BaseException as exc:
        receipt.update(status='failed',error=str(exc),finished_at=time.time());save();raise
