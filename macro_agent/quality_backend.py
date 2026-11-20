"""Production SWERV pre-route gates; bounded native candidates remain server-only."""
from pathlib import Path
import copy,json,shutil,time
from . import swerv_backend as b
from . import def_io_compat as io,pin_metrics,hold_policy

VERSION='swerv-preroute-quality-v1'
COMPATIBLE={'macro_placement','fanout','placement','export_def','cts','to_drv','legalization','timing'}

def lefs(reference):return [Path(reference)/p for p in b.manifest(reference)['cell_lefs']]

def placement_audit(work,reference):
    w=Path(work);v=pin_metrics.audit(w/'result/placement.def',lefs(reference),w/'result/pl/report/place_summary.json')
    b.write(w/'result/hpwl-audit.json',v)
    if not v['passed']:raise ValueError('HPWL_CONSISTENCY_FAILED: '+str(w/'result/hpwl-audit.json'))
    return v

def hold_candidates(work,reference):
    """Every candidate starts at the same DRV DEF; never runs placement/routing."""
    w=Path(work);ref=Path(reference);m=b.manifest(ref);source=w/'result/to_drv.def'
    source_ref=pin_metrics.ref(source);root=w/'result/hold-candidates';root.mkdir(exist_ok=False)
    started=time.monotonic();candidates=[];native=[];policy=copy.deepcopy(hold_policy.POLICY)
    def native_stage(stage,c):
        original=b.native_deadline
        def bounded(action,directory,now=None):
            remaining=int(policy['campaign_seconds']-(time.monotonic()-started))-10
            if remaining<=0:raise TimeoutError('HOLD_REVIEW_CAMPAIGN_BUDGET')
            return min(original(action,directory,now),policy['max_native_seconds'],remaining)
        b.native_deadline=bounded
        try:return io.execute(stage,c,ref)
        finally:b.native_deadline=original
    for label,cap in [('skip',None),('cap05',.05),('cap10',.10),('cap20',.20)]:
        if time.monotonic()-started>policy['campaign_seconds']-90:raise TimeoutError('HOLD_REVIEW_CAMPAIGN_BUDGET')
        c=root/label;c.mkdir();b.setup(c,ref);shutil.copyfile(source,c/'result/to_drv.def')
        if cap is None:shutil.copyfile(source,c/'result/to_hold.def')
        else:
            p=c/'config/to_default_config_hold.json';cfg=json.loads(p.read_text());cfg['max_insert_instance_percent']=cap;b.write(p,cfg)
            result=native_stage('to_hold',c);native.append({'candidate':label,'stage':'to_hold','evidence':result})
        for stage in ('legalization','timing'):
            if stage=='timing':shutil.copyfile(c/'result/legalization.def',c/'result/filler.def')
            result=native_stage(stage,c);native.append({'candidate':label,'stage':stage,'evidence':result})
        legal=json.loads((c/'legalization-evidence.json').read_text())
        report=c/'result/timing'/(m['top']+'.rpt')
        value={'label':label,'cap':cap,'hold_executed':cap is not None,
               'measurement':pin_metrics.measure(c/'result/legalization.def',lefs(ref)),
               'timing':hold_policy.timing(report.read_text()),'timing_source':pin_metrics.ref(report),
               'geometry_passed':legal['geometry']['passed'],'connectivity_passed':legal['transformation']['passed'],
               'artifact':pin_metrics.ref(c/'result/legalization.def')}
        if cap is not None:value['connectivity_passed'] &= native[-3]['evidence']['transformation']['passed']
        candidates.append(value);review=hold_policy.review(candidates,policy)
        review.update(source=source_ref,native_stages=native,seconds=time.monotonic()-started,complete=False,
                      native_routing_executed=False,execution_location='server')
        b.write(w/'result/hold-review.json',review)
        # Caps are upper limits, not insertion targets. Stop when the minimum
        # tested cost candidate meets all hard timing/physical/cost criteria.
        if review['passed']:break
    if pin_metrics.ref(source)!=source_ref:raise ValueError('HOLD_SOURCE_CHANGED')
    review.update(complete=True,source_unchanged=True,seconds=time.monotonic()-started)
    b.write(w/'result/hold-review.json',review)
    return review

def execute(stage,work,reference):
    w=Path(work);ref=Path(reference)
    if stage=='to_hold':
        review=hold_candidates(w,ref)
        if not review['passed']:
            b.write(w/'to_hold-evidence.json',{'passed':False,'native_success_not_quality_acceptance':True,'hold_review':review})
            raise ValueError('HOLD_COST_REVIEW_REQUIRED: candidates preserved; no timing-clean cost-bounded candidate; '+str(w/'result/hold-review.json'))
        c=w/'result/hold-candidates'/review['selected']
        shutil.copyfile(c/'result/legalization.def',w/'result/to_hold.def')
        shutil.copyfile(c/'result/legalization.v',w/'result/to_hold.v')
        value={'stage':stage,'passed':True,'artifact':str(w/'result/to_hold.def'),'artifact_sha256':b.sha(w/'result/to_hold.def'),
               'seconds':review['seconds'],'hold_cost_review':review,'native_routing_executed':False}
        review['accepted_def_sha256']=value['artifact_sha256'];b.write(w/'result/hold-review.json',review)
        b.write(w/'to_hold-evidence.json',value);return value
    if stage=='routing':
        gate_routing(w)
    value=io.execute(stage,w,ref) if stage in COMPATIBLE else b.execute(stage,w,ref)
    if stage=='placement':
        value['hpwl_consistency']=placement_audit(w,ref);b.write(w/'placement-evidence.json',value)
    if stage=='validate':value['hpwl_consistency']=placement_audit(w,ref)
    return value

def gate_routing(work):
    w=Path(work);hp=w/'result/hpwl-audit.json';hold=w/'result/hold-review.json'
    if not hp.exists() or not hold.exists():raise ValueError('PRE_ROUTE_REVIEW_MISSING')
    a=json.loads(hp.read_text());h=json.loads(hold.read_text())
    if not a.get('passed') or not h.get('routing_allowed') or not h.get('complete'):raise ValueError('PRE_ROUTE_QUALITY_BLOCKED')
    if a['measurement']['sources'][0]['sha256']!=b.sha(w/'result/placement.def'):raise ValueError('HPWL_AUDIT_STALE')
    if h.get('accepted_def_sha256')!=b.sha(w/'result/to_hold.def'):raise ValueError('HOLD_REVIEW_STALE')
    if h['policy']!=hold_policy.POLICY:raise ValueError('HOLD_POLICY_CHANGED')
    return {'passed':True,'scope':'pre-route only; post-route quality is still required'}

def observation(state):
    if not state.get('contract',{}).get('case_manifest',{}).get('pre_route_quality_policy'):return {'enabled':False}
    roots=[Path(state['accepted_work'])] if state.get('accepted_work') else []
    failures=[e for e in state.get('events',[]) if e.get('action')=='to_hold' and e.get('status')=='failed' and e.get('work')]
    if failures:roots.insert(0,Path(failures[-1]['work']))
    for w in roots:
        p=w/'result/hold-review.json'
        if p.exists():
            r=json.loads(p.read_text())
            return {'enabled':True,'status':r['status'],'routing_allowed':r['routing_allowed'],
                    'selected':r['selected'],'source':pin_metrics.ref(p),
                    'reasons':{c['label']:c['rejection_reasons'] for c in r['candidates']}}
    return {'enabled':True,'status':'pending_stage_measurement','routing_allowed':False}
