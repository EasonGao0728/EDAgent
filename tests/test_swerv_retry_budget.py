import json
from pathlib import Path
import tempfile
import unittest
from macro_agent.swerv_backend import native_deadline,sha,CASE


class RetryBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.task=Path(self.tmp.name)/'remote-example'
        self.work=self.task/'attempts'/'new'
        (self.work/'result').mkdir(parents=True)
        (self.work/'result/legalization.def').write_text('accepted unchanged checkpoint')
        (self.work/'run-start.json').write_text(json.dumps({'time':100}))
        self.extension={'schema_version':'swerv_budget_extension_v1','task_id':self.task.name,
            'case_id':CASE,'issued_at':10000,'expires_at':24400,'routing_seconds':10800,
            'other_stage_seconds':600,'cpu_threads':4,'memory_gb':8,
            'original_budget_failed':True,'authorization':'user requested retry',
            'checkpoint_sha256':sha(self.work/'result/legalization.def')}

    def save(self):
        (self.task/'approved-budget-extension.json').write_text(json.dumps(self.extension))

    def test_old_deadline_is_not_reset(self):
        self.assertEqual(native_deadline('routing',self.work,200),5400)
        with self.assertRaisesRegex(ValueError,'budget exhausted'):native_deadline('routing',self.work,10000)

    def test_explicit_retry_does_not_modify_old_clock(self):
        self.save()
        before=(self.work/'run-start.json').read_bytes()
        self.assertEqual(native_deadline('routing',self.work,10100),10800)
        self.assertEqual(native_deadline('filler',self.work,10100),600)
        self.assertEqual(native_deadline('routing',self.work,24000),390)
        self.assertEqual(before,(self.work/'run-start.json').read_bytes())
        with self.assertRaisesRegex(ValueError,'budget exhausted'):native_deadline('routing',self.work,24400)

    def test_changed_checkpoint_rejected(self):
        self.save();(self.work/'result/legalization.def').write_text('changed')
        with self.assertRaisesRegex(ValueError,'checkpoint changed'):native_deadline('routing',self.work,10100)

    def test_six_hour_approval_preserves_prior_amendment(self):
        self.save();old=(self.task/'approved-budget-extension.json').read_bytes()
        self.extension.update(routing_seconds=21600,expires_at=35200,routing_attempt_limit=3)
        (self.task/'approved-budget-extension-6h.json').write_text(json.dumps(self.extension))
        self.assertEqual(native_deadline('routing',self.work,10100),21600)
        self.assertEqual(native_deadline('drc',self.work,10100),600)
        self.assertEqual((self.task/'approved-budget-extension.json').read_bytes(),old)
        with self.assertRaisesRegex(ValueError,'budget exhausted'):native_deadline('routing',self.work,35200)

    def test_third_attempt_requires_frozen_unexpired_approval(self):
        from unittest.mock import patch
        from macro_agent.main_task import stage_failure_limit,file_ref
        self.extension.update(routing_seconds=21600,expires_at=35200,routing_attempt_limit=3)
        p=self.task/'approved-budget-extension-6h.json';p.write_text(json.dumps(self.extension))
        ref=file_ref(p);s={'contract':{'case_id':CASE},'input_refs':[]}
        self.assertEqual(stage_failure_limit(s,'routing'),2)
        s['contract']['authorized_routing_retry']=ref
        with self.assertRaisesRegex(ValueError,'not frozen'):stage_failure_limit(s,'routing')
        s['input_refs']=[ref]
        with patch('macro_agent.main_task.time.time',return_value=10100):
            self.assertEqual(stage_failure_limit(s,'routing'),3)
            self.assertEqual(stage_failure_limit(s,'placement'),2)
        with patch('macro_agent.main_task.time.time',return_value=35200):
            with self.assertRaisesRegex(ValueError,'expired'):stage_failure_limit(s,'routing')
        p.write_text('{}')
        with self.assertRaisesRegex(ValueError,'changed'):stage_failure_limit(s,'routing')

    def test_changed_limits_or_identity_rejected(self):
        for key,value in [('cpu_threads',8),('routing_seconds',99999),('task_id','different'),
                          ('expires_at',999999),('authorization',''),('original_budget_failed',False)]:
            with self.subTest(key=key):
                original=self.extension[key];self.extension[key]=value;self.save()
                with self.assertRaisesRegex(ValueError,'Invalid audited'):native_deadline('routing',self.work,10100)
                self.extension[key]=original

if __name__=='__main__':unittest.main()
