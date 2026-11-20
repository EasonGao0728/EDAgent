import copy
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import core_resource_extension as r
from macro_agent import aes_flow
from macro_agent.main_task import digest
from macro_agent import main_task as task


class ResourceExtensionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.folder=Path(self.tmp.name).resolve()
        self.swap=patch.object(r,'TASK',self.folder);self.swap.start()
        self.original={'contract':{'case_id':'aes_core_sky130_t','goal':'full_backend',
            'all_inputs_hash':'original', 'input_source':'conversation_attachments',
            'budget':{'executions':22,'model_calls':40,'wall_seconds':32400,
                'cpu_threads':4,'memory_gb':8,'container_seconds':21600,
                'host_seconds':21620,'routing_seconds':21600}},
            'created_at':100.,'status':'stopped_with_best','pending':None,
            'revision':1,
            'completed':list(r.PREFIX),'results':{s:{'passed':True} for s in r.PREFIX},
            'failure_counts':{'routing':1},'counts':{'executions':11,'model_calls':14},
            'input_refs':[r.ref(r.BASE)],'events':[{'action':'routing','status':'failed'}],
            'receipts':{'old':{'committed':True}}}
        self.failed={'stage':'routing','passed':False,'timed_out':True,'deadline_seconds':21600}
        for name,data in [('parent.json',self.original),('failed.json',self.failed)]:
            (self.folder/name).write_text(json.dumps(data),encoding='utf-8')
        (self.folder/'runtime.py').write_text(r.extended_source(),encoding='utf-8')
        self.state=copy.deepcopy(self.original)
        a={'authorization':r.AUTHORIZATION,'resumed_at':40000.,'routing_seconds':64800,
           'continuation_seconds':72000,'original_routing_budget_met':False,
           'original_deadline':32500.,'new_deadline':112000.,
           'parent':r.ref(self.folder/'parent.json'),'failed_routing':r.ref(self.folder/'failed.json'),
           'runner_source':r.ref(self.folder/'runtime.py'),'program':r.ref(r.__file__),
           'worker':r.ref(r.ROOT/'tools/dsh_resource_host.py')}
        self.state['resource_continuation']=a
        self.state['contract']['budget']=r.expected_budget(self.original,40000.)
        self.state['input_refs'] += [a['runner_source'],a['program'],a['worker']]
        self.state['contract']['all_inputs_hash']=digest(self.state['input_refs'])

    def tearDown(self):
        self.swap.stop();self.tmp.cleanup()

    def test_preserved_prefix_and_explicit_original_failure(self):
        result=r.validate(self.state,self.folder)
        self.assertTrue(result['passed']);self.assertFalse(result['original_routing_budget_met'])
        self.assertEqual(self.state['counts'],self.original['counts'])

    def test_rejects_mutations_to_evidence_counts_contract_and_results(self):
        changes=[lambda s:s['counts'].update(executions=0),
                 lambda s:s['failure_counts'].update(routing=0),
                 lambda s:s['contract']['budget'].update(memory_gb=16),
                 lambda s:s['results']['placement'].update(passed=False),
                 lambda s:s['events'].clear(),
                 lambda s:s['resource_continuation'].update(new_deadline=999999),
                 lambda s:s['resource_continuation'].update(original_routing_budget_met=True)]
        for change in changes:
            with self.subTest(change=change):
                state=copy.deepcopy(self.state);change(state)
                with self.assertRaises(ValueError):r.validate(state,self.folder)

    def test_active_or_non_timeout_runs_are_ineligible(self):
        for mutation in [lambda s:s.update(pending={'action':'routing'}),
                         lambda s:s.update(status='running'),
                         lambda s:s['failure_counts'].update(routing=2),
                         lambda s:s['completed'].append('routing')]:
            state=copy.deepcopy(self.original);mutation(state)
            with self.assertRaises(ValueError):r.eligible(state,self.failed)
        with self.assertRaises(ValueError):r.eligible(self.original,{**self.failed,'timed_out':False})

    def test_snapshot_allows_only_two_timeout_expressions(self):
        p=Path(self.state['resource_continuation']['runner_source']['path'])
        p.write_text(p.read_text(encoding='utf-8').replace("'--cpus','4'","'--cpus','8'"),encoding='utf-8')
        self.state['resource_continuation']['runner_source']=r.ref(p)
        with self.assertRaisesRegex(ValueError,'two authorized timeout'):r.validate(self.state,self.folder)

    def test_all_native_tcl_scripts_identical(self):
        module=types.ModuleType('macro_agent._resource_test')
        module.__file__=str(r.BASE);module.__package__='macro_agent'
        exec(compile(r.extended_source(),'<tested timeout copy>','exec'),module.__dict__)
        for case in ('aes_sky130_t','aes_legacy','aes_core_sky130_t'):
            m=json.loads((r.ROOT/'cases/ibench'/case/'manifest.json').read_text(encoding='utf-8'))
            for stage in aes_flow.STAGES:
                if stage not in ('validate','gds_export'):
                    self.assertEqual(aes_flow.script(stage,m),module.script(stage,m),(case,stage))

    def test_native_command_changes_only_timeout_not_cpu_memory_or_algorithm(self):
        module=types.ModuleType('macro_agent._resource_command_test')
        module.__file__=str(r.BASE);module.__package__='macro_agent'
        exec(compile(r.extended_source(),'<tested timeout copy>','exec'),module.__dict__)
        work=self.folder/'command-probe';(work/'logs').mkdir(parents=True)
        process=types.SimpleNamespace(returncode=124,poll=lambda:124)
        with patch('macro_agent.ieda_runtime.docker',return_value=['docker']), patch.object(module.subprocess,'Popen',return_value=process) as spawn:
            result=module.execute('routing',work,r.ROOT/'cases/ibench/aes_core_sky130_t')
        command=spawn.call_args.args[0]
        self.assertEqual(command[command.index('--cpus')+1],'4')
        self.assertEqual(command[command.index('--memory')+1],'8g')
        self.assertEqual(command[command.index('timeout')+2],'64800')
        self.assertEqual(command[-2:],['-script','stage.tcl'])
        self.assertFalse(result['passed']);self.assertTrue(result['timed_out'])
        self.assertEqual(result['deadline_seconds'],64800)

    def test_desktop_view_and_package_disclose_original_timeout(self):
        (self.folder/'task.json').write_text(json.dumps(self.state),encoding='utf-8')
        calls=[]
        def base_package(state,folder,backend):
            (folder/'acceptance.json').write_text('{}',encoding='utf-8')
            (folder/'report.html').write_text('<h1>test</h1>',encoding='utf-8')
            return {}
        def base_backend(state):
            return types.SimpleNamespace(STAGES=aes_flow.STAGES,
                execute=lambda stage,work:calls.append(stage) or {'passed':True},package=base_package)
        with patch.object(task,'task_backend',base_backend),patch.object(task,'view',task.view):
            r.install_for_request({'mode':'task','run':str(self.folder),'operation':'observe'})
            view=task.view(self.state,self.folder)
            self.assertFalse(view['original_routing_resource_budget_met'])
            self.assertEqual(view['resource_continuation']['routing_seconds'],64800)
            backend=task.task_backend(self.state)
            self.assertEqual(backend.execute('filler',self.folder),{'passed':True})
            self.assertEqual(calls,['filler'])
            outputs=backend.package(self.state,self.folder,backend)
            self.assertIn('原六小时路由时间预算未通过',(self.folder/'report.html').read_text(encoding='utf-8'))
            self.assertEqual(outputs['report']['sha256'],r.sha(self.folder/'report.html'))
            self.assertFalse(json.loads((self.folder/'acceptance.json').read_text(encoding='utf-8'))['original_routing_resource_budget_met'])


if __name__=='__main__':unittest.main()
