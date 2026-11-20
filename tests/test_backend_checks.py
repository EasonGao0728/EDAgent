import copy
import json
from pathlib import Path
import tempfile
import unittest
from macro_agent.backend_checks import routing_gate,drc_gate,transformation_check,route_records,io_policy_check,pdn_policy_check
from macro_agent.main_task import ROOT,dispatch,load

class BackendTests(unittest.TestCase):
    def test_pdn_width_contract_rejects_missing_power_net_and_wrong_geometry(self):
        rule={'widths_dbu':{'met1':460,'met4':3200,'met5':3200}}
        records=[n+' + ROUTED met1 460 NEW met4 3200 NEW met5 3200 NEW met2 0' for n in ('VDD','VSS')]
        check=lambda r:pdn_policy_check({'physical':{'SPECIALNETS':r}},rule)['passed']
        self.assertTrue(check(records))
        self.assertFalse(check(records[:1]))
        self.assertFalse(check([r.replace('met1 460','met1 480') for r in records]))
        self.assertFalse(check([r+' NEW met2 1000' for r in records]))
    def test_frozen_io_layer_and_rectangle_are_enforced(self):
        rule={'allowed_layers':['met3','met4'],'width_dbu':800,'height_dbu':800}
        d={'pins':{'a':'a + NET a + PORT + LAYER met3 ( -400 -400 ) ( 400 400 ) + PLACED ( 1000 1000 ) N'}}
        self.assertTrue(io_policy_check(d,rule)['passed'])
        for old,new in [('met3','met5'),('( 400 400 )','( 399 400 )'),('+ LAYER met3','+ UNKNOWN met3')]:
            self.assertFalse(io_policy_check({'pins':{'a':d['pins']['a'].replace(old,new)}},rule)['passed'])
    def test_false_route_flag_overrules_successful_routed_net_count(self):
        s={'route_complete':False,'dr_summary':{'total_net_num':10,'routed_net_num':10}}
        self.assertFalse(routing_gate(s)['passed'])
        s['route_complete']=True;self.assertTrue(routing_gate(s)['passed'])
        self.assertFalse(routing_gate({**s,'stage_ledger':[{'failed':True}]})['passed'])
        self.assertFalse(routing_gate({**s,'stage_ledger':[{'entered':True,'completed':False}]})['passed'])
        s['dr_summary']['routed_net_num']=9;self.assertFalse(routing_gate(s)['passed'])
    def test_drc_missing_dirty_and_unexecuted_never_pass(self):
        good={'status':'partial_clean','violation_count':0,'execution_started':True,'checked':['metal_short'],'unsupported':['other']}
        self.assertTrue(drc_gate(good)['passed']);self.assertFalse(drc_gate(good)['signoff_clean'])
        for bad in ({},{**good,'violation_count':9},{**good,'execution_started':False},{**good,'violation_count':False},{**good,'skipped':['metal_short']}):
            self.assertFalse(drc_gate(bad)['passed'])
        self.assertFalse(drc_gate({**good,'runtime':{'per_rule':{'minimum_area':{'violation_count':3}}}})['passed'])
    def sample(self):
        return dict(design='g',units=1000,die=[0,0,100,100],pins={},components={'u':{'master':'ff','placement':['PLACED',0,0,'N']}},nets={'clk':[('PIN','clk'),('u','CLK')],'d':[('PIN','d'),('u','D')]})
    def cts(self):
        b=self.sample();a=copy.deepcopy(b);a['components']['b']={'master':'sky130_fd_sc_hd__buf_1','placement':['PLACED',10,0,'N']}
        a['nets']['clk']=[('PIN','clk'),('b','A')];a['nets']['clk_b']=[('b','X'),('u','CLK')]
        return b,a
    def test_clock_tree_valid_and_missing_sink_rejected(self):
        b,a=self.cts();self.assertTrue(transformation_check(b,a,'cts')['passed'])
        a['nets']['clk_b'].remove(('u','CLK'));self.assertFalse(transformation_check(b,a,'cts')['passed'])
    def test_clock_bridge_to_data_or_multiple_nets_rejected(self):
        b,a=self.cts();a['nets']['d'].append(('b','A'));self.assertFalse(transformation_check(b,a,'cts')['passed'])
    def test_clock_cycle_and_unapproved_cell_rejected(self):
        b,a=self.cts();a['components']['b']['master']='arbitrary_logic';self.assertFalse(transformation_check(b,a,'cts')['passed'])
        b,a=self.cts();a['nets']['clk'].append(('b','X'));self.assertFalse(transformation_check(b,a,'cts')['passed'])
    def test_route_cannot_move_original_cells(self):
        b=self.sample();a=copy.deepcopy(b);a['components']['u']['placement'][1]=10
        for stage in ('routing','filler','drc','routed_readback'):
            self.assertFalse(transformation_check(b,a,stage)['passed'])
        self.assertTrue(transformation_check(b,a,'legalization')['passed'])
        b['components']['u']['placement'][0]='FIXED';self.assertFalse(transformation_check(b,a,'legalization')['passed'])
    def test_wire_tamper_detected_even_if_endpoints_unchanged(self):
        with tempfile.TemporaryDirectory() as t:
            a=Path(t)/'a.def';b=Path(t)/'b.def'
            a.write_text('NETS 1 ;\n- n ( u A ) + ROUTED met1 ( 0 0 ) ( 10 0 ) ;\nEND NETS\n')
            b.write_text(a.read_text().replace('( 10 0 )','( 11 0 )'))
            self.assertNotEqual(route_records(a),route_records(b))
    def test_registered_experimental_goal_keeps_separate_contract_and_rejects_finish(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'runs') as t:
            req={'run':t,'operation':'start','case_id':'ibench_gcd_legacy','goal':'routed_def'}
            s=dispatch(req);self.assertEqual(len(s['plan']),11);self.assertFalse(s['overall_phase1_certified'])
            self.assertTrue(s['contract']['experimental'])
            self.assertEqual(s['contract']['approved_logical_transformations']['cts']['clock_net'],'clk')
            self.assertIn('route_complete',s['contract']['required_backend_gates'])
            self.assertEqual(s['contract']['case_manifest']['io_rule']['allowed_layers'],['met3','met4'])
            self.assertEqual(s['contract']['case_manifest']['pdn_rule']['widths_dbu']['met1'],460)
            with self.assertRaisesRegex(ValueError,'another goal'):dispatch({**req,'goal':'placement_def'})
            with self.assertRaisesRegex(ValueError,'not allowed'):dispatch({'run':t,'operation':'act','action':'finish','action_id':'f','state_id':s['state_id'],'reason':'test'})
            self.assertEqual(dispatch({'run':t,'operation':'retrieve','query':'routing gate'})['status'],'matched')
    def test_rejected_route_or_final_drc_preserves_accepted_state(self):
      for failed_stage,completed_count in [('routing',7),('drc',9)]:
        with self.subTest(stage=failed_stage),tempfile.TemporaryDirectory(dir=ROOT/'runs') as t:
            s=dispatch({'run':t,'operation':'start','case_id':'ibench_gcd_legacy','goal':'routed_def'})
            def fixture(stage,work):
                if stage==failed_stage:raise ValueError('controlled backend quality rejection')
                return {'fixture_only':True}
            for n in range(completed_count):
                s=dispatch({'run':t,'operation':'act','action':s['allowed_actions'][0],
                    'action_id':str(n),'state_id':s['state_id'],'reason':'offline control test'},execute=fixture)
            old=load(Path(t)/'task.json')['accepted_work'];self.assertEqual(s['allowed_actions'][0],failed_stage)
            for n in range(2):
                s=dispatch({'run':t,'operation':'act','action':failed_stage,'action_id':'bad'+str(n),
                    'state_id':s['state_id'],'reason':'controlled failure'},execute=fixture)
                self.assertEqual(load(Path(t)/'task.json')['accepted_work'],old)
                self.assertFalse(s['goal_certified']);self.assertNotIn('finish',s['allowed_actions'])
            self.assertEqual(s['status'],'failed')

if __name__=='__main__':unittest.main()
