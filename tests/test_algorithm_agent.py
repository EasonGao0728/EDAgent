import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from macro_agent import algorithm_agent as aa
from macro_agent.dsh_host import initialize,act,ROOT
from macro_agent.common import digest,read_json,write_json
from macro_agent.windows_sandbox import WindowsSandbox

SOURCE='''def propose_moves(context, budget, rng):
    candidates=[]
    step=context.summary()['grid']*5
    for m in context.macros(budget['target_macro_ids']):
        for dx,dy in [(step,0),(0,step),(-step,0),(0,-step)]:
            moves=[{'macro_id':m['id'],'x':m['x']+dx,'y':m['y']+dy}]
            if context.is_legal(moves):
                candidates.append((context.hpwl(moves),moves))
    candidates.sort(key=lambda item:item[0])
    return [{'moves':item[1]} for item in candidates[:budget['max_candidates']]]
'''

class ProviderFixture:
    def __init__(self,sources=None):self.contexts=[];self.sources=sources or [SOURCE]
    def generate(self,system,context,schema,seed,reasoning_effort=None):
        self.contexts.append(copy.deepcopy(context))
        if 'metric' in schema['properties']:
            result={'metric':context['tool_request']['metric'],'units':context['tool_request']['units'],
                'variables':'lower-left x/y on the frozen core grid','hard_constraints':aa.CONSTRAINTS,
                'method':'rank legal axial neighbors by the host HPWL','assumptions':'toy macro-center pins',
                'limitations':'local search, no PPA guarantee'}
        else:result={'description':'OFFLINE TEST FIXTURE, not LLM-generated','source':self.sources.pop(0)}
        return result,{'provider':'offline_fixture','reasoning_effort':reasoning_effort}

class AlgorithmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.sandbox=WindowsSandbox(ROOT,timeout=10)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'runs');self.run=Path(self.temp.name)/'run'
        self.state=initialize(self.run,ROOT/'cases/toy/connected_groups.json')
        self.action={'tool':'request_tool','state_id':digest(self.state['case']),'reason':'need reusable ranked local search',
            'target_ids':['a','b'],'metric':'weighted_macro_center_hpwl'}
        self.provider=ProviderFixture()
    def tearDown(self):self.temp.cleanup()
    def request(self):
        result=act(self.state,self.action,'request',run=self.run)
        self.rid=result['request_id'];return result
    def step(self,n):
        return aa.advance(self.run,self.rid,str(n),provider=self.provider,sandbox=self.sandbox,guard=lambda:None)
    def delivered(self):
        self.request();self.step(1);self.step(2);return self.step(3)
    def test_real_sandbox_delivery_then_independent_commit(self):
        before=copy.deepcopy(self.state['case'])
        result=self.delivered()
        self.assertEqual(result['status'],'delivered',result)
        self.assertEqual(self.state['case'],before)
        self.assertEqual(len(self.provider.contexts),2)
        self.assertNotIn('messages',self.provider.contexts[1])
        self.assertIn('model_spec',self.provider.contexts[1])
        validation=read_json(Path(result['delivery']['validation_ref']))
        self.assertEqual(validation['sandbox'],'windows_appcontainer')
        self.assertFalse(validation['generalization_tested'])
        action={'tool':'run_generated_tool','tool_id':result['delivery']['tool_id'],'state_id':digest(before)}
        applied=act(self.state,action,'run-generated',run=self.run)
        self.assertTrue(applied['accepted']);self.assertLess(applied['after']['weighted_hpwl'],applied['before']['weighted_hpwl'])
        self.assertEqual(act(self.state,action,'run-generated',run=self.run),applied)
    def test_duplicate_step_does_not_call_model_twice(self):
        self.request();first=self.step(1);second=self.step(1)
        self.assertEqual(first,second);self.assertEqual(len(self.provider.contexts),1)
    def test_metric_and_scope_rejected(self):
        for fields in ({'metric':'PPA'},{'target_ids':['hub']},{'target_ids':['a','a']}):
            with self.assertRaises(ValueError):aa.create_request(self.run,self.state,{**self.action,**fields},'bad')
    def test_stale_snapshot_stops_development(self):
        self.request();self.state['case']['macros'][1]['x']+=1
        with self.assertRaisesRegex(ValueError,'stale Algorithm'):
            act(self.state,{'tool':'algorithm_step','state_id':digest(self.state['case']),'request_id':self.rid},'s',run=self.run)
    def test_invalid_scope_candidate_is_rejected_and_repaired(self):
        bad="def propose_moves(context, budget, rng):\n    return [{'moves':[{'macro_id':'hub','x':0,'y':0}]}]\n"
        self.provider=ProviderFixture([bad,SOURCE]);self.request();self.step(1);self.step(2)
        result=self.step(3);self.assertEqual(result['status'],'repair',result)
        self.step(4);result=self.step(5)
        self.assertEqual(result['status'],'delivered',result);self.assertEqual(result['model_calls'],3)
        self.assertIn('candidate_errors',self.provider.contexts[-1]['feedback'])
    def test_source_hash_tamper_refused(self):
        result=self.delivered();p=aa.job_path(self.run,self.rid)/'code.json';code=read_json(p)
        code['source']+='\n# changed';write_json(p,code)
        with self.assertRaisesRegex(ValueError,'source hash'):
            aa.run_tool(self.run,self.state,result['delivery']['tool_id'],sandbox=self.sandbox)
    def test_invalid_model_spec_cannot_redefine_objective(self):
        request=self.request();job=read_json(aa.job_path(self.run,self.rid)/'job.json')
        spec=ProviderFixture().generate('',{'tool_request':job['request']},aa.SPEC_SCHEMA,7)[0]
        spec['metric']='PPA'
        with self.assertRaises(ValueError):aa.check_spec(spec,job['request'])
    def test_quota_refresh_failure_blocks_maker(self):
        with patch('macro_agent.quota.ensure_quota',side_effect=ValueError('QUOTA_UNAVAILABLE')) as guard:
            with self.assertRaisesRegex(ValueError,'QUOTA_UNAVAILABLE'):aa.quota_guard()
            guard.assert_called_once_with()
    def test_model_failures_consume_reserved_budget(self):
        self.request()
        with patch.object(self.provider,'generate',side_effect=RuntimeError('offline simulated failure')):
            for n in range(1,4):result=self.step(n)
        self.assertEqual(result['status'],'failed');self.assertEqual(result['model_calls'],3)
        self.assertEqual(self.step(4)['status'],'failed')

if __name__=='__main__':unittest.main()
