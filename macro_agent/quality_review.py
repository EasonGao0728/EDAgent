"""Main-Agent quality tool: inspect -> bounded server review -> accept or preserve.

The registered historical candidate is explicit, hashed and never promoted into
the old completed task. Future tasks use their own accepted DRV checkpoint.
"""
from pathlib import Path
import hashlib,html,json,shutil,time
from . import main_task as task,pin_metrics,hold_policy,quality_backend
ROOT=Path(__file__).resolve().parents[1]

def sources(state,folder):
    if state['contract']['case_id']!='swerv_nangate45':raise ValueError('QUALITY_PROFILE_NOT_QUALIFIED_FOR_CASE')
    if state['contract'].get('case_manifest',{}).get('pre_route_quality_policy') and 'to_drv' in state['results']:
        a=state['results']['placement'];b=state['results']['to_drv'];task.verify_refs(a['artifact_refs']+b['artifact_refs'])
        summary=Path(a['artifact']).parents[1]/'result/pl/report/place_summary.json'
        v={'case_id':'swerv_nangate45','scope':'current accepted DRV checkpoint',
           'placement_def':a['artifact'],'placement_summary':str(summary),'drv_def':b['artifact'],
           'sources':[pin_metrics.ref(Path(a['artifact'])),pin_metrics.ref(summary),pin_metrics.ref(Path(b['artifact']))]}
    else:
        v=task.load(ROOT/'environments/swerv-quality-review-source.json')
        if Path(folder).name!=v['parent_task_id'] or pin_metrics.ref(Path(folder)/'final.def')['sha256']!=v['parent_final_sha256']:
            raise ValueError('NO_QUALIFIED_REVIEW_CHECKPOINT')
    task.verify_refs(v['sources']);return v

def reference(state):return Path(state['contract'].get('input_root') or ROOT/'cases/ibench/swerv_nangate45')

def inspect(state,folder):
    f=Path(folder);src=sources(state,f);ref=reference(state)
    audit=pin_metrics.audit(src['placement_def'],quality_backend.lefs(ref),src['placement_summary'])
    value={'source':src,'hpwl_consistency':audit,'policy':hold_policy.POLICY,
        'implementation':[pin_metrics.ref(Path(__file__).with_name(n+'.py')) for n in ('quality_review','quality_backend','pin_metrics','hold_policy','def_io_compat')],
        'planned_native_stages':['baseline legalization and diagnostic STA','up to 3 hold/legalization/STA candidates'],
        'routing_executed':False,'new_placement_executed':False,'production_promotion_allowed':False}
    value['evidence_id']=task.digest(value)
    task.save(f/'quality-review-evidence.json',value)
    control=f/'quality-review-control.json'
    if not control.exists():task.save(control,{'created_at':time.time(),'model_calls':0,'model_call_limit':20,'wall_seconds':3600,'scope':'new explicitly requested quality review; original budgets unchanged'})
    done=f/'quality-review.json'
    if not done.exists() and state['contract'].get('case_manifest',{}).get('pre_route_quality_policy'):
        observed=quality_backend.observation(state)
        if observed.get('source'):
            task.verify_refs([observed['source']]);previous=task.load(Path(observed['source']['path']))
            if previous.get('complete'):
                previous.update(hpwl_consistency=audit,source_scope=src['scope'],production_replaced=False)
                task.save(done,previous);report(f,previous)
    if done.exists():value['review']=task.load(done)
    value['can_execute']=audit['passed'] and not done.exists()
    value['execution_location']='server'
    return compact(value)

def compact(v):
    a=v.get('hpwl_consistency',{});r=v.get('review',v)
    return {'evidence_id':v.get('evidence_id'),'source_scope':v.get('source',{}).get('scope') or r.get('source_scope'),
        'can_execute':v.get('can_execute',False),'execution_location':'server',
        'hpwl_consistency':{k:a.get(k) for k in ('passed','native_dbu','independent_dbu','difference_dbu','tolerance_dbu')},
        'policy':v.get('policy',r.get('policy')),'status':r.get('status','ready'),
        'selected':r.get('selected'),'routing_allowed':r.get('routing_allowed',False),'error':r.get('error'),
        'candidates':[{k:c.get(k) for k in ('label','cap','added_buffers','area_growth','net_growth','hpwl_change_um','timing','marginal','rejection_reasons','eligible')} for c in r.get('candidates',[])],
        'unknowns':['post-route congestion','post-route DRC','extracted parasitic timing'],
        'production_replaced':False,'routing_executed':False,'report_available':bool(r.get('complete') or r.get('error'))}

def validate(state,folder,evidence_id):
    v=inspect(state,folder)
    if v['evidence_id']!=evidence_id:raise ValueError('STALE_QUALITY_EVIDENCE')
    if not v['can_execute']:raise ValueError('QUALITY_REVIEW_NOT_ELIGIBLE: inspect existing result or metric conflict')
    return task.load(Path(folder)/'quality-review-evidence.json')

def run(state,folder,req):
    f=Path(folder);v=validate(state,f,req['evidence_id']);before=pin_metrics.ref(f/'task.json');original=pin_metrics.ref(f/'final.def') if (f/'final.def').exists() else None
    w=f/'quality-candidates'/('review-'+hashlib.sha256(req['action_id'].encode()).hexdigest()[:16])
    w.mkdir(parents=True,exist_ok=False);ref=reference(state)
    quality_backend.b.setup(w,ref)
    shutil.copyfile(v['source']['drv_def'],w/'result/to_drv.def')
    task.save(f/'quality-review.json',{'status':'running','source':v['source'],'work':str(w),'evidence_id':v['evidence_id'],'started_at':time.time()})
    try:
        review=quality_backend.hold_candidates(w,ref)
        review.update(hpwl_consistency=v['hpwl_consistency'],source_scope=v['source']['scope'],work=str(w),
            baseline_preserved=pin_metrics.ref(f/'task.json')==before and (not original or pin_metrics.ref(f/'final.def')==original),
            production_promotion_allowed=False,production_replaced=False,evidence_id=v['evidence_id'])
        if not review['baseline_preserved']:raise ValueError('PRODUCTION_ARTIFACT_CHANGED')
        task.save(f/'quality-review.json',review);report(f,review)
        return review
    except BaseException as exc:
        result={'status':'failed','error':str(exc),'source':v['source'],'work':str(w),'production_replaced':False,
                'candidate_evidence':str(w/'result/hold-review.json'),'evidence_id':v['evidence_id']}
        task.save(f/'quality-review.json',result);report(f,result);raise

def report(folder,r):
    f=Path(folder);rows=[]
    for c in r.get('candidates',[]):
        m=c['measurement'];t=c['timing'];g=c.get('marginal',{})
        vals=[c['label'],c['added_buffers'],f'{m["standard_cell_area_um2"]:.3f}',m['nets'],f'{m["hpwl_um"]:.3f}',
            t['max_worst_slack_ns'],t['min_worst_slack_ns'],t['min_tns_ns'],g.get('hold_tns_gain_ns','—'),', '.join(c['rejection_reasons']) or '通过预布线门禁']
        rows.append('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in vals)+'</tr>')
    heads=['候选','新增缓冲器','标准单元面积 µm²','网络数','HPWL µm','setup slack ns','hold slack ns','hold TNS ns','相邻档TNS收益 ns','审查结论']
    text='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>主 Agent 预布线质量审查</title><style>body{font:16px/1.7 sans-serif;max-width:1200px;margin:40px auto;padding:20px;color:#17283a}.scroll{overflow:auto}table{border-collapse:collapse}td,th{border:1px solid #ccd6df;padding:10px}th{background:#edf3f7}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>主 Agent 预布线质量审查</h1><p>状态：'+html.escape(r['status'])+'；选择：'+html.escape(str(r.get('selected')))+'。工具成功不等于质量通过。</p><p>IO适配修复＋整数DBU HPWL一致性检查＋hold时序/面积/网络成本门禁。执行在服务器，原生产结果保留，没有重跑布局或完整布线。拥塞、DRC、提取RC时序仍未知。</p><div class="scroll"><table><tr>'+''.join('<th>'+x+'</th>' for x in heads)+'</tr>'+''.join(rows)+'</table></div><h2>完整审查证据</h2><pre>'+html.escape(json.dumps(r,ensure_ascii=False,indent=2))+'</pre></html>'
    (f/'quality-review.html').write_text(text,encoding='utf-8')
