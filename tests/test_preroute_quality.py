import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from macro_agent import hold_policy as h,quality_backend as q,pin_metrics

def candidate(label='skip',hold=-.2,tns=-10,setup=.7,area=100,nets=100,instances=100):
    return {'label':label,'geometry_passed':True,'connectivity_passed':True,
        'timing':{'min_worst_slack_ns':hold,'min_tns_ns':tns,'max_worst_slack_ns':setup,'max_tns_ns':0},
        'measurement':{'standard_cell_area_um2':area,'nets':nets,'instances':instances,'hpwl_um':1000}}

class QualityGateTests(unittest.TestCase):
    def test_native_success_cannot_accept_remaining_hold_violation(self):
        a=candidate();b=candidate('cap05',hold=-.01,tns=-1,area=105,instances=105,nets=105);b['native_exit']=0
        r=h.review([a,b]);self.assertFalse(r['passed']);self.assertIsNone(r['selected']);self.assertIn('hold_not_clean',r['candidates'][1]['rejection_reasons'])
    def test_no_buffers_when_zero_candidate_already_meets_timing(self):
        a=candidate(hold=.01,tns=0);b=candidate('cap05',hold=.05,tns=0,area=105,nets=105)
        self.assertEqual(h.review([a,b])['selected'],'skip')
    def test_select_lowest_cost_only_among_timing_clean_candidates(self):
        a=candidate();b=candidate('cap05',hold=0,tns=0,area=105,nets=105);c=candidate('cap20',hold=.1,tns=0,area=119,nets=119)
        self.assertEqual(h.review([a,b,c])['selected'],'cap05')
    def test_setup_or_cost_regression_not_hidden_by_hold_improvement(self):
        for b,reason in [(candidate('cap05',hold=0,tns=0,setup=-.01),'setup_not_clean'),(candidate('cap20',hold=0,tns=0,area=121),'area_budget_exceeded'),(candidate('cap20',hold=0,tns=0,nets=121),'net_budget_exceeded')]:
            r=h.review([candidate(),b]);self.assertFalse(r['passed']);self.assertIn(reason,r['candidates'][1]['rejection_reasons'])
    def test_unknown_congestion_is_not_passed_drc(self):
        r=h.review([candidate(hold=0,tns=0)])
        self.assertEqual(r['candidates'][0]['congestion'],'unknown_not_measured');self.assertFalse(r['signoff_clean'])
    def test_sta_missing_or_nonfinite_rejected(self):
        with self.assertRaises(ValueError):h.timing('successful exit')
    def test_stage_rejects_without_replacing_source_or_running_routing(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d);(w/'result').mkdir();src=w/'result/to_drv.def';src.write_text('original')
            with patch.object(q,'hold_candidates',return_value={'passed':False,'status':'review_required'}),patch.object(q.b,'execute') as native:
                with self.assertRaisesRegex(ValueError,'HOLD_COST_REVIEW_REQUIRED'):q.execute('to_hold',w,w)
                native.assert_not_called();self.assertEqual(src.read_text(),'original');self.assertFalse((w/'result/to_hold.def').exists())
    def test_routing_cannot_bypass_missing_or_stale_review(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d);(w/'result').mkdir()
            with self.assertRaisesRegex(ValueError,'MISSING'):q.gate_routing(w)
            (w/'result/placement.def').write_text('changed');(w/'result/to_hold.def').write_text('hold')
            (w/'result/hpwl-audit.json').write_text(json.dumps({'passed':True,'measurement':{'sources':[{'sha256':'old'}]}}))
            (w/'result/hold-review.json').write_text(json.dumps({'routing_allowed':True,'complete':True}))
            with self.assertRaisesRegex(ValueError,'HPWL_AUDIT_STALE'):q.gate_routing(w)
    def test_real_study_integer_metric_regression(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/swerv-no-hold-20261115/evidence/imp_fixed-result-placement.def'
        if not p.exists():self.skipTest('local evidence fixture absent')
        lefs=list((root/'cases/ibench/swerv_nangate45/pdk/lef').glob('*.lef'))
        v=pin_metrics.audit(p,lefs,p.parent/'imp_fixed-placement-summary-preserved.json')
        self.assertTrue(v['passed']);self.assertEqual(v['independent_dbu'],272810809)
        with tempfile.TemporaryDirectory() as d:
            s=Path(d)/'wrong.json';s.write_text(json.dumps({'detail_placement':{'hpwl':272810808}}))
            self.assertFalse(pin_metrics.audit(p,lefs,s)['passed'])

    def test_blocked_review_delivers_evidence_not_uncertified_design(self):
        from macro_agent import remote_service as service,main_task
        with tempfile.TemporaryDirectory() as d,patch.object(service,'task',main_task):
            w=Path(d)
            (w/'task.json').write_text(json.dumps({'status':'running'}))
            (w/'quality-review.json').write_text(json.dumps({'status':'review_required'}))
            (w/'quality-review.html').write_text('review')
            (w/'final.def').write_text('must not be delivered')
            r=service.artifacts(w)
            self.assertFalse(r['goal_certified'])
            self.assertEqual({v['name'] for v in r['files']},{'quality-review.json','quality-review.html'})
            self.assertNotIn('final_def',r['deliverables'])
            (w/'quality-review.json').write_text(json.dumps({'status':'running'}))
            with self.assertRaisesRegex(ValueError,'NOT_FINISHED'):service.artifacts(w)

    def test_production_failure_exposes_review_without_repeating_candidates(self):
        from macro_agent import quality_review as qr
        with tempfile.TemporaryDirectory() as d:
            w=Path(d);failed=w/'failed';(failed/'result').mkdir(parents=True)
            r=h.review([candidate()]);r['complete']=True
            (failed/'result/hold-review.json').write_text(json.dumps(r))
            state={'contract':{'case_manifest':{'pre_route_quality_policy':True}},'events':[{'action':'to_hold','status':'failed','work':str(failed)}]}
            src={'placement_def':'x','placement_summary':'y','scope':'current accepted DRV checkpoint'}
            with patch.object(qr,'sources',return_value=src),patch.object(qr,'reference',return_value=w),patch.object(q,'lefs',return_value=[]),patch.object(qr.pin_metrics,'audit',return_value={'passed':True}),patch.object(q,'hold_candidates') as native:
                result=qr.inspect(state,w)
                self.assertFalse(result['can_execute']);self.assertEqual(result['status'],'review_required')
                self.assertEqual(result['source_scope'],src['scope']);native.assert_not_called()
                self.assertTrue((w/'quality-review.html').is_file())

if __name__=='__main__':unittest.main()
