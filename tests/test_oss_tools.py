import unittest
from macro_agent.adapters.toy import load_case
from macro_agent.oss_tools import solve, connectivity, catalog
from macro_agent.evaluator import evaluate
from macro_agent.dsh_host import ROOT

class OSSTests(unittest.TestCase):
    def test_solver_real_cases_independent_legality_and_objective(self):
        for name in ('connected_groups','blocked_channel'):
            case=load_case(ROOT/f'cases/toy/{name}.json')
            batches,info=solve(case)
            self.assertEqual(len(batches),1)
            candidate,record=evaluate(case,batches[0],[m['id'] for m in case['macros'] if not m['fixed']])
            self.assertTrue(record['legal'],record)
            self.assertTrue(record['improved'],record)
            self.assertAlmostEqual(record['after']['weighted_hpwl'],info['objective_hpwl'])
            self.assertEqual([m for m in candidate['macros'] if m['fixed']],[m for m in case['macros'] if m['fixed']])
    def test_catalog_and_graph(self):
        self.assertFalse(next(t for t in catalog()['tools'] if t['tool_id']=='iEDA')['accepts_toy_layout'])
        case=load_case(ROOT/'cases/toy/connected_groups.json')
        result=connectivity(case)
        self.assertEqual(len(result['components']),2)
        self.assertEqual(result['macro_incident_weight']['a'],15)
    def test_reject_fractional_weight(self):
        case=load_case(ROOT/'cases/toy/connected_groups.json');case['nets'][0]['weight']=1.5
        with self.assertRaises(ValueError):solve(case)
    def test_translated_grid_origin(self):
        case=load_case(ROOT/'cases/toy/connected_groups.json')
        case['core']['x']+=3;case['core']['y']+=3
        for item in case['macros']+case['ports']:item['x']+=3;item['y']+=3
        case['grid']=1
        batches,info=solve(case)
        _,record=evaluate(case,batches[0],[m['id'] for m in case['macros'] if not m['fixed']])
        self.assertTrue(record['legal'])
        self.assertAlmostEqual(record['after']['weighted_hpwl'],info['objective_hpwl'])
