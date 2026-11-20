import hashlib, json, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from macro_agent.main_task import ROOT,dispatch,load,save,clone_workspace


class StorageResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'runs')
        self.folder=Path(self.temp.name)/'task'
        self.view=dispatch({'operation':'start','run':str(self.folder),'case_id':'sky130_gcd'})
    def tearDown(self):self.temp.cleanup()
    def act(self,name,execute=None):
        self.view=dispatch({'operation':'act','run':str(self.folder),'action':name,'action_id':name+'-'+str(time.time_ns()),
            'state_id':self.view['state_id'],'reason':'offline storage test'},execute=execute)
        return self.view
    def accepted(self):
        def fake(stage,work):
            p=work/'result/import_netlist.def';p.write_text('OFFLINE fixture\n')
            return {'artifact':str(p),'test_fixture':True}
        self.act('import_netlist',fake)
    def resume(self,native_names=''):
        with patch('macro_agent.ieda_runtime.invoke',return_value=native_names):
            return dispatch({'operation':'resume','run':str(self.folder),'state_id':self.view['state_id'],'reason':'User requested continuation after repair'})
    def test_resume_preserves_checkpoint_and_budget(self):
        self.accepted();self.act('stop')
        previous=(self.folder/'task.json').read_bytes();counts=self.view['counts'].copy()
        result=self.resume()
        self.assertEqual(result['status'],'running');self.assertEqual(result['counts'],counts)
        self.assertEqual(result['allowed_actions'][0],'floorplan');self.assertFalse(result['goal_certified'])
        event=load(self.folder/'task.json')['events'][-1]
        self.assertEqual(Path(event['checkpoint']['path']).read_bytes(),previous)
        self.assertFalse(event['budgets_reset'])
    def test_tampered_accepted_artifact_rejected(self):
        self.accepted();self.act('stop')
        state=load(self.folder/'task.json');Path(state['results']['import_netlist']['artifact']).write_text('changed')
        with self.assertRaisesRegex(ValueError,'changed'):self.resume()
        self.assertEqual(load(self.folder/'task.json')['status'],'stopped_with_best')
    def test_tampered_receipt_rejected(self):
        self.accepted();self.act('stop');state=load(self.folder/'task.json')
        Path(state['results']['import_netlist']['receipt_ref']).write_text('{}')
        with self.assertRaisesRegex(ValueError,'receipt changed'):self.resume()
    def test_running_native_job_blocks_resume(self):
        self.accepted();self.act('stop')
        with self.assertRaisesRegex(ValueError,'NATIVE_JOB_ACTIVE'):self.resume('aieda-aes-existing\n')
    def test_uncertain_execution_blocks_resume(self):
        self.accepted();self.act('stop');state=load(self.folder/'task.json');state['pending']={'action':'floorplan'};save(self.folder/'task.json',state)
        with self.assertRaisesRegex(ValueError,'uncertain execution'):self.resume()
    def test_original_wall_budget_cannot_be_reset(self):
        self.accepted();self.act('stop');state=load(self.folder/'task.json');state['created_at']=0;save(self.folder/'task.json',state)
        with self.assertRaisesRegex(ValueError,'BUDGET_EXHAUSTED'):self.resume()
    def test_exhausted_execution_budget_cannot_be_reset(self):
        self.accepted();self.act('stop');state=load(self.folder/'task.json');state['counts']['executions']=state['contract']['budget']['executions'];save(self.folder/'task.json',state)
        with self.assertRaisesRegex(ValueError,'BUDGET_EXHAUSTED'):self.resume()
    def test_workspace_failure_never_starts_native_action(self):
        self.accepted();calls=[];before=load(self.folder/'task.json')['accepted_work']
        with patch('macro_agent.main_task.shutil.disk_usage',return_value=SimpleNamespace(free=0)):
            result=self.act('floorplan',lambda s,w:calls.append(s))
        self.assertEqual(calls,[]);self.assertFalse(result['native_execution_started'])
        after=load(self.folder/'task.json');self.assertEqual(after['accepted_work'],before)
        self.assertEqual(after['counts']['executions'],1);self.assertIsNone(after['pending'])
        self.assertEqual(after['events'][-1]['status'],'preparation_failed')
    def test_clone_keeps_content_and_isolates_later_writes(self):
        source=Path(self.temp.name)/'source';source.mkdir();data=b'known fixture\n'*100000
        (source/'data.json').write_bytes(data);target=Path(self.temp.name)/'copy'
        clone_workspace(source,target)
        self.assertEqual((target/'data.json').read_bytes(),data)
        with (target/'data.json').open('ab') as f:f.write(b'changed')
        self.assertEqual((source/'data.json').read_bytes(),data)
        self.assertNotEqual((target/'data.json').read_bytes(),data)
    def test_no_checkpoint_does_not_resume(self):
        self.act('stop')
        with self.assertRaisesRegex(ValueError,'No accepted checkpoint'):self.resume()


if __name__=='__main__':unittest.main()
