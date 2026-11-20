import unittest
from macro_agent.placement_registry import select_tool

class DispatcherTests(unittest.TestCase):
    def args(self):
        return dict(stage='macro_placement',format_id='real',required_constraints=['fixed_instances'],
                    movable_hard_macros=2,state_id='s1',budget={'cpu_threads':4,'memory_gb':8,'timeout_seconds':180})
    def card(self):
        return dict(tool_id='ieda_imp',backend='iEDA',stage='macro_placement',formats=['real'],
                    constraints=['fixed_instances'],installed=True,verified=True,cpu_threads=4,memory_gb=8,timeout_seconds=180)
    def test_no_macro_skip_and_unverified_rejection(self):
        a=self.args();a['movable_hard_macros']=0
        self.assertEqual(select_tool(**a,tool_cards=[])['status'],'skip')
        c=self.card();c['verified']=False
        self.assertEqual(select_tool(**self.args(),tool_cards=[c])['status'],'capability_gap')
    def test_constraints_and_resources_not_silently_dropped(self):
        a=self.args();a['required_constraints'].append('halo')
        self.assertEqual(select_tool(**a,tool_cards=[self.card()])['status'],'capability_gap')
        a=self.args();a['budget']['memory_gb']=4
        self.assertIn('insufficient_memory_gb',select_tool(**a,tool_cards=[self.card()])['rejected'][0]['reasons'])
    def test_version_and_state_recorded_for_selected_tool(self):
        c=self.card();c['version']='pinned'
        r=select_tool(**self.args(),tool_cards=[c]);self.assertEqual(r['selected']['version'],'pinned')
        self.assertEqual(r['state_id'],'s1');self.assertTrue(r['decision_id'])

    def test_verified_external_backend_is_still_forbidden(self):
        c=self.card();c.update(tool_id='openroad_hier_rtlmp',backend='OpenROAD')
        r=select_tool(**self.args(),tool_cards=[c])
        self.assertEqual(r['status'],'capability_gap')
        self.assertIn('phase1_backend_forbidden',r['rejected'][0]['reasons'])
