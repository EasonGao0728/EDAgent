import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from macro_agent.main_task import dispatch, ROOT, load, save

class TaskTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'runs')
        self.run=str(Path(self.temp.name)/'task')
        self.state=dispatch({'run':self.run,'operation':'start','case_id':'sky130_gcd'})
    def tearDown(self): self.temp.cleanup()
    def act(self,action,identity='a',execute=None,state_id=None):
        self.state=dispatch({'run':self.run,'operation':'act','action':action,'action_id':identity,
                             'state_id':state_id or self.state['state_id'],'reason':'test'},execute=execute)
        return self.state
    def test_stale_and_out_of_order_rejected_without_execution(self):
        with self.assertRaisesRegex(ValueError,'STALE'): self.act('import_netlist',state_id='old')
        with self.assertRaisesRegex(ValueError,'not allowed'): self.act('placement')
        self.assertFalse(self.state['contract']['maker_enabled'])
    def test_duplicate_action_does_not_execute_twice(self):
        calls=[];original=self.state['state_id']
        def execute(stage,work): calls.append(stage);return {'test_fixture':True}
        self.act('import_netlist',execute=execute)
        result=self.act('import_netlist',state_id=original,execute=execute)
        self.assertTrue(result['replayed_receipt']);self.assertEqual(calls,['import_netlist'])
    def test_failed_stage_preserves_accepted_state_and_two_failures_stop(self):
        def fail(stage,work): raise RuntimeError('controlled tool failure')
        first=self.act('import_netlist','a',fail)
        self.assertTrue(first['accepted_state_preserved']);self.assertEqual(first['counts']['executions'],1)
        self.act('import_netlist','b',fail)
        self.assertEqual(self.state['status'],'failed');self.assertFalse(self.state['goal_certified'])
    def test_failed_attempt_evidence_is_bounded_readonly_and_not_accepted(self):
        def fail(stage,work):
            (work/'logs'/f'{stage}.log').write_text('old line\n'*10000+'Docker Engine unavailable\n',encoding='utf-8')
            raise RuntimeError('iEDA import_netlist exited 1')
        self.act('import_netlist','failure-log',fail)
        before=(Path(self.run)/'task.json').read_bytes()
        result=dispatch({'run':self.run,'operation':'query','kind':'evidence','stage':'import_netlist','limit':2})
        self.assertFalse(result['accepted']);self.assertEqual(result['status'],'failed_attempt')
        self.assertTrue(result['tail_only']);self.assertEqual(result['items'][0],'Docker Engine unavailable')
        self.assertEqual(len(result['items']),2);self.assertIsNotNone(result['next_cursor'])
        self.assertEqual((Path(self.run)/'task.json').read_bytes(),before)
        self.assertEqual(load(Path(self.run)/'task.json')['completed'],[])
    def test_failed_evidence_missing_log_is_explicit_and_arbitrary_stages_are_rejected(self):
        def fail(stage,work):raise RuntimeError('failed before logger opened')
        self.act('import_netlist','no-log',fail)
        request={'run':self.run,'operation':'query','kind':'evidence','stage':'import_netlist'}
        result=dispatch(request)
        self.assertFalse(result['log_available']);self.assertFalse(result['accepted'])
        with self.assertRaisesRegex(ValueError,'Unknown evidence stage'):
            dispatch({**request,'stage':'../../outside'})
    def test_crash_recovers_as_uncertain_then_new_workspace(self):
        def crash(stage,work): raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt): self.act('import_netlist',execute=crash)
        self.state=dispatch({'run':self.run,'operation':'observe'})
        self.assertEqual(self.state['phase'],'UNCERTAIN');old=self.state['pending']['work']
        self.act('recover','recover');self.assertEqual(self.state['counts']['executions'],1)
        result=self.act('import_netlist','b',lambda stage,work:{'work_used':str(work)})
        self.assertNotEqual(old,result['latest_evidence']['work_used'])
    def test_budgets_and_stop_cannot_certify_goal(self):
        path=Path(self.run)/'task.json';state=load(path)
        state['counts']['model_calls']=state['contract']['budget']['model_calls'];save(path,state)
        with self.assertRaisesRegex(ValueError,'TASK_MODEL_BUDGET'):
            dispatch({'run':self.run,'operation':'reserve_model'})
        self.act('stop');self.assertFalse(self.state['goal_certified'])
    def test_recovery_does_not_race_a_possibly_running_container(self):
        import time
        def crash(stage,work):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.act('import_netlist',execute=crash)
        path=Path(self.run)/'task.json';s=load(path);s['pending']['safe_retry_after']=time.time()+200;save(path,s)
        self.state=dispatch({'run':self.run,'operation':'observe'})
        r=self.act('recover','recover')
        self.assertIn('EXECUTION_UNCERTAIN',r['action_error']);self.assertIsNotNone(r['pending'])
        self.assertEqual(r['counts']['executions'],1)
    def test_rag_incompatible_empty_and_snapshot(self):
        req={'run':self.run,'operation':'retrieve','query':'netlist readback'}
        self.assertEqual(dispatch({**req,'backend_version':'wrong'})['status'],'incompatible_version')
        r=dispatch(req);self.assertTrue(r['hits']);self.assertTrue(Path(r['evidence_ref']).is_file())
        self.assertEqual(dispatch({**req,'query':'nonsense_77123'})['status'],'no_match')
    def test_mutated_input_fails_closed(self):
        with patch('macro_agent.main_task.verify_refs',side_effect=ValueError('Artifact/input changed')):
            with self.assertRaisesRegex(ValueError,'changed'): self.act('import_netlist')
    def test_existing_task_cannot_silently_change_case(self):
        with self.assertRaisesRegex(ValueError,'unsupported_case'):
            dispatch({'run':self.run,'operation':'start','case_id':'nangate_macro_smoke'})
        with self.assertRaisesRegex(ValueError,'already bound'):
            dispatch({'run':self.run,'operation':'start','case_id':'ibench_gcd_legacy'})
    def test_registered_hd_case_keeps_inputs_separate_from_hs(self):
        from macro_agent.ieda_stages import for_case
        hd = for_case('ibench_gcd_legacy')
        hs = for_case('sky130_gcd')
        hd_files = hd.input_files()
        self.assertTrue(all(p.is_file() for p in hd_files))
        self.assertIn('sky130_fd_sc_hd', hd.manifest()['cell_lefs'][0])
        self.assertIn('sky130_fd_sc_hs', hs.manifest()['cell_lefs'][0])
        self.assertTrue(set(hd_files).isdisjoint(hs.input_files()))
        other = str(Path(self.temp.name)/'hd-task')
        state = dispatch({'run':other,'operation':'start','case_id':'ibench_gcd_legacy'})
        self.assertEqual(state['contract']['case_manifest']['core_site'], 'unithd')
        self.assertEqual(state['contract']['case_manifest']['format_id'], 'ibench_gcd_legacy_v1')
        self.assertEqual(state['allowed_actions'][0], 'import_netlist')
        self.assertEqual(for_case('sky130_gcd').manifest()['case_id'], 'sky130_gcd')
    def test_history_query_and_bad_cursor(self):
        self.act('stop')
        req={'run':self.run,'operation':'query','kind':'events','limit':1}
        r=dispatch(req);self.assertEqual(r['total'],1);self.assertEqual(r['state_id'],self.state['state_id'])
        with self.assertRaisesRegex(ValueError,'cursor/limit'):dispatch({**req,'limit':10000})
