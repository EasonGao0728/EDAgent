"""Separate execution completeness from physical quality, per user acceptance.

Residual DRC is recorded as quality failure. Missing nets, skipped work, timeouts
and contradictory evidence are never accepted as completed reproduction.
"""
from .backend_checks import routing_gate,drc_gate

def routing_observation(summary):
    errors=[];route=summary.get('route',{});dr=summary.get('dr_summary',{})
    if type(route.get('total_net_num')) is not int or route.get('total_net_num',0)<=0:errors.append('missing_total_nets')
    if route.get('routed_net_num')!=route.get('total_net_num') or route.get('unrouted_net_num')!=0:errors.append('unrouted_nets')
    if dr.get('routed_net_num')!=route.get('routed_net_num') or dr.get('total_net_num')!=route.get('total_net_num'):errors.append('route_count_discrepancy')
    stages={s['stage']:s for s in summary.get('stage_ledger',[])}
    for name in ('PA','SA','TG','LA','SR','TA','DR','VR'):
        s=stages.get(name,{})
        if not s.get('entered') or not s.get('completed') or s.get('failed') or s.get('timed_out') or s.get('skipped'):errors.append('incomplete_native_stage:'+name)
    if summary.get('coverage',{}).get('failed_stage_count')!=0:errors.append('failed_stage_count')
    issues=set(summary.get('route_issue_count_map',{}))
    if issues-{'residual_drc','route_incomplete'}:errors.append('unexpected_route_issues')
    if not summary.get('route_complete') and not (summary.get('reason')=='residual_drc' and route.get('residual_drc',0)>0):errors.append('unexplained_route_incomplete')
    return {'passed':not errors,'errors':errors,'scope':'Complete native routing execution and all-net coverage; residual DRC is a separate quality outcome',
        'route_complete':summary.get('route_complete'),'routed_net_num':route.get('routed_net_num'),'total_net_num':route.get('total_net_num'),
        'residual_drc':route.get('residual_drc'),'quality_assessment':routing_gate(summary),'signoff_clean':False}

def drc_observation(summary, *, report_dir=None, producer_sha256=None):
    quality=drc_gate(summary,report_dir=report_dir,producer_sha256=producer_sha256);errors=[];count=summary.get('violation_count')
    if summary.get('execution_started') is not True:errors.append('not_executed')
    if type(count) is not int or count<0:errors.append('missing_or_invalid_violation_count')
    if not summary.get('checked') or summary.get('skipped') or summary.get('refused'):errors.append('missing_or_skipped_drc_coverage')
    if summary.get('status') not in ('clean','partial_clean','dirty','violations','violation','partial_dirty'):
        errors.append('unrecognized_drc_status:'+str(summary.get('status')))
    evidence=quality.get('count_reconciliation')
    if evidence and not evidence['passed']:errors.append('drc_final_evidence_inconsistent')
    explained=evidence and evidence['passed'] and evidence['runtime_scope']=='pre_filter_per_cluster_candidates'
    if 'invalid_drc_runtime_counts' in quality['errors']:errors.append('invalid_drc_runtime_counts')
    if not explained and count==0 and any(type(v.get('violation_count')) is int and v['violation_count']>0 for v in summary.get('runtime',{}).get('per_rule',{}).values() if isinstance(v,dict)):
        errors.append('contradictory_drc_counts')
    return {'passed':not errors,'errors':errors,'scope':'DRC executed and faithfully reported; zero-violation quality is separate',
        'violation_count':count,'checked':summary.get('checked',[]),'unsupported':summary.get('unsupported',[]),
        'runtime':summary.get('runtime',{}),'count_reconciliation':evidence,'quality_clean':quality['passed'],'quality_assessment':quality,'signoff_clean':False}
