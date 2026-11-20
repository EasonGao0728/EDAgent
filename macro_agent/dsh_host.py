"""Main-agent tools, bounded Algorithm Agent handoff and official OAuth bridge."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

from .adapters.toy import load_case
from .common import digest
from .context_api import DesignContext
from .evaluator import evaluate
from .geometry import metrics

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ['query_design', 'retrieve_knowledge', 'run_fixed_tool', 'finish']
ACTION_SCHEMA = {'type': 'object', 'additionalProperties': False,
 'properties': {'tool': {'type': 'string', 'enum': TOOLS},
 'state_id': {'type': 'string'}, 'reason': {'type': 'string'},
 'query': {'type': 'string'}, 'tool_id': {'type': 'string', 'enum': ['', 'neighbor_v1', 'swap_v1']},
 'offset': {'type': 'integer'}, 'limit': {'type': 'integer'}},
 'required': ['tool', 'state_id', 'reason', 'query', 'tool_id', 'offset', 'limit']}

def save(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    os.replace(temp, path)

def run_path(value):
    path = Path(value).resolve()
    if not path.is_relative_to(ROOT / 'runs'):
        raise ValueError('run must be inside project runs directory')
    return path

def initialize(directory, case_path):
    directory = run_path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    case = load_case(case_path)
    state = {'version': 1, 'case': case, 'baseline': copy.deepcopy(case),
      'contract': {'goal': 'reduce weighted macro-center HPWL while preserving legality',
       'evaluation_stage': 'toy_macro_center_proxy', 'units': case['units'],
       'maker_enabled': True, 'max_actions': 24, 'max_evaluations': 160,
       'max_model_calls': 8, 'max_internal_trials_per_tool': 80},
      'counts': {'actions': 0, 'evaluations': 0, 'model_calls': 0},
      'status': 'running', 'receipts': {}, 'events': [], 'pending': None}
    save(directory/'checkpoint.json', state)
    return state

def knowledge(query):
    # Curated source material; text and version are returned, never instructions.
    docs = [('evaluation', 'macro_agent/evaluator.py'),
            ('main_agent_guide', 'dsh/knowledge/main-agent.md')]
    terms = set(query.lower().replace('hpwl', 'hpwl weighted').split())
    hits = []
    for key, rel in docs:
        text = (ROOT/rel).read_text(encoding='utf-8')
        lines = text.splitlines()
        for i in range(0, len(lines), 18):
            part = '\n'.join(lines[i:i+18])
            score = sum(term in part.lower() for term in terms)
            if score:
                hits.append({'chunk_id': f'{key}:{i+1}', 'source_ref': rel,
                 'lines': [i+1, min(i+18,len(lines))], 'content_version': hashlib.sha256(text.encode()).hexdigest(),
                 'text': part, 'score': score})
    hits.sort(key=lambda x: -x['score'])
    return {'status': 'matched' if hits else 'no_match', 'hits': hits[:3],
            'truncated': len(hits)>3, 'authority': 'reference_data_only'}

def candidates(case, tool_id, cap):
    movable = [m for m in case['macros'] if not m['fixed']]
    count = 0
    if tool_id == 'neighbor_v1':
        step = case['grid'] * 5
        for m in movable:
            for dx,dy in [(step,0),(-step,0),(0,step),(0,-step),(step,step),(-step,-step)]:
                if count >= cap: return
                count += 1
                yield {'moves': [{'macro_id':m['id'],'x':m['x']+dx,'y':m['y']+dy}]}
    elif tool_id == 'swap_v1':
        for i,a in enumerate(movable):
            for b in movable[i+1:]:
                if count >= cap: return
                count += 1
                yield {'moves':[{'macro_id':a['id'],'x':b['x'],'y':b['y']},
                                {'macro_id':b['id'],'x':a['x'],'y':a['y']}]}
    else: raise ValueError('unknown fixed tool')

def act(state, action, action_id, run=None, route=None):
    if action_id in state['receipts']:
        if state['receipts'][action_id]['request_hash'] != digest(action):
            raise ValueError('action_id reused with different arguments')
        return state['receipts'][action_id]['result']
    if state['status'] != 'running': raise ValueError('task already stopped')
    if state['counts']['actions'] >= state['contract']['max_actions']: raise ValueError('action budget exhausted')
    state['counts']['actions'] += 1
    case = state['case']; current = digest(case)
    if action.get('state_id') != current:
        result = {'error': 'stale_state', 'current_state_id': current}
    else:
        name = action.get('tool')
        if name == 'query_design':
            offset, limit = action.get('offset',0), action.get('limit',10)
            if type(offset) is not int or type(limit) is not int or offset<0 or not 1<=limit<=20:
                raise ValueError('invalid pagination')
            items = case['nets'] if action.get('query') == 'nets' else case['macros']
            result = {'state_id':current, 'source':'current_design_snapshot',
             'items':items[offset:offset+limit], 'total':len(items),
             'next_offset':offset+limit if offset+limit<len(items) else None,
             'truncated':offset+limit<len(items), 'summary':DesignContext(case).summary()}
        elif name == 'retrieve_knowledge': result = knowledge(action.get('query',''))
        elif name == 'tool_catalog':
            from .oss_tools import catalog
            result = catalog()
            if run:
                from .algorithm_agent import packages
                result['generated_tools']=packages(run)
        elif name in ('request_tool','algorithm_step','run_generated_tool'):
            if not run:raise ValueError('Algorithm Agent needs a persistent run workspace')
            from . import algorithm_agent as algorithm
            if name=='request_tool':
                result=algorithm.create_request(run,state,action,action_id)
            elif name=='algorithm_step':
                job=algorithm.read_json(algorithm.job_path(run,action['request_id'])/'job.json')
                if job['request']['base_state_id']!=current:raise ValueError('stale Algorithm Agent request: create a request against current design')
                route=route or {}
                result=algorithm.advance(run,action['request_id'],action_id,
                    model=route.get('model','gpt-6.1-sol'),effort=route.get('reasoning_effort','xhigh'))
                state['counts']['maker_model_calls']=state['counts'].get('maker_model_calls',0)+result['model_calls']-job['model_calls']
            else:result=algorithm.run_tool(run,state,action['tool_id'])
        elif name == 'analyze_connectivity':
            from .oss_tools import connectivity
            result = connectivity(case)
        elif name in ('run_fixed_tool','run_oss_tool'):
            available = state['contract']['max_evaluations']-state['counts']['evaluations']
            cap = min(available, state['contract']['max_internal_trials_per_tool'])
            target_ids = [m['id'] for m in case['macros'] if not m['fixed']]
            records=[]; selected=case; best=metrics(case)['weighted_hpwl']
            metadata={}
            if name == 'run_oss_tool':
                if action.get('tool_id')!='ortools_cpsat':raise ValueError('unsupported executable OSS tool')
                from .oss_tools import solve
                batches,metadata=solve(case) if cap else ([],{})
            else:batches=candidates(case,action.get('tool_id'),cap)
            for batch in batches:
                candidate, record = evaluate(case,batch,target_ids)
                state['counts']['evaluations'] += 1
                records.append(record)
                if record.get('improved') and record['after']['weighted_hpwl']<best:
                    best=record['after']['weighted_hpwl'];selected=candidate
            state['case']=selected
            result={'state_id':digest(selected),'parent_state_id':current,
              'tool_id':action['tool_id'],'tool_version':'1','evaluated':len(records),
              'legal_candidates':sum(r['legal'] for r in records),
              'before':metrics(case),'after':metrics(selected),'accepted':selected is not case,
              'evaluation_records':records,'solver':metadata,'stop_reason':'evaluation_budget' if cap==0 else None}
        elif name == 'finish':
            state['status']='stopped_with_best'
            maker_calls=state['counts'].get('maker_model_calls',0)
            if run:
                from .algorithm_agent import read_json
                maker_calls=sum(read_json(p)['model_calls'] for p in (Path(run)/'algorithm').glob('req_*/job.json'))
            result={'status':state['status'],'reason':action.get('reason',''),
             'baseline':metrics(state['baseline']),'best':metrics(case),
             'goal_certified':False,'maker_calls':maker_calls}
        else: raise ValueError('tool not available')
    state['receipts'][action_id]={'request_hash':digest(action),'result':result}
    state['events'].append({'action_id':action_id,'action':action,'result':result})
    state['pending']=None
    return result

def main(req):
    mode=req['mode']
    if mode=='task':
        from .main_task import dispatch
        return dispatch(req)
    # Non-secret process context helps distinguish desktop and terminal routing.
    from urllib.request import getproxies,proxy_bypass
    from urllib.parse import urlsplit
    try:
        if mode in ('native_model','models','quota'):
            proxy_summary={}
            for key,value in getproxies().items():
                if key in ('http','https','all'):
                    parsed=urlsplit(value)
                    proxy_summary[key]={'scheme':parsed.scheme,'host':parsed.hostname,'port':parsed.port,
                                        'has_credentials':bool(parsed.username or parsed.password)}
            (ROOT/f'.cache/dsh-host-context-{mode}.json').write_text(json.dumps(
                {'mode':mode,'proxies':proxy_summary,'bypass_api':proxy_bypass('api.openai.com'),'python':sys.executable,
                 'local_app_data':os.environ.get('LOCALAPPDATA')}),encoding='utf-8')
    except (OSError,ValueError): pass
    if mode=='auth_window':
        from .login_window import launch_window
        return launch_window()
    if mode=='quota':
        from .quota import ensure_quota
        return ensure_quota(req.get('file'))
    if mode=='ieda_status':
        from .ieda_runtime import status
        return status()
    if mode=='ieda_run':
        from .ieda_runtime import run_case
        return run_case(req['run'],req['case_id'])
    if mode=='models':
        from .chatgpt_provider import ChatGPTProvider
        return ChatGPTProvider().models()
    if mode=='native_model':
        from .dsh_native import native_model
        return native_model(req)
    if mode=='model':
        from .chatgpt_provider import ChatGPTProvider
        provider=ChatGPTProvider(model=req.get('model'))
        provider.resolve_model()
        action,usage=provider.generate(req['system'],req['prompt'],ACTION_SCHEMA,7,reasoning_effort=req.get('reasoning_effort','xhigh'))
        return {'action':action,'usage':usage}
    if mode=='init': return initialize(req['run'],req['case'])
    path=run_path(req['run'])/'checkpoint.json'
    state=json.loads(path.read_text(encoding='utf-8'))
    if mode=='state': return state
    if mode=='snapshot': return {'state_id':digest(state['case']), 'metrics':metrics(state['case']),
                                'summary':DesignContext(state['case']).summary()}
    if mode=='reserve_model':
        if state['counts']['model_calls']>=state['contract']['max_model_calls']: raise ValueError('model budget exhausted')
        state['counts']['model_calls']+=1
    elif mode=='pending': state['pending']=req['pending']
    elif mode=='reject_pending':
        pending=state['pending']
        if pending:
            state['counts']['actions']+=1
            state['events'].append({**pending,'result':{'error':req['error']}})
            state['pending']=None
    elif mode=='act':
        result=act(state,req['action'],req['action_id'],run=req['run'],route=req.get('route'))
        save(path,state)
        return result
    elif mode=='stop': state['status']=req['status']
    else: raise ValueError('unknown host operation')
    save(path,state)
    return state

if __name__=='__main__':
    try:
        req=json.load(sys.stdin)
        print(json.dumps({'ok':True,'value':main(req)},ensure_ascii=False,allow_nan=False))
    except Exception as exc:
        from .bridge_errors import error_response
        request=locals().get('req')
        print(json.dumps(error_response(exc,request.get('mode') if isinstance(request,dict) else 'input')))
        sys.exit(1)
