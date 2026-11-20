"""Strict read-only audit of equal-valued minimum-path report selection.

This recognizes a reporting distinction, not numerical tolerance. Setup paths,
TNS, minimum data-path values (including JSON precision), and timing footers must
match. Different clock branches are allowed only under explicitly ideal clocks
with zero reported clock delay. Original reports remain unchanged.
"""
import copy, hashlib, json, re
from pathlib import Path
from macro_agent.def_validation import read_def

GIT = 'aa25008b3778a76ae1975c839d4cc459f7f7b3b7'
SOURCE = f'https://github.com/OSCC-Project/iEDA/blob/{GIT}/src/operation/iSTA/source/module/sta/StaReport.cc#L154'


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def tables(path):
    lines = Path(path).read_text(encoding='utf-8').splitlines()
    if len(lines)<3 or not lines[0].endswith('GitVersion: '+GIT+'.'):
        raise ValueError('Unreviewed timing producer')
    groups = []; current = None
    for line in lines[2:]:
        if not line.strip() or line.startswith('+'): continue
        if not line.startswith('|') or not line.endswith('|'):
            raise ValueError('Unknown timing report content')
        row = [v.strip() for v in line[1:-1].split('|')]
        if row[0] in ('Endpoint', 'Clock', 'Point'):
            current = {'header': row, 'rows': []}; groups.append(current)
        elif current is None:
            raise ValueError('Missing timing table header')
        else:
            if len(row) != len(current['header']): raise ValueError('Timing column count changed')
            current['rows'].append(row)
    if len(groups)<3 or groups[0]['header'] != ['Endpoint','Clock Group','Delay Type','Path Delay','Path Required','CPPR','Slack','Freq(MHz)'] or groups[1]['header'] != ['Clock','Delay Type','TNS']:
        raise ValueError('Unexpected timing summary')
    if any(g['header'] != ['Point','Fanout','Capacitance','Resistance','Transition','Delta Delay','Incr','Path'] for g in groups[2:]):
        raise ValueError('Unexpected path detail schema')
    if len(groups[0]['rows']) != len(groups)-2: raise ValueError('Missing detailed path')
    return groups


def point(value, design):
    m = re.fullmatch(r'([^:]+):([^ ]+) \(([^)]+)\)', value)
    if m:
        inst, pin, master = m.groups()
        if design['components'].get(inst,{}).get('master') != master:
            raise ValueError('Path master differs from DEF')
        return (inst,pin), master
    if value.endswith(' (port)'):
        name=value[:-7]
        if name not in design['pins']: raise ValueError('Unknown path port')
        return ('PIN',name), 'port'
    raise ValueError('Unrecognized timing point')


def wire_signature(path, design):
    data=json.loads(Path(path).read_text()); canonical=copy.deepcopy(data)
    roles={}; nodes=[]; node_labels=[]; net_terms={}
    for net,terms in design['nets'].items():
        for term in terms:
            t=tuple(term)
            if t in net_terms: raise ValueError('DEF endpoint repeated')
            net_terms[t]=net
    for row in canonical:
        if len(row)!=1: raise ValueError('Unknown path JSON')
        key,val=next(iter(row.items()))
        if key.startswith('node_'):
            if set(val)!={'Point','Capacitance','slew','trans_type'}: raise ValueError('Unknown node fields')
            term,master=point(val['Point'],design); node_labels.append(val['Point'])
            if term[0] not in roles: roles[term[0]]=len(roles)
            val['Point']={'instance_role':roles[term[0]],'pin':term[1],'master':master}
            nodes.append(term)
        elif key.startswith('inst_arc_'):
            if set(val)!={'Incr'}: raise ValueError('Unknown arc fields')
        else: raise ValueError('Unknown path record')
    for a,b in zip(nodes,nodes[1:]):
        if a[0]!=b[0] and (a not in net_terms or net_terms[a]!=net_terms.get(b)):
            raise ValueError('Reported path is not connected in DEF')
    return canonical, nodes, node_labels, roles, net_terms


def minimum_detail(detail, wire, design):
    canonical,nodes,labels,roles,net_terms=wire
    rows=detail['rows']; starts=[]
    for i,r in enumerate(rows[:-1]):
        if r[0]!=labels[0]:continue
        following=next((v for v in rows[i+1:] if not v[0].endswith(' (net)')),None)
        if following and following[0]==labels[1]:starts.append(i)
    if len(starts)!=1: raise ValueError('Ambiguous data path start')
    start=starts[0];ends=[i for i in range(start,len(rows)) if rows[i][0]==labels[-1]]
    if len(ends)!=1: raise ValueError('Ambiguous data path end')
    end=ends[0]; footer=next((i for i in range(end+1,len(rows)) if rows[i][0] in ('library hold time','library removal time')),None)
    if footer is None: raise ValueError('Minimum-path footer missing')
    data_rows=copy.deepcopy(rows[start:end+1]); seen=[]; net_roles={}
    for row in data_rows:
        if row[0].endswith(' (net)'):
            name=row[0][:-6]
            if name not in design['nets']: raise ValueError('Unknown data net')
            if name not in net_roles: net_roles[name]=len(net_roles)
            row[0]=['data_net',net_roles[name]]
        else:
            term,master=point(row[0],design);seen.append(term)
            if term[0] not in roles: raise ValueError('Detail absent from full precision path')
            row[0]=[roles[term[0]],term[1],master]
    if seen!=nodes: raise ValueError('Detail and JSON paths differ')
    clock_rows=rows[:start]+rows[end+1:footer]
    if not any(r[0]=='clock network delay (ideal)' for r in clock_rows): raise ValueError('Nonideal clock')
    for row in clock_rows:
        if row[6] not in ('','0','0.000') or row[7] not in ('','0','0.000','0.000r','0.000f'):
            raise ValueError('Nonzero clock path delay')
        label=row[0]
        if not label or label.startswith('clock '): continue
        if label.endswith(' (clock net)'):
            if label[:-12] not in design['nets']: raise ValueError('Unknown clock net')
        else: point(label,design)
    footer_rows=rows[footer:]
    if not any(r[0]=='path net delay' and r[-1]=='0.000(0.000%)' for r in footer_rows):
        raise ValueError('Parasitic timing outside this audit scope')
    return {'data_rows':data_rows,'footer_rows':footer_rows,'wire_signature':canonical}


def audit(server_work,desktop_work,top):
    a=Path(server_work);b=Path(desktop_work);da=read_def(a/'result/filler.def');db=read_def(b/'result/filler.def')
    if da!=db: raise ValueError('Timing inputs differ')
    paths=[w/'result/timing'/(top+'.rpt') for w in (a,b)];ta,tb=map(tables,paths)
    if len(ta)!=len(tb) or ta[1]!=tb[1]: raise ValueError('TNS or path count differs')
    sa,sb=ta[0]['rows'],tb[0]['rows'];minimum=[r[1:] for r in sa if r[2]=='min']
    changed=[];evidence=[]
    for i,(ra,rb) in enumerate(zip(sa,sb)):
        wa=a/'result/timing/wire_paths'/f'wire_path_{i+1}.json';wb=b/'result/timing/wire_paths'/f'wire_path_{i+1}.json'
        x=wire_signature(wa,da);y=wire_signature(wb,db)
        if x[1][-1]!=tuple(ra[0].split(':')) or y[1][-1]!=tuple(rb[0].split(':')):
            raise ValueError('Summary endpoint differs from JSON')
        if ra==rb:
            if ta[i+2]!=tb[i+2] or json.loads(wa.read_text())!=json.loads(wb.read_text()):
                raise ValueError('Same endpoint timing differs')
        else:
            if ra[1:]!=rb[1:] or ra[2]!='min' or ra[5]!='0.000' or sum(r==ra[1:] for r in minimum)<2:
                raise ValueError('Difference is not a tied minimum-path selection')
            if x[0]!=y[0] or minimum_detail(ta[i+2],x,da)!=minimum_detail(tb[i+2],y,db):
                raise ValueError('Tied path precision, structure or detail differs')
            changed.append({'server_endpoint':ra[0],'dsh_endpoint':rb[0],'identical_metrics':ra[1:]})
        evidence.extend({'path':str(p),'sha256':sha(p)} for p in (wa,wb))
    exact_text = paths[0].read_text(encoding='utf-8').splitlines()[2:] == paths[1].read_text(encoding='utf-8').splitlines()[2:]
    return {'passed':True,'exact_report_text_equal':exact_text,'classification':'equal_minimum_path_selection' if changed else 'same_paths',
            'different_selected_paths':changed,'numerical_tolerance':'none',
            'scope':'Selected paths and clock TNS at reported precision, full JSON precision for data paths; ideal-clock/no-SPEF diagnostic only, not all-endpoint or signoff equivalence',
            'source':SOURCE,'evidence':[{'path':str(p),'sha256':sha(p)} for p in paths]+evidence}
