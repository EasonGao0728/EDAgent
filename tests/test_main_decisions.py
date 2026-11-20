import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from macro_agent import main_task as task, main_decisions as d


class Decisions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=task.ROOT/'runs')
        self.folder=Path(self.tmp.name)
        task.dispatch({'run':str(self.folder),'operation':'start','case_id':'sky130_gcd'})
        self.state=task.load(self.folder/'task.json')
    def tearDown(self):self.tmp.cleanup()
    def observe(self):return d.inspect(self.state,self.folder)
    def request(self,tool='inspect_design',identity='test-call'):
        o=self.observe();c=d.catalog(self.state,self.folder)
        return {'action_id':identity,'tool_id':tool,'evidence_id':o['evidence_id'],
                'decision_state_id':c['decision_state_id'],'reason':'Measured facts motivate this choice',
                'expected_effect':'Gather evidence without claiming improvement','uncertainties':'No signoff evidence'}
    def test_no_evidence_or_stale_plan(self):
        req=self.request()
        with self.assertRaisesRegex(ValueError,'OBSERVATION'):d.plan(self.state,self.folder,{**req,'evidence_id':'invented'})
        with self.assertRaisesRegex(ValueError,'STALE'):d.plan(self.state,self.folder,{**req,'decision_state_id':'old'})
    def test_exactly_once_plan_and_execute(self):
        req=self.request();p=d.plan(self.state,self.folder,req)
        self.assertEqual(p,d.plan(self.state,self.folder,req))
        a=d.execute(self.state,self.folder,p['plan_id']);b=d.execute(self.state,self.folder,p['plan_id'])
        self.assertTrue(b['replayed']);self.assertEqual(a['tool_id'],'inspect_design')
        self.assertEqual(len(d.store(self.folder)['events']),1)
    def test_pending_plan_requires_cancel_before_replanning(self):
        p=d.plan(self.state,self.folder,self.request())
        with self.assertRaisesRegex(ValueError,'PENDING'):d.plan(self.state,self.folder,self.request(identity='second'))
        d.cancel_plan(self.state,self.folder,p['plan_id'],'Need different evidence')
        self.assertEqual(d.plan(self.state,self.folder,self.request(identity='third'))['status'],'planned')
    def test_identity_collision(self):
        req=self.request();d.plan(self.state,self.folder,req)
        with self.assertRaisesRegex(ValueError,'COLLISION'):d.plan(self.state,self.folder,{**req,'reason':'changed'})
    def test_no_maker_or_unregistered_repair(self):
        with self.assertRaisesRegex(ValueError,'NOT_ELIGIBLE'):d.plan(self.state,self.folder,self.request('invent_new_tool'))
        with self.assertRaisesRegex(ValueError,'NOT_ELIGIBLE'):d.plan(self.state,self.folder,self.request('route_top_met3'))
    def test_stop_does_not_mutate_native_task_or_claim_quality(self):
        self.state['status']='target_met';task.save(self.folder/'task.json',self.state)
        before=(self.folder/'task.json').read_bytes()
        p=d.plan(self.state,self.folder,self.request('stop_preserve'));r=d.execute(self.state,self.folder,p['plan_id'])
        self.assertFalse(r['result']['production_modified']);self.assertEqual((self.folder/'task.json').read_bytes(),before)
        self.assertEqual(d.store(self.folder)['status'],'stopped')
    def test_native_checkpoint_requires_selected_tool(self):
        d.enable(self.folder)
        self.state['completed']=['import_netlist','floorplan'];self.state['revision']+=1
        # Actual GCD stage sequence has placement next.
        self.assertTrue(d.needs_decision(self.state,self.folder))
        value={'state_id':task.state_id(self.state),'kind':'summary','facts':{'test':True}}
        eid=task.digest(value);(self.folder/'decision-evidence').mkdir()
        task.save(self.folder/'decision-evidence'/(eid+'.json'),value)
        s=d.store(self.folder);s['observations']=[{'state_id':task.state_id(self.state),'kind':'summary','evidence_id':eid}];d.write(self.folder,s)
        req={'action_id':'gate','tool_id':'ieda_ipl','evidence_id':eid,'decision_state_id':d.token(self.state,s),'reason':'Use admitted placement','expected_effect':'Run incomplete stage','uncertainties':'Quality unknown'}
        with patch('macro_agent.task_queries.features',return_value={'movable_hard_macros':0}), \
             patch('macro_agent.placement_registry.select_tool',return_value={'selected':{'tool_id':'ieda_ipl'},'decision_id':'admission'}):
            d.plan(self.state,self.folder,req)
        self.assertFalse(d.needs_decision(self.state,self.folder))
        self.state['revision']+=1
        self.assertTrue(d.needs_decision(self.state,self.folder))
    def test_changed_evidence_is_rejected(self):
        req=self.request();p=self.folder/'decision-evidence'/(req['evidence_id']+'.json');task.save(p,{'forged':True})
        with self.assertRaisesRegex(ValueError,'CHANGED'):d.plan(self.state,self.folder,req)
    def test_plan_budget(self):
        req=self.request();s=d.store(self.folder);s['budget']['decisions']=0;d.write(self.folder,s)
        with self.assertRaisesRegex(ValueError,'BUDGET'):d.plan(self.state,self.folder,req)
    def test_admission_is_rechecked_before_execution(self):
        p=d.plan(self.state,self.folder,self.request())
        with patch('macro_agent.main_decisions.catalog',return_value={'tools':[]}):
            with self.assertRaisesRegex(ValueError,'NO_LONGER_ELIGIBLE'):d.execute(self.state,self.folder,p['plan_id'])
    def test_changed_implementation_blocks_execution_but_allows_cancel(self):
        p=d.plan(self.state,self.folder,self.request())
        with patch.object(d,'implementation',return_value={'changed':True}):
            with self.assertRaisesRegex(ValueError,'IMPLEMENTATION_CHANGED'):
                d.execute(self.state,self.folder,p['plan_id'])
            d.cancel_plan(self.state,self.folder,p['plan_id'],'Replan against new code')
        self.assertEqual(d.store(self.folder)['plans'][0]['status'],'cancelled')
    def test_stale_plan_cannot_execute(self):
        p=d.plan(self.state,self.folder,self.request());self.state['revision']+=1
        with self.assertRaisesRegex(ValueError,'STALE'):d.execute(self.state,self.folder,p['plan_id'])
    def test_rag_rejects_unreviewed_hash(self):
        from macro_agent.knowledge import retrieve
        original=task.load
        def load(p):
            value=original(p)
            if Path(p).name=='index.json':
                for e in value['entries']:e['sha256']='0'*64
            return value
        with patch('macro_agent.knowledge.task.load',side_effect=load):r=retrieve(self.folder,self.state,'netlist','')
        self.assertEqual(r['status'],'no_match');self.assertTrue(r['excluded'])
    def test_rag_document_version_not_caller_label(self):
        from macro_agent.knowledge import retrieve
        self.state['contract']['backend_version']='unreviewed-new-backend'
        r=retrieve(self.folder,self.state,'netlist','unreviewed-new-backend')
        self.assertEqual(r['status'],'no_match');self.assertTrue(r['excluded'])
    def test_net_terminal_pagination_has_no_lost_endpoints(self):
        from macro_agent.task_queries import query
        self.state['accepted_work']='fixture';self.state['completed']=['import_netlist']
        self.state['results']={'import_netlist':{'artifact':'fixture.def'}}
        design={'nets':{'large':[['u'+str(i),'A'] for i in range(53)]},'units':1000}
        with patch('macro_agent.task_queries.read_def',return_value=design):
            pages=[query(self.state,None,'terminals',offset,20,name='large') for offset in (0,20,40)]
        self.assertEqual(sum(len(p['items']) for p in pages),53)
        self.assertEqual([p['next_cursor'] for p in pages],[20,40,None])

if __name__=='__main__':unittest.main()
