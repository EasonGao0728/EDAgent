import copy
import tempfile
import unittest
from pathlib import Path
from macro_agent.dsh_host import ROOT, initialize, act, knowledge, candidates
from macro_agent.common import digest
from macro_agent.geometry import legality

class MainHostTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'runs')
        self.state=initialize(Path(self.temp.name)/'run',ROOT/'cases/toy/blocked_channel.json')
    def tearDown(self): self.temp.cleanup()
    def action(self,tool='run_fixed_tool',**kw):
        return dict(tool=tool,state_id=digest(self.state['case']),reason='test',
                    query='nets',tool_id='neighbor_v1',offset=0,limit=2,**kw)
    def test_fixed_tool_and_immutable_baseline(self):
        baseline=copy.deepcopy(self.state['baseline'])
        r=act(self.state,self.action(),'a')
        self.assertLessEqual(r['after']['weighted_hpwl'],r['before']['weighted_hpwl'])
        self.assertEqual(self.state['baseline'],baseline)
        self.assertTrue(all(e['validation_level']=='toy_geometry_and_macro_center_proxy' for e in r['evaluation_records'] if e['legal']))
    def test_idempotent_commit_and_collision(self):
        a=self.action();r=act(self.state,a,'a');counts=copy.deepcopy(self.state['counts'])
        self.assertEqual(act(self.state,a,'a'),r)
        self.assertEqual(self.state['counts'],counts)
        with self.assertRaises(ValueError):act(self.state,{**a,'reason':'changed'},'a')
    def test_stale_does_not_commit(self):
        a={**self.action(),'state_id':'wrong'};before=copy.deepcopy(self.state['case'])
        self.assertEqual(act(self.state,a,'a')['error'],'stale_state')
        self.assertEqual(before,self.state['case'])
    def test_eval_budget_is_hard(self):
        self.state['contract']['max_evaluations']=2
        r=act(self.state,self.action(),'a');self.assertEqual(r['evaluated'],2)
        r=act(self.state,self.action(),'b');self.assertEqual(r['evaluated'],0)
    def test_pagination(self):
        r=act(self.state,self.action('query_design'),'q')
        self.assertEqual(len(r['items']),2);self.assertEqual(r['next_offset'],2)
        self.assertTrue(r['truncated'])
    def test_unsupported_maker(self):
        with self.assertRaises(ValueError):act(self.state,self.action('make_tool'),'x')
    def test_stop_cannot_claim_optimality(self):
        r=act(self.state,self.action('finish'),'f')
        self.assertFalse(r['goal_certified'])
        with self.assertRaises(ValueError):act(self.state,self.action(),'next')
    def test_rag_no_match_and_sources(self):
        self.assertEqual(knowledge('unfindable_xyz')['status'],'no_match')
        hits=knowledge('HPWL')['hits'];self.assertTrue(hits)
        self.assertTrue(all(h['content_version'] and h['lines'] for h in hits))
    def test_fixed_macro_not_moved(self):
        fixed=[m for m in self.state['case']['macros'] if m['fixed']]
        act(self.state,self.action(),'a')
        self.assertEqual(fixed,[m for m in self.state['case']['macros'] if m['fixed']])
    def test_resume_receipt_survives_serialization(self):
        import json
        a=self.action();r=act(self.state,a,'x')
        recovered=json.loads(json.dumps(self.state))
        self.assertEqual(act(recovered,a,'x'),r)

if __name__=='__main__':unittest.main()
