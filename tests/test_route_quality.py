import copy,json,tempfile,unittest
from pathlib import Path
from macro_agent.route_quality import routing_capabilities,compare_candidates,quality_feedback,context_feedback,preservation,audit_stage

class RoutingQualityTests(unittest.TestCase):
    def log(self,n=1):
        return '\n'.join(f'DetailedRouter Begin iteration {i}/{n}\nDetailedRouter End Iteration {i}/{n}' for i in range(1,n+1))
    def record(self):
        return {'input_sha256':'a'*64,'checker_environment_sha256':'b'*64,'artifact_sha256':'c'*64,
            'checked_rules':['metal_short','spacing'],'controls':{'threads':4,'rounds':1},
            'resource_budget':{'route_seconds':1800},'experiment_factor':'top_routing_layer',
            'execution_completed':True,'seconds':10,'structure':{'passed':True,'electrical_connectivity_verified':True},
            'required_capabilities_verified':True,'drc':{'total':10,'by_type':{'metal_short':5,'spacing':5}}}
    def test_requested_flags_are_never_observed_without_evidence(self):
        p=routing_capabilities(self.log(),{'max_dr_iterations':1,'native_layer_tracks':True,'native_graph':'layered'})
        self.assertTrue(p['passed']);self.assertIsNone(p['observed']['native_layer_tracks']);self.assertIsNone(p['native_graph'])
        self.assertEqual(p['repair_actions_enabled'],[])
    def test_missing_or_inconsistent_iteration_logs_fail(self):
        for log in ('', 'DetailedRouter Begin iteration 1/1',self.log(2),'DetailedRouter Begin iteration 2/1\nDetailedRouter End Iteration 2/1'):
            self.assertFalse(routing_capabilities(log,{'max_dr_iterations':1})['passed'])
    def test_early_stop_within_advertised_cap_is_allowed(self):
        self.assertTrue(routing_capabilities(self.log().replace('/1','/6'),{'max_dr_iterations':6})['passed'])
    def test_lower_total_cannot_hide_more_shorts(self):
        a=self.record();b=copy.deepcopy(a);b['drc']={'total':7,'by_type':{'metal_short':6,'spacing':1}}
        r=compare_candidates(a,b);self.assertFalse(r['experimental_improvement']);self.assertFalse(r['eligible_for_reviewed_promotion'])
        self.assertIn('metal_short',r['regressed_rule_types'])
    def test_improvement_without_connectivity_stays_experimental(self):
        a=self.record();b=copy.deepcopy(a);b['drc']={'total':4,'by_type':{'metal_short':2,'spacing':2}};b['structure']['electrical_connectivity_verified']=False
        r=compare_candidates(a,b);self.assertTrue(r['experimental_improvement']);self.assertFalse(r['eligible_for_reviewed_promotion'])
    def test_mismatch_timeout_metadata_bad_counts_and_nan_fail_closed(self):
        for key,val in [('input_sha256','d'*64),('checked_rules',['metal_short']),('execution_completed',False),('seconds',float('nan')),('seconds',1801),('structure',{'passed':False}),('drc',{'total':0,'by_type':{'metal_short':1}})]:
            a=self.record();b=copy.deepcopy(a);b[key]=val
            with self.subTest(key=key,val=val):self.assertFalse(compare_candidates(a,b)['comparable'])
    def test_clean_without_valid_counts_or_execution_not_accepted(self):
        for gate in ({},{'passed':True,'quality_clean':True},{'passed':True,'quality_clean':True,'violation_count':True},{'passed':False,'quality_clean':True,'violation_count':0}):
            self.assertFalse(quality_feedback(gate)['supported_drc_clean'])
        r=quality_feedback({'passed':True,'violation_count':10,'quality_clean':False})
        self.assertTrue(r['execution_verified']);self.assertEqual(r['status'],'residual_drc');self.assertFalse(r['automatic_promotion_enabled'])
    def test_historical_false_claim_is_sanitized_without_rewriting(self):
        state={'results':{'routing':{'routing_profile':{'native_layer_tracks':True,'native_graph':'layered'}}}}
        old=copy.deepcopy(state);r=context_feedback(state);self.assertIsNone(r['routing_capabilities']['observed']['native_graph']);self.assertEqual(state,old)
    def test_real_snapshot_preserves_metadata(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/ieda-rootcause-20261112/neighborhood-308-snapshot.def'
        if not p.exists():self.skipTest('Local real fixture unavailable')
        r=preservation(p,p);self.assertTrue(r['passed']);self.assertFalse(r['electrical_connectivity_verified'])
        with tempfile.TemporaryDirectory() as t:
            q=Path(t)/'changed.def';q.write_text(p.read_text().replace('pdn_generator','wrong_generator'))
            self.assertFalse(preservation(p,q)['passed'])

if __name__=='__main__':unittest.main()
