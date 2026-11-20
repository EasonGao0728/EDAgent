"""Reviewed open-source integrations. All placements are independently evaluated by host."""
import itertools
import math
import shutil
from importlib.metadata import version, PackageNotFoundError


def catalog():
    items=[]
    for tool, package, url, capability in [
        ('networkx_connectivity','networkx','https://github.com/networkx/networkx','netlist incidence graph analysis'),
        ('ortools_cpsat','ortools','https://github.com/google/or-tools','bounded integer toy macro placement')]:
        try: v=version(package)
        except PackageNotFoundError: v=None
        items.append(dict(tool_id=tool,version=v,available=v is not None,source=url,capability=capability))
    from .ieda_runtime import status
    items.append(status())
    for tool,url in [('openroad','https://github.com/The-OpenROAD-Project/OpenROAD')]:
        items.append(dict(tool_id=tool,source=url,available=False,executable_detected=shutil.which(tool),
            reason='Native flow adapter and validated LEF/DEF/PDK case not configured; discovery only, not executable.'))
    return {'tools':items,'evaluation_stage':'toy_macro_center_proxy'}


def connectivity(case):
    import networkx as nx
    graph=nx.Graph()
    graph.add_nodes_from(('node',m['id']) for m in case['macros']+case['ports'])
    for net in case['nets']:
        for node in net['nodes']:
            graph.add_edge(('net',net['id']),('node',node),weight=net['weight'])
    return {'library':'networkx','version':nx.__version__,'representation':'bipartite net incidence graph',
        'components':[sorted(n[1] for n in c if n[0]=='node') for c in nx.connected_components(graph)],
        'macro_incident_weight':{m['id']:sum(d['weight'] for _,_,d in graph.edges(('node',m['id']),data=True)) for m in case['macros']}}


def solve(case):
    from ortools.sat.python import cp_model
    # This first adapter deliberately rejects unsupported fractional geometry/weights.
    values=[case['grid'],case['min_spacing'],*case['core'].values()]
    for r in case['macros']+case['blockages']: values.extend(r[k] for k in ('x','y','width','height'))
    for p in case['ports']: values.extend([p['x'],p['y']])
    values.extend(n['weight'] for n in case['nets'])
    if any(not float(v).is_integer() for v in values):raise ValueError('CP-SAT v1 requires integer geometry and net weights')
    if len(case['macros'])>50:raise ValueError('CP-SAT v1 limited to 50 macros')
    model=cp_model.CpModel(); core=case['core']; grid=int(case['grid']); spacing=int(case['min_spacing'])
    rects=[]; centers={}; coords={}
    for m in case['macros']:
        x=model.new_int_var(0,math.floor((core['width']-m['width'])/grid),m['id']+'_x')
        y=model.new_int_var(0,math.floor((core['height']-m['height'])/grid),m['id']+'_y')
        px=x*grid+int(core['x']);py=y*grid+int(core['y'])
        if m['fixed']:model.add(px==int(m['x']));model.add(py==int(m['y']))
        model.add_hint(x,int((m['x']-core['x'])/grid));model.add_hint(y,int((m['y']-core['y'])/grid))
        coords[m['id']]=(px,py); rects.append((px,py,int(m['width']),int(m['height'])))
        centers[m['id']]=(2*px+int(m['width']),2*py+int(m['height']))
    for b in case['blockages']:rects.append(tuple(int(b[k]) for k in ('x','y','width','height')))
    for i,(a,b) in enumerate(itertools.combinations(rects,2)):
        if all(isinstance(v,int) for v in a+b):continue
        # Disjunctive separation includes spacing; independent evaluator is final authority.
        flags=[model.new_bool_var(f'sep_{i}_{j}') for j in range(4)]
        for flag,condition in zip(flags,[a[0]+a[2]+spacing<=b[0],b[0]+b[2]+spacing<=a[0],a[1]+a[3]+spacing<=b[1],b[1]+b[3]+spacing<=a[1]]):
            model.add(condition).only_enforce_if(flag)
        model.add_bool_or(flags)
    for p in case['ports']:centers[p['id']]=(2*int(p['x']),2*int(p['y']))
    bound=4*int(abs(core['x'])+abs(core['y'])+core['width']+core['height']+sum(abs(p['x'])+abs(p['y']) for p in case['ports']))
    terms=[]
    for net in case['nets']:
        for axis in (0,1):
            lo=model.new_int_var(-bound,bound,'lo');hi=model.new_int_var(-bound,bound,'hi')
            vals=[centers[n][axis] for n in net['nodes']]
            model.add_min_equality(lo,vals);model.add_max_equality(hi,vals)
            terms.append(int(net['weight'])*(hi-lo))
    model.minimize(sum(terms))
    solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=5
    solver.parameters.num_search_workers=1;solver.parameters.random_seed=7
    status=solver.solve(model)
    result={'solver_status':solver.status_name(status),'time_limit_seconds':5,'library':'ortools', 'version':version('ortools')}
    if status not in (cp_model.FEASIBLE,cp_model.OPTIMAL):return [],result
    result.update(objective_hpwl=solver.objective_value/2,best_bound_hpwl=solver.best_objective_bound/2)
    moves=[{'macro_id':m['id'],'x':solver.value(coords[m['id']][0]),'y':solver.value(coords[m['id']][1])} for m in case['macros'] if not m['fixed']]
    return [{'moves':moves}],result
