import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from macro_agent import feedback_control as f, p1_perception as p, main_task as task
from macro_agent import remote_client

class PerceptionTests(unittest.TestCase):
    def test_comparison_reply_keeps_failed_candidate_counts_and_no_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            value={'branch_id':'b','conclusion':'candidate_evaluation_failed_reject','adopted':False,'baseline':{'count':0,'count_consistent':True},'candidate':{'stage_accepted':False,'count':None,'reported_counts':{'canonical':0,'runtime_rule_sum':2}},'candidate_stage':{'metrics':{'hpwl':1},'gates':{'large':'x'*10000}},'baseline_stage':{'metrics':{'hpwl':2}}}
            result=remote_client.model_reply(value,Path(tmp))
            self.assertEqual(result['conclusion'],value['conclusion']);self.assertFalse(result['adopted'])
            self.assertIsNone(result['candidate']['count']);self.assertEqual(result['candidate']['reported_counts']['runtime_rule_sum'],2)
            self.assertEqual(task.load(Path(result['full_snapshot_ref']['path'])),value)
    def test_large_insertion_list_is_referenced_without_hiding_gate_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate={'passed':False,'errors':['bad transform'],'added_instances':[str(i) for i in range(100)]}
            value={'contract':{},'feedback_campaign':{'branches':[{'latest_observation':{'gates':{'transformation':gate}}}]}}
            result=remote_client.model_context(value,Path(tmp));g=result['feedback_campaign']['branches'][0]['latest_observation']['gates']['transformation']
            self.assertFalse(g['passed']);self.assertEqual(g['errors'],['bad transform']);self.assertEqual(g['added_instances_summary']['count'],100)
            self.assertEqual(len(task.load(Path(result['full_snapshot_ref']['path']))['feedback_campaign']['branches'][0]['latest_observation']['gates']['transformation']['added_instances']),100)
    def test_delivery_reply_retains_cards_and_exact_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            value={'status':'target_met','download_verified':True,'deliverables':{'feedback_report':{'path':'report.html','sha256':'abc'}},'contract':{'old_transport':'x'*20000}}
            result=remote_client.model_reply(value,Path(tmp))
            self.assertEqual(result['deliverables'],value['deliverables']);self.assertTrue(result['download_verified'])
            self.assertEqual(task.load(Path(result['full_snapshot_ref']['path'])),value)
            self.assertNotIn('contract',result)
    def test_failed_drc_counter_conflict_is_never_reported_as_zero_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'runs/b/attempts/fail';(work/'result/report').mkdir(parents=True)
            task.save(work/'backend-checks.json',{'drc_gate':{'passed':False,'violation_count':0,'errors':['drc_counter_discrepancy_requires_review'],'runtime':{'per_rule':{'minimum_area':{'violation_count':2}}}}})
            task.save(work/'result/report/violations.json',{'count':0,'summary':{'total':0},'violations':[]})
            with patch.object(task,'ROOT',root):result=p.hotspots({'completed':[],'events':[{'action':'drc','status':'failed','work':str(work)}]})
            self.assertIsNone(result['count']);self.assertFalse(result['stage_accepted']);self.assertFalse(result['count_consistent'])
            self.assertEqual(result['reported_counts']['canonical'],0);self.assertEqual(result['reported_counts']['runtime_rule_sum'],2)
            self.assertNotIn('hotspots',result);task.verify_refs(result['sources'])
    def test_context_projection_keeps_constraints_and_current_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            value={'plan':['frozen_parent_plan'],'contract':{'hard_constraints':['fixed macro'],'budget':{'executions':32},'attachment_import':{'files':[{'name':'n','sha256':'abc','source_local_path':'duplicate'}]}},'feedback_campaign':{'events':[{'action':'observed','metrics':{'big':'old'},'reason':'old'}],'branches':[{'latest_observation':{'metrics':{'drc':2}}}]}}
            result=remote_client.model_context(value,Path(tmp))
            self.assertEqual(result['contract']['hard_constraints'],['fixed macro'])
            self.assertEqual(result['feedback_campaign']['branches'],value['feedback_campaign']['branches'])
            self.assertNotIn('plan',result);self.assertIn('plan',result['frozen_baseline_details']['fields'])
            self.assertEqual(task.load(Path(result['full_snapshot_ref']['path'])),value)
            task.verify_refs([result['full_snapshot_ref']])
    def test_observation_projection_keeps_evidence_identity_and_marks_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            value={'contract':{},'feedback_campaign':{'branches':[{'latest_observation':{'stage':'legalization','metrics':{'n':3}},'observations':{'stage:legalization':{'current':True,'evidence_id':'new','facts':{'stage':'legalization','metrics':{'n':3}}},'stage:placement':{'current':False,'evidence_id':'old','full_record':'old.json','facts':{'metrics':{'n':2}}}}}]}}
            branch=remote_client.model_context(value,Path(tmp))['feedback_campaign']['branches'][0]
            self.assertEqual(branch['observations']['stage:legalization']['evidence_id'],'new')
            self.assertIn('facts_ref',branch['observations']['stage:legalization'])
            self.assertEqual(branch['observations']['stage:placement']['full_record'],'old.json')
            self.assertIn('facts_scope',branch['observations']['stage:placement'])
            self.assertEqual(branch['latest_observation']['metrics']['n'],3)
    def test_job_reply_retains_exact_receipt_without_duplicate_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            value={'job':{'job_id':'durable'},'task':{'state_id':'parent','contract':{},'feedback_campaign':{'campaign_state_id':'c','counts':{},'branches':[{'branch_id':'b','state_id':'s','latest_observation':'x'*30000}]}}}
            result=remote_client.model_reply(value,Path(tmp));ref=result['task']['full_snapshot_ref']
            self.assertLess(len(json.dumps(result)),2000)
            task.verify_refs([ref]);self.assertEqual(task.load(Path(ref['path'])),value)
            self.assertEqual(result['task']['feedback_campaign_ref']['branches'][0]['state_id'],'s')
    def test_stream_large_and_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'markers.json';data={'count':6000,'summary':{'total':6000},'violations':[{'type':'metal_short','bbox':[0,0,1,1]}]*6000}
            path.write_text(json.dumps(data));rows=list(p.marker_stream(path));self.assertEqual(len(rows),6001)
            path.write_text('{"count":1,"violations":[{"type":"x"')
            with self.assertRaisesRegex(ValueError,'TRUNCATED'):list(p.marker_stream(path))
    def test_unknown_is_never_measured(self):
        self.assertEqual(p.measurement(None,'um')['kind'],'unknown')
    def test_only_density_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'config').mkdir();path=root/'config/pl_default_config.json'
            original={'PL':{'GP':{'Density':{'target_density':.6,'bin_cnt_x':16}},'DP':{'enable':1}}}
            task.save(path,original);effect=f.apply_adjustment(root,{'density':.55});changed=task.load(path)
            self.assertEqual(changed['PL']['GP']['Density']['target_density'],.55)
            changed['PL']['GP']['Density']['target_density']=.6;self.assertEqual(changed,original)
            self.assertEqual(effect['before'],.6)
            with self.assertRaisesRegex(ValueError,'UNREVIEWED'):f.apply_adjustment(root,{'density':.1})
    def test_native_adjustment_is_not_configuration_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);log=root/'placement.log';log.write_text('Target Density : 0.659264\n')
            s={'results':{'placement':{'log':str(log),'receipt_ref':str(root/'receipt.json'),'parameter_effect':{'requested':.65,'native_log':task.file_ref(log)}}}}
            result=p.density_evidence(s);self.assertEqual(result['native_reported'],.659264)
            self.assertFalse(result['request_matches_native_report'])
            log.write_text('Target Density : 0.65\n')
            with self.assertRaisesRegex(ValueError,'changed'):p.density_evidence(s)

class BranchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.runs=self.root/'runs';self.runs.mkdir();self.folder=self.runs/'remote-parent001';self.folder.mkdir()
        self.work=self.folder/'attempts/fanout';(self.work/'config').mkdir(parents=True);(self.work/'result').mkdir()
        task.save(self.work/'config/pl_default_config.json',{'PL':{'GP':{'Density':{'target_density':.6}}}})
        (self.work/'result/fanout.def').write_text('native fixture')
        self.result={'artifact':str(self.work/'result/fanout.def'),'artifact_refs':[task.file_ref(self.work/'result/fanout.def')], 'receipt_ref':str(self.work/'receipt.json')};task.save(self.work/'receipt.json',self.result)
        self.state={'contract':{'case_id':'ibench_gcd_legacy','goal':'full_backend','backend_version':'v1','budget':{'wall_seconds':3600,'executions':22}},'revision':0,'completed':['import_netlist','floorplan','fanout'],'results':{k:self.result for k in ['import_netlist','floorplan','fanout']},'input_refs':[],'status':'target_met','pending':None,'counts':{'executions':3,'model_calls':0},'accepted_work':str(self.work),'events':[]}
        task.save(self.folder/'task.json',self.state)
        self.rootpatch=patch.object(task,'ROOT',self.root);self.rootpatch.start()
        self.bp=patch.object(task,'task_backend',return_value=SimpleNamespace(STAGES=['import_netlist','floorplan','fanout','placement','validate','export_def','routing','drc']));self.bp.start()
        self.vp=patch.object(task,'view',side_effect=lambda s,p:{'allowed_actions':['placement','stop'] if s['status']=='running' else []});self.vp.start()
        self.pp=patch.object(p,'physical_sources',return_value=(self.root,{},[]));self.pp.start()
        self.ip=patch.object(p,'input_profile',return_value={'metrics':{'nominal_area_utilization':{'value':.4}}});self.ip.start()
        self.sp=patch.object(task,'start',side_effect=self.start);self.sp.start()
        f.begin(self.state,self.folder,{'reason':'user authorized feedback'})
        e={'kind':'stage','state_id':task.state_id(self.state),'facts':{}}
        self.eid=task.digest(e);(self.folder/'feedback-evidence').mkdir();task.save(self.folder/'feedback-evidence'/(self.eid+'.json'),e)
    def tearDown(self):
        for p in [self.rootpatch,self.bp,self.vp,self.pp,self.ip,self.sp]:p.stop()
        self.tmp.cleanup()
    def start(self,dest,case_id,goal):
        s=copy.deepcopy(self.state);s.update(status='running',completed=[],results={},events=[],counts={'executions':0,'model_calls':0});task.save(dest/'task.json',s)
    def request(self,**kw):
        return {'campaign_state_id':f.view(self.folder)['campaign_state_id'],'action_id':'branch-one','evidence_id':self.eid,'density':.55,'reason':'check density hypothesis','expected_effect':'unknown; test',**kw}
    def test_branch_preserves_parent_and_only_imports_prefix(self):
        before=(self.folder/'task.json').read_bytes();r=f.branch(self.state,self.folder,self.request());b=r['branches'][0];s=task.load(self.runs/b['branch_id']/'task.json')
        self.assertEqual(before,(self.folder/'task.json').read_bytes());self.assertEqual(s['completed'],self.state['completed']);self.assertEqual(s['counts']['executions'],0)
        self.assertNotIn('placement',s['results']);self.assertEqual(b['adjustment']['restart_stage'],'placement')
        r2=f.branch(self.state,self.folder,self.request());self.assertEqual(r2['counts']['branches'],1)
    def test_stale_evidence_and_changed_artifact_rejected(self):
        epath=self.folder/'feedback-evidence'/(self.eid+'.json');epath.write_text('{}')
        with self.assertRaisesRegex(ValueError,'STALE_OR_CHANGED'):f.branch(self.state,self.folder,self.request())
    def test_noop_and_unreviewed_changes_rejected(self):
        with self.assertRaisesRegex(ValueError,'NO_PARAMETER_CHANGE'):f.branch(self.state,self.folder,self.request(density=.6))
        with self.assertRaisesRegex(ValueError,'UNREVIEWED'):f.branch(self.state,self.folder,self.request(density=.8))
    def test_parent_change_stops_campaign(self):
        request=self.request()
        task.save(self.folder/'task.json',{})
        with self.assertRaisesRegex(ValueError,'changed'):f.branch(self.state,self.folder,request)
    def test_observations_survive_compaction_and_expose_staleness(self):
        with patch.object(p,'stage_observation',return_value={'stage':'placement','placement_parameter':{'native_reported':.659264},'large_detail':'omitted'}):
            result=f.inspect(self.state,self.folder,'stage','placement')
        summary=f.view(self.folder)['observations']['stage:placement']
        self.assertEqual(summary['evidence_id'],result['evidence_id'])
        self.assertTrue(summary['current']);self.assertNotIn('large_detail',summary['facts'])
        changed=copy.deepcopy(self.state);changed['revision']+=1
        self.assertFalse(f.observation_index(self.folder,changed)['stage:placement']['current'])
    def test_identity_collision_and_shared_budget(self):
        f.branch(self.state,self.folder,self.request())
        with self.assertRaisesRegex(ValueError,'COLLISION'):f.branch(self.state,self.folder,self.request(density=.5))
        c=f.load(self.folder);c['counts']['branches']=2;f.save(self.folder,c)
        with self.assertRaisesRegex(ValueError,'BRANCH_BUDGET'):f.branch(self.state,self.folder,self.request(action_id='new'))
    def test_low_area_target_and_path_escape_rejected(self):
        with patch.object(p,'input_profile',return_value={'metrics':{'nominal_area_utilization':{'value':.574}}}):
            with self.assertRaisesRegex(ValueError,'DENSITY_BELOW'):f.branch(self.state,self.folder,self.request(density=.55))
        with self.assertRaisesRegex(ValueError,'INVALID_EVIDENCE'):f.branch(self.state,self.folder,self.request(evidence_id='../outside'))

class ComparisonTests(unittest.TestCase):
    def test_regression_never_promotes_or_modifies_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);parent=root/'parent';parent.mkdir();child=root/'runs/remote-child001';child.mkdir(parents=True)
            s={'contract':{},'completed':['placement','drc'],'results':{},'status':'target_met'};task.save(parent/'task.json',s);task.save(child/'task.json',s)
            task.save(parent/f.FILE,{'baseline_task':task.file_ref(parent/'task.json'),'branches':[{'branch_id':child.name}],'events':[],'revision':0})
            before=(parent/'task.json').read_bytes()
            base={'count_consistent':True,'count':3,'by_rule':{'short':3},'coverage':{'checked':['short']}}
            candidate={**base,'count':4,'by_rule':{'short':4}}
            with patch.object(task,'ROOT',root),patch.object(p,'hotspots',side_effect=[base,candidate]),patch.object(p,'physical_sources',return_value=(root,{},[])),patch.object(p,'stage_observation',return_value={}):
                result=f.compare(s,parent,child.name)
            self.assertEqual(result['conclusion'],'quality_regression_reject');self.assertFalse(result['adopted']);self.assertFalse(result['supported_drc_improvement'])
            self.assertEqual(before,(parent/'task.json').read_bytes())

if __name__=='__main__':unittest.main()
