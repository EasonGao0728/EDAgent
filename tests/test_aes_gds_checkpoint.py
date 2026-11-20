import copy, unittest
from macro_agent import aes_flow
from tools.resume_aes_gds_checkpoint import check_record, CHECKER, OLD, NEW, EMPTY


class CheckpointGuards(unittest.TestCase):
    def setUp(self):
        self.current = {CHECKER: NEW, 'macro_agent/aes_flow.py': 'unchanged'}
        self.record = {'case': 'aes_legacy', 'status': 'failed', 'version': aes_flow.VERSION,
                       'router_sha256': aes_flow.ROUTER_SHA256,
                       'implementation_sha256': {**self.current, CHECKER: OLD},
                       'stages': [{'stage': s, 'passed': True} for s in aes_flow.STAGES[:14]]}
        self.record['stages'].append({'stage': 'gds_export', 'passed': False, 'returncode': 0,
                                     'validation': {'passed': False, 'errors': sorted('missing_routed_net:' + n for n in EMPTY)}})

    def test_only_reviewed_checker_case_admitted(self):
        check_record(self.record, self.current, EMPTY)

    def test_original_failed_record_is_not_mutated(self):
        previous = copy.deepcopy(self.record)
        check_record(self.record, self.current, EMPTY)
        self.assertEqual(self.record, previous)

    def test_missing_or_failed_earlier_stage_rejected(self):
        self.record['stages'][10]['passed'] = False
        with self.assertRaisesRegex(ValueError, 'fourteen'):
            check_record(self.record, self.current, EMPTY)

    def test_native_export_failure_rejected(self):
        self.record['stages'][-1]['returncode'] = 1
        with self.assertRaisesRegex(ValueError, 'Native export failure'):
            check_record(self.record, self.current, EMPTY)

    def test_timeout_rejected(self):
        self.record['stages'][-1]['timed_out'] = True
        with self.assertRaisesRegex(ValueError, 'Native export failure'):
            check_record(self.record, self.current, EMPTY)

    def test_other_gds_error_rejected(self):
        self.record['stages'][-1]['validation']['errors'].append('missing_routed_net:real_connected_net')
        with self.assertRaisesRegex(ValueError, 'three independently'):
            check_record(self.record, self.current, EMPTY)

    def test_changed_native_producer_rejected(self):
        self.current['macro_agent/aes_flow.py'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'Unreviewed'):
            check_record(self.record, self.current, EMPTY)

    def test_arbitrary_checker_revision_rejected(self):
        self.current[CHECKER] = 'unreviewed'
        with self.assertRaisesRegex(ValueError, 'Unreviewed'):
            check_record(self.record, self.current, EMPTY)

    def test_empty_net_with_endpoints_not_exempted(self):
        with self.assertRaisesRegex(ValueError, 'three independently'):
            check_record(self.record, self.current, set(EMPTY) - {next(iter(EMPTY))})


if __name__ == '__main__':
    unittest.main()
