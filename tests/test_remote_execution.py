import base64,contextlib,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from macro_agent import remote_client as client,remote_native as native,remote_service as service
from macro_agent import main_task


class RemoteClientTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=client.ROOT/'runs');self.folder=Path(self.temp.name)/'task'
    def tearDown(self):self.temp.cleanup()
    def test_historical_native_execution_never_falls_back(self):
        self.folder.mkdir();p=self.folder/'task.json';p.write_text('{"historical":true}')
        original=p.read_bytes()
        with patch.object(client,'rpc') as rpc:
            with self.assertRaisesRegex(ValueError,'HISTORICAL_LOCAL_TASK'):
                client.dispatch({'mode':'task','operation':'act','action':'routing','run':str(self.folder)})
            rpc.assert_not_called()
        self.assertEqual(p.read_bytes(),original)
    def test_binding_is_stable_across_lost_reply(self):
        a=client.bind(self.folder);b=client.bind(self.folder)
        self.assertEqual(a,b);self.assertFalse((self.folder/'task.json').exists())
    def test_context_retains_verified_delivery_and_rejects_tampering(self):
        self.folder.mkdir();p=self.folder/'final.def';p.write_bytes(b'accepted')
        ref={'path':str(p),'bytes':8,'sha256':hashlib.sha256(b'accepted').hexdigest()}
        client.atomic(self.folder/'remote-delivery.json',{'files':{'remote/final.def':ref},'deliverables':{'final_def':ref}})
        view={'state_id':'s','run':'server/run','goal_certified':True,'final_def':ref}
        self.assertTrue(client.mirror(view,self.folder)['download_verified'])
        p.write_bytes(b'tampered')
        self.assertNotIn('download_verified',client.mirror(view,self.folder))
    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):client.local_folder(client.ROOT/'outside')
    def test_mirror_preserves_server_quality_profile(self):
        self.folder.mkdir()
        view={'state_id':'s','run':'server/run','execution_profile':'ssh-bwrap-quality-v2',
              'quality_feedback':{'status':'residual_drc'}}
        result=client.mirror(view,self.folder)
        self.assertEqual(result['execution_profile'],'ssh-bwrap-quality-v2')
        self.assertEqual(result['quality_feedback']['status'],'residual_drc')
    def test_query_and_rag_results_do_not_overwrite_task_view(self):
        self.folder.mkdir()
        for value in ({'state_id':'s1','hits':[],'status':'no_match'}, {'state_id':'s1','items':[]}, {'state_id':'s1','status':'selected'}):
            self.assertEqual(client.mirror(value,self.folder),value)
        self.assertFalse((self.folder/'remote-view.json').exists())
    def test_tampered_download_never_publishes(self):
        client.bind(self.folder)
        ref={'name':'final.def','path':client.config()['server_root']+'/runs/remote-fixture/final.def','sha256':hashlib.sha256(b'good').hexdigest(),'bytes':4}
        def transfer(*a,**kw):
            (self.folder/'remote-download-pending/final.def').write_bytes(b'evil')
            return SimpleNamespace(returncode=0,stderr='')
        with patch.object(client,'rpc',return_value={'files':[ref],'deliverables':{}}),patch.object(client.subprocess,'run',side_effect=transfer):
            with self.assertRaisesRegex(ValueError,'integrity'):client.download(self.folder,'remote-fixture')
        self.assertFalse((self.folder/'final.def').exists())
    def test_local_attachment_tamper_stops_before_network(self):
        source=Path(self.temp.name)/'input.v';source.write_bytes(b'bad')
        with patch.object(client,'rpc') as rpc:
            with self.assertRaisesRegex(ValueError,'attachment bytes changed'):
                client.dispatch({'mode':'task','operation':'start','run':str(self.folder),
                    'attachment_inputs':[{'path':str(source),'name':'input.v','bytes':3,'sha256':'0'*64}]})
            rpc.assert_not_called()
    def test_verified_staging_resumes_without_retransferring(self):
        client.bind(self.folder);stage=self.folder/'remote-download-pending';stage.mkdir()
        (stage/'final.def').write_bytes(b'good')
        ref={'name':'final.def','path':client.config()['server_root']+'/runs/remote-fixture/final.def','sha256':hashlib.sha256(b'good').hexdigest(),'bytes':4}
        package={'files':[ref],'deliverables':{'final_def':ref}}
        with patch.object(client,'rpc',side_effect=[package,{'state_id':'s','goal_certified':True}]),patch.object(client.subprocess,'run') as transfer:
            result=client.download(self.folder,'remote-fixture')
        transfer.assert_not_called();self.assertEqual((self.folder/'final.def').read_bytes(),b'good')
        self.assertTrue(result['download_verified'])


class NativeTemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        p=self.root/'environments/ieda-export';p.mkdir(parents=True)
        (p/'runtime-manifest.json').write_text('{"image":"export-image"}')
        (self.root/'runs/work').mkdir(parents=True);(self.root/'cases').mkdir()
        self.patcher=patch.object(native,'ROOT',self.root);self.patcher.start()
        from macro_agent.portable_ieda import IMAGE
        self.argv=['run','--rm','--pull=never','--name','aieda-test-123','--network','none','--cpus','4','--memory','8g','--pids-limit','256',
            '--mount',f'type=bind,source={self.root}/cases,target=/reference,readonly',
            '--mount',f'type=bind,source={self.root}/runs/work,target=/work',IMAGE,'timeout','--kill-after=5','120','iEDA','-script','/work/stage.tcl']
    def tearDown(self):self.patcher.stop();self.temp.cleanup()
    def test_reviewed_template(self):self.assertEqual(native.parse(self.argv)['seconds'],120)
    def test_resource_or_shell_escape_rejected(self):
        for old,new in [('8g','16g'),('none','host'),('iEDA','bash'),('120','99999')]:
            argv=[new if s==old else s for s in self.argv]
            with self.assertRaises(ValueError):native.parse(argv)
    def test_input_write_rejected(self):
        with self.assertRaises(ValueError):native.parse([x.replace(',readonly','') for x in self.argv])
    def test_cancel_never_kills_reused_or_foreign_pid(self):
        handles=self.root/'handles';handles.mkdir()
        (handles/'aieda-test-123.json').write_text(json.dumps({'pid':123,'start_ticks':'old'}))
        with patch.dict(native.os.environ,{'AIEDA_NATIVE_HANDLES':str(handles)}),patch.object(native,'identity',return_value=None),patch.object(native.os,'kill') as kill:
            native.control(['kill','aieda-test-123']);kill.assert_not_called()
    def test_management_endpoint_has_no_arbitrary_command(self):
        with self.assertRaisesRegex(ValueError,'Unsupported'):native.control(['exec','bash'])


class ServiceSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.folder=self.root/'runs/remote-fixture';self.folder.mkdir(parents=True)
        self.patches=[patch.object(service,'ROOT',self.root),patch.object(service,'task',main_task),
            patch.object(service,'gate',contextlib.nullcontext),
            patch.object(service,'snapshot',return_value={'state_id':'s1','status':'running','pending':None,'allowed_actions':['routing']})]
        for p in self.patches:p.start()
        self.req={'operation':'act','action':'routing','state_id':'s1','reason':'test','action_id':'stable-id'}
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def test_reply_loss_does_not_duplicate_native_launch(self):
        with patch.object(service.subprocess,'run',return_value=SimpleNamespace(returncode=0,stderr='')) as run:
            first=service.submit(self.folder,self.req);second=service.submit(self.folder,self.req)
            self.assertEqual(first['job']['job_id'],second['job']['job_id']);self.assertTrue(second['replayed']);run.assert_called_once()
    def test_same_key_different_payload_rejected(self):
        with patch.object(service.subprocess,'run',return_value=SimpleNamespace(returncode=0,stderr='')):
            service.submit(self.folder,self.req)
            with self.assertRaisesRegex(ValueError,'COLLISION'):service.submit(self.folder,{**self.req,'reason':'different'})
    def test_replay_lost_worker_does_not_reacquire_scheduler_lock(self):
        depth=0
        @contextlib.contextmanager
        def nonreentrant_gate():
            nonlocal depth
            self.assertEqual(depth,0,'scheduler lock reacquired')
            depth+=1
            try:yield
            finally:depth-=1
        with patch.object(service.subprocess,'run',return_value=SimpleNamespace(returncode=0,stderr='')) as run:
            first=service.submit(self.folder,self.req)
            p=self.folder/'jobs'/(first['job']['job_id']+'.json')
            record=main_task.load(p);record.update(status='running',pid=123,start_ticks='old');main_task.save(p,record)
            with patch.object(service,'gate',nonreentrant_gate),patch.object(native,'identity',return_value=None):
                replay=service.submit(self.folder,self.req)
            self.assertEqual(replay['job']['status'],'lost');run.assert_called_once()
    def test_another_job_does_not_start(self):
        with patch.object(service.subprocess,'run',return_value=SimpleNamespace(returncode=0,stderr='')) as run:
            service.submit(self.folder,self.req)
            with self.assertRaisesRegex(ValueError,'SERVER_BUSY'):service.submit(self.folder,{**self.req,'action_id':'other'})
            run.assert_called_once()
    def test_job_path_traversal_rejected(self):
        with self.assertRaisesRegex(ValueError,'identity'):service.valid_id('../another-task')
    def test_native_stage_and_bulk_run_cannot_bypass_decision_checkpoint(self):
        with patch.object(service,'snapshot',return_value={'state_id':'s1','status':'running','pending':None,
                'allowed_actions':['routing'],'main_decision':{'decision_required':True}}), \
             patch.object(service.subprocess,'run') as launch:
            for operation in ('act','run'):
                with self.assertRaisesRegex(ValueError,'MAIN_DECISION_REQUIRED'):
                    service.submit(self.folder,{**self.req,'operation':operation})
            launch.assert_not_called()
    def test_finish_revalidates_approved_plan_before_dispatch(self):
        from macro_agent import main_decisions
        main_task.save(self.folder/'task.json',{'fixture':True})
        with patch.object(service,'folder_for',return_value=self.folder), \
             patch.object(service,'active',return_value=None), \
             patch.object(main_decisions,'needs_decision',return_value=False), \
             patch.object(main_decisions,'current_plan',return_value={'plan_id':'old'}), \
             patch.object(main_decisions,'selected',side_effect=ValueError('PLAN_IMPLEMENTATION_CHANGED')), \
             patch.object(main_task,'dispatch') as dispatch:
            with self.assertRaisesRegex(ValueError,'IMPLEMENTATION_CHANGED'):
                service.rpc({'task_id':'remote-fixture','operation':'act','action':'finish'})
            dispatch.assert_not_called()


if __name__=='__main__':unittest.main()
