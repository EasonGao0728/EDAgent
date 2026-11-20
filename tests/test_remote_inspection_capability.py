import unittest
from unittest.mock import patch
from macro_agent.remote_client import inspect_rpc

class InspectionCapabilityTests(unittest.TestCase):
    def test_unregistered_experiment_returns_explicit_unavailable(self):
        with patch('macro_agent.remote_client.rpc',side_effect=RuntimeError('EXPERIMENT_CAPABILITY_GAP')) as remote:
            r=inspect_rpc({'operation':'decision_inspect','kind':'experiment_result','task_id':'example'})
        self.assertFalse(r['available']);self.assertFalse(r['native_action_submitted'])
        self.assertEqual(r['error'],'EXPERIMENT_CAPABILITY_GAP');remote.assert_called_once()

    def test_real_network_errors_are_not_hidden(self):
        with patch('macro_agent.remote_client.rpc',side_effect=RuntimeError('REMOTE_REPLY_UNKNOWN')):
            with self.assertRaisesRegex(RuntimeError,'REMOTE_REPLY_UNKNOWN'):
                inspect_rpc({'operation':'decision_inspect','kind':'experiment_result','task_id':'example'})

    def test_mutations_and_summary_errors_still_fail(self):
        for request in ({'operation':'decision_execute','kind':'experiment_result'},
                        {'operation':'decision_inspect','kind':'summary'}):
            with self.subTest(request=request),patch('macro_agent.remote_client.rpc',side_effect=RuntimeError('EXPERIMENT_CAPABILITY_GAP')):
                with self.assertRaises(RuntimeError):inspect_rpc(request)

    def test_success_is_unchanged(self):
        value={'facts':{'passed':False},'state_id':'s'}
        with patch('macro_agent.remote_client.rpc',return_value=value):
            self.assertIs(inspect_rpc({'operation':'observe'}),value)

if __name__=='__main__':unittest.main()
