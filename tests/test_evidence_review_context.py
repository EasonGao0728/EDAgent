"""Read-only conversation budgets must never enable native task actions."""
import tempfile
import time
import unittest
import json
from pathlib import Path
from unittest.mock import patch
from macro_agent import remote_client as client


class EvidenceReviewTests(unittest.TestCase):
    def test_budget_is_bounded_and_cannot_execute_or_rebind(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            binding={'purpose':'evidence_review','review_created_at':time.time()}
            for op in ['run','act','start','open','quality_execute','feedback_continue','local_execute','job_cancel','download','decision_plan']:
                with self.assertRaisesRegex(ValueError,'READ_ONLY'):client.evidence_review_gate(folder,binding,op)
            for op in client.EVIDENCE_REVIEW_OPS-{'reserve_model'}:
                self.assertIsNone(client.evidence_review_gate(folder,binding,op))
            for i in range(20):self.assertEqual(client.evidence_review_gate(folder,binding,'reserve_model')['call'],i+1)
            with self.assertRaisesRegex(ValueError,'20 calls'):client.evidence_review_gate(folder,binding,'reserve_model')
            with patch.object(client.time,'time',return_value=binding['review_created_at']+3601):
                with self.assertRaisesRegex(ValueError,'expired'):client.evidence_review_gate(folder,binding,'reserve_model')

    def test_existing_execution_mode_still_uses_server_budget(self):
        self.assertIsNone(client.evidence_review_gate(Path('unused'),{'purpose':'quality_review'},'reserve_model'))

    def test_dispatch_blocks_native_calls_before_transport(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);binding={'purpose':'evidence_review','review_created_at':time.time()}
            (folder/'remote-task.json').write_text(json.dumps(binding),encoding='utf-8')
            with patch.object(client,'local_folder',return_value=folder),patch.object(client,'bind',return_value=binding),patch.object(client,'rpc') as transport:
                with self.assertRaisesRegex(ValueError,'READ_ONLY'):
                    client.dispatch({'run':td,'operation':'quality_execute'})
                self.assertTrue(client.dispatch({'run':td,'operation':'reserve_model'})['reserved'])
                transport.assert_not_called()


if __name__=='__main__':unittest.main()
