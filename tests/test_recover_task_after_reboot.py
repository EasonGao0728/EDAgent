import copy
import os
from pathlib import Path
import tempfile
import unittest

from tools.recover_task_after_reboot import mark_stopped, validate_interruption


class RebootRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()
        self.work = self.folder / 'attempts' / 'interrupted'
        (self.work / 'logs').mkdir(parents=True)
        self.log = self.work / 'logs/routing.log'
        self.log.write_text('Native partial routing; not accepted')
        os.utime(self.log, (1800, 1800))
        self.state = {'status': 'running', 'created_at': 500, 'revision': 3,
            'contract': {'goal': 'full_backend', 'case_id': 'aes_sky130_t',
                         'budget': {'wall_seconds': 32400, 'host_seconds': 21620}},
            'pending': {'action': 'routing', 'action_id': 'real-call', 'work': str(self.work),
                        'safe_retry_after': 1000 + 21630},
            'completed': ['import_netlist'], 'results': {'import_netlist': {'passed': True}},
            'counts': {'executions': 2, 'model_calls': 3}, 'failure_counts': {},
            'accepted_work': 'preserved', 'events': [], 'input_refs': [], 'receipts': {}}
        self.evidence = {'observed_at': 2100, 'boot_epoch': 2000, 'engine_os': 'linux',
                         'engine_id': 'engine', 'containers': []}

    def check(self):
        return validate_interruption(self.state, self.folder, self.evidence, 2100)

    def test_real_reboot_discards_only_uncertain_state_and_preserves_budget(self):
        self.check()
        before = copy.deepcopy(self.state)
        result = mark_stopped(self.state, {'path': 'receipt', 'sha256': 'hash'})
        self.assertEqual(self.state, before)
        self.assertIsNone(result['pending'])
        self.assertEqual(result['status'], 'stopped_with_best')
        for key in ('contract', 'counts', 'created_at', 'results', 'completed', 'accepted_work', 'failure_counts', 'input_refs', 'receipts'):
            self.assertEqual(result[key], before[key])
        self.assertFalse(result['events'][-1]['accepted'])

    def test_boot_before_action_is_not_proof(self):
        self.evidence['boot_epoch'] = 900
        with self.assertRaisesRegex(ValueError, 'postdate'): self.check()

    def test_any_existing_container_blocks_recovery(self):
        self.evidence['containers'] = [{'Names': 'another-users-job', 'State': 'running'}]
        with self.assertRaisesRegex(ValueError, 'no containers'): self.check()

    def test_complete_receipt_must_use_normal_recovery(self):
        (self.work / 'stage-receipt.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'normal recover'): self.check()

    def test_fresh_log_is_not_interrupted_preboot_log(self):
        os.utime(self.log, (2050, 2050))
        with self.assertRaisesRegex(ValueError, 'predating'): self.check()

    def test_stale_engine_evidence_is_rejected(self):
        self.evidence['observed_at'] = 2000
        with self.assertRaisesRegex(ValueError, 'Fresh'): self.check()

    def test_expired_task_cannot_be_extended(self):
        self.state['contract']['budget']['wall_seconds'] = 1000
        with self.assertRaisesRegex(ValueError, 'exhausted'): self.check()

    def test_other_task_attempt_cannot_be_discarded(self):
        self.state['pending']['work'] = str(self.folder.parent)
        with self.assertRaisesRegex(ValueError, 'outside'): self.check()

    def test_unknown_platform_evidence_fails(self):
        self.evidence['engine_os'] = 'windows'
        with self.assertRaisesRegex(ValueError, 'Linux'): self.check()
