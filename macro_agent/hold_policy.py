"""Host-owned cost/timing acceptance; model prose cannot bypass these gates."""
import math,re
VERSION='hold-cost-review-v1'
POLICY={'version':VERSION,'caps':[0.05,0.10,0.20],'max_area_growth':0.20,'max_net_growth':0.20,
        'setup_slack_floor_ns':0.0,'hold_slack_floor_ns':0.0,'max_setup_tns_regression_ns':0.0,
        'max_hold_tns_ns':0.0,'max_native_seconds':600,'campaign_seconds':1800,
        'scope':'diagnostic no-SPEF screening; not signoff; default cost limits are engineering policy, not learned optimum'}

def timing(text):
    out={};slacks={'min':[],'max':[]}
    for line in text.splitlines():
        v=[s.strip() for s in line.split('|')[1:-1]]
        if len(v)==8 and v[2] in slacks:slacks[v[2]].append(float(v[6]))
        if len(v)==3 and v[0]=='core_clock' and v[1] in slacks:out[v[1]+'_tns_ns']=float(v[2])
    for k,v in slacks.items():
        if not v or k+'_tns_ns' not in out:raise ValueError('HOLD_REVIEW_MISSING_STA_EVIDENCE')
        out[k+'_worst_slack_ns']=min(v)
    if not all(math.isfinite(v) for v in out.values()):raise ValueError('HOLD_REVIEW_NONFINITE_TIMING')
    return out

def review(candidates,policy=None):
    p=policy or POLICY
    if not candidates or candidates[0]['label']!='skip':raise ValueError('HOLD_BASELINE_REQUIRED')
    base=candidates[0];rows=[];previous=None
    for c in candidates:
        m=c['measurement'];t=c['timing'];b=base['measurement'];bt=base['timing']
        area=m['standard_cell_area_um2']/b['standard_cell_area_um2']-1
        nets=m['nets']/max(1,b['nets'])-1;buffers=m['instances']-b['instances'];reasons=[]
        if not c.get('geometry_passed'):reasons.append('geometry_failed')
        if not c.get('connectivity_passed'):reasons.append('connectivity_unverified')
        if area>p['max_area_growth']+1e-12:reasons.append('area_budget_exceeded')
        if nets>p['max_net_growth']+1e-12:reasons.append('net_budget_exceeded')
        if t['min_worst_slack_ns']<p['hold_slack_floor_ns'] or t['min_tns_ns']<p['max_hold_tns_ns']:reasons.append('hold_not_clean')
        if t['max_worst_slack_ns']<p['setup_slack_floor_ns']:reasons.append('setup_not_clean')
        if t['max_tns_ns']<bt['max_tns_ns']-p['max_setup_tns_regression_ns']:reasons.append('setup_tns_regression')
        row={**c,'area_growth':area,'net_growth':nets,'added_buffers':buffers,
            'hpwl_change_um':m['hpwl_um']-b['hpwl_um'],'hold_tns_improvement_ns':t['min_tns_ns']-bt['min_tns_ns'],
            'rejection_reasons':reasons,'eligible':not reasons,'congestion':'unknown_not_measured','drc':'unknown_not_measured'}
        if previous:
            extra=buffers-previous['added_buffers'];gain=t['min_tns_ns']-previous['timing']['min_tns_ns']
            row['marginal']={'additional_buffers':extra,'hold_tns_gain_ns':gain,'gain_ns_per_100_buffers':100*gain/extra if extra>0 else None}
        rows.append(row);previous=row
    feasible=[x for x in rows if x['eligible']]
    chosen=min(feasible,key=lambda x:(x['measurement']['standard_cell_area_um2'],x['measurement']['nets'],x['measurement']['hpwl_um'])) if feasible else None
    return {'schema_version':VERSION,'policy':p,'candidates':rows,'selected':chosen['label'] if chosen else None,
            'status':'accepted_for_pre_route' if chosen else 'review_required','passed':bool(chosen),
            'routing_allowed':bool(chosen),'signoff_clean':False,'production_replaced':False,
            'selection_rule':'Among timing-clean, geometry/connectivity-valid, cost-bounded candidates choose minimum area then nets then HPWL; otherwise preserve baseline and stop',
            'unknowns':['post-route congestion','post-route DRC','extracted parasitic timing','power']}
