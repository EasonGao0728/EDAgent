"""Independent checks for the registered HD post-placement subset, not signoff."""
from collections import Counter
import re
from .def_validation import section

def pdn_policy_check(design,rule):
    """Check generated widths, not electrical integrity or foundry signoff."""
    errors=[];counts={}
    records={r.split()[0]:r for r in design.get('physical',{}).get('SPECIALNETS',[])}
    for net in ('VDD','VSS'):
        widths=re.findall(r'(?:ROUTED|NEW) (met\d+) (\d+)',records.get(net,''))
        actual=Counter((layer,int(width)) for layer,width in widths if int(width)>0)
        counts[net]={layer+':'+str(width):count for (layer,width),count in actual.items()}
        for layer,width in rule['widths_dbu'].items():
            if not actual[(layer,width)]:errors.append('missing_pdn_width:'+net+':'+layer)
        if any(rule['widths_dbu'].get(layer)!=width for layer,width in actual):
            errors.append('unexpected_pdn_width:'+net)
    return {'passed':not errors,'errors':errors,'counts':counts,'policy':rule,
            'not_checked':['power connectivity','current capacity','IR drop','foundry signoff']}


def io_policy_check(design,rule,logical_only_pdn_pins=()):
    """Check the registered iFP two-direction pin-layer policy and port rectangles."""
    errors=[];layers=Counter();checked=0
    for name,pin in design['pins'].items():
        if name in logical_only_pdn_pins and '+ SPECIAL' in pin:continue
        shapes=re.findall(r'\+ LAYER (\S+) \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \)',pin)
        if len(shapes)!=1:errors.append('unsupported_io_geometry:'+name);continue
        layer,x1,y1,x2,y2=shapes[0];checked+=1;layers[layer]+=1
        if layer not in rule['allowed_layers']:errors.append('io_layer_mismatch:'+name)
        if int(x2)-int(x1)!=rule['width_dbu'] or int(y2)-int(y1)!=rule['height_dbu']:errors.append('io_size_mismatch:'+name)
    if not checked:errors.append('no_signal_io_checked')
    return {'passed':not errors,'errors':errors,'checked_signal_pins':checked,'layer_counts':dict(layers),'policy':rule}


def route_records(path):
    """Compare full per-net routing tokens as well as endpoint-only DEF parsing."""
    text=path.read_text(encoding='utf-8')
    result={}
    for row in section(text,'NETS'):
        name=row.split()[0]
        # Keep route order, masks, via names, widths and coordinates; only whitespace normalizes.
        result[name]=' '.join(row.split('+',1)[1].split()) if '+' in row else ''
    return result


def routing_gate(summary):
    errors=[]
    if summary.get('route_complete') is not True:errors.append('route_complete_not_true')
    stages=summary.get('stage_ledger',summary.get('stage_status',summary.get('stages',[])))
    if isinstance(stages,dict):stages=list(stages.values())
    for stage in stages:
        if stage.get('failed') or stage.get('timed_out'):errors.append('routing_substage_failed')
        if stage.get('entered') and stage.get('completed') is not True:errors.append('entered_routing_substage_incomplete')
    dr=summary.get('dr_summary',{})
    if not dr or dr.get('total_net_num',0)<=0 or dr.get('routed_net_num')!=dr.get('total_net_num'):
        errors.append('routed_net_count_mismatch_or_missing')
    return {'passed':not errors,'errors':errors,'route_complete':summary.get('route_complete'),
            'routed_net_num':dr.get('routed_net_num'),'total_net_num':dr.get('total_net_num')}


def drc_gate(summary, *, report_dir=None, producer_sha256=None):
    errors=[]
    if summary.get('execution_started') is not True:errors.append('drc_not_executed')
    if summary.get('status') not in ('clean','partial_clean'):errors.append('drc_not_clean')
    if type(summary.get('violation_count')) is not int or summary['violation_count']!=0:errors.append('drc_violations_or_unknown')
    if not summary.get('checked'):errors.append('no_checked_rule_families')
    if summary.get('skipped') or summary.get('refused'):errors.append('drc_skipped_or_refused')
    counters=summary.get('runtime',{})
    per_rule=counters.get('per_rule',{})
    invalid_counts=any(not isinstance(v,dict) or type(v.get('violation_count')) is not int or v['violation_count']<0 for v in per_rule.values())
    if invalid_counts:errors.append('invalid_drc_runtime_counts')
    evidence=None
    if report_dir is not None:
        from .drc_counts import reconcile
        evidence=reconcile(summary,report_dir,producer_sha256)
        if not evidence['passed']:errors.append('drc_final_evidence_inconsistent')
    explained=evidence and evidence['passed'] and evidence['runtime_scope']=='pre_filter_per_cluster_candidates'
    if not explained and summary.get('violation_count')==0 and any(type(v.get('violation_count')) is int and v['violation_count']>0 for v in per_rule.values() if isinstance(v,dict)):
        errors.append('drc_counter_discrepancy_requires_review')
    return {'passed':not errors,'errors':errors,'violation_count':summary.get('violation_count'),
            'checked':summary.get('checked',[]),'unsupported':summary.get('unsupported',[]),
            'runtime':counters,'count_reconciliation':evidence,'signoff_clean':False,'scope':'supported iEDA rule families only'}


def transformation_check(before,after,stage):
    """Permit only audited clock buffers and filler; no other logical optimization."""
    errors=[];added=set(after['components'])-set(before['components'])
    for key in ('design','units','die','pins'):
        if before[key]!=after[key]:errors.append('changed_'+key)
    for name,cell in before['components'].items():
        new=after['components'].get(name)
        if new is None or new['master']!=cell['master']:errors.append('changed_original:'+name)
        elif cell['placement'] and cell['placement'][0]=='FIXED' and cell!=new:errors.append('changed_fixed:'+name)
        elif stage in ('routing','filler','drc','routed_readback') and cell!=new:errors.append('changed_position:'+name)
    if stage=='cts':
        if any(after['components'][n]['master']!='sky130_fd_sc_hd__buf_1' for n in added):errors.append('unapproved_clock_cell')
        # Every original endpoint must remain, under the same logical net after buffer contraction.
        nets={n:set(pins) for n,pins in after['nets'].items()}
        consumed=set();clock_endpoints=set();stack=['clk'];visited=set()
        while stack:
            net=stack.pop()
            if net in visited:errors.append('clock_cycle_or_multiple_parent');break
            visited.add(net)
            if net not in nets:errors.append('missing_clock_net');break
            for inst,pin in nets[net]:
                if inst in added:
                    if pin=='A':
                        if inst in consumed:errors.append('clock_buffer_reused');continue
                        consumed.add(inst)
                        outputs=[n for n,pins in nets.items() if (inst,'X') in pins]
                        if len(outputs)!=1 or outputs[0]==net:errors.append('invalid_clock_buffer_output')
                        else:stack.append(outputs[0])
                    elif pin!='X':errors.append('unknown_clock_buffer_pin')
                else:clock_endpoints.add((inst,pin))
        if consumed!=added:errors.append('disconnected_added_buffer')
        if clock_endpoints!=set(before['nets'].get('clk',[])):errors.append('clock_endpoint_change')
        for n,pins in before['nets'].items():
            if n!='clk' and set(after['nets'].get(n,[]))!=set(pins):errors.append('nonclock_net_changed:'+n)
        if set(after['nets'])-visited != set(before['nets'])-{'clk'}:errors.append('unexpected_net')
        # A buffer terminal may not be on multiple nets or an unrelated data net.
        terminal_nets=Counter(p for pins in after['nets'].values() for p in pins if p[0] in added)
        if any(terminal_nets[(n,p)]!=1 for n in added for p in ('A','X')):errors.append('clock_buffer_terminal_multiplicity')
    else:
        if before['nets']!=after['nets']:errors.append('net_connectivity_changed')
        if stage=='filler':
            if any(not re.fullmatch(r'sky130_fd_sc_hd__fill_(1|2|4|8)',after['components'][n]['master']) for n in added):
                errors.append('unapproved_filler')
        elif added:errors.append('unexpected_instances')
    return {'passed':not errors,'errors':errors,'added_instances':sorted(added),
            'scope':'DEF logical terminals and approved buffer topology; not LVS or formal equivalence'}
