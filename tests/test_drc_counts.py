import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from macro_agent.drc_counts import AUDITED_BINARY, marker_stream, reconcile
from macro_agent.backend_checks import drc_gate
from macro_agent.aes_reproduction import drc_observation

FIXTURE = Path(__file__).parent / 'fixtures/drc-prefilter-counts'


class CountSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'report'
        shutil.copytree(FIXTURE, self.root)
        self.summary = json.loads((self.root / 'drc_summary.json').read_text())

    def gate(self, sha=AUDITED_BINARY):
        return drc_gate(self.summary, report_dir=self.root, producer_sha256=sha)

    def write_summary(self):
        for folder in (self.root, self.root / 'drc.rpt.artifacts'):
            (folder / 'drc_summary.json').write_text(json.dumps(self.summary))

    def write_markers(self, value):
        for folder in (self.root, self.root / 'drc.rpt.artifacts'):
            (folder / 'violations.json').write_text(json.dumps(value))

    def test_real_zero_final_two_raw_reconciles_without_mutation(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        original = copy.deepcopy(self.summary)
        result = self.gate()
        self.assertTrue(result['passed'], result)
        r = result['count_reconciliation']
        self.assertTrue(r['different_scopes_explain_counts'])
        self.assertEqual(r['runtime_candidate_count'], 2)
        self.assertEqual(r['final_violation_count'], 0)
        self.assertFalse(result['signoff_clean'])
        self.assertFalse(r['physical_filter_correctness_verified'])
        self.assertEqual(self.summary, original)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_unknown_producer_and_summary_only_still_fail_closed(self):
        for sha in (None, 'wrong'):
            self.assertFalse(self.gate(sha)['passed'])
        self.assertFalse(drc_gate(self.summary)['passed'])

    def test_missing_or_stale_canonical_copies_are_rejected(self):
        p = self.root / 'drc.rpt.artifacts/violations.json'
        p.write_text('{}')
        self.assertFalse(self.gate()['passed'])
        p.unlink()
        self.assertFalse(self.gate()['passed'])

    def test_final_marker_total_mismatch_is_not_excused(self):
        data = json.loads((self.root / 'violations.json').read_text())
        data['count'] = 2
        self.write_markers(data)
        self.assertFalse(self.gate()['passed'])

    def test_log_final_count_mismatch_is_not_excused(self):
        (self.root / 'drc.rpt').write_text('| Total | 1 | 100% |')
        self.assertFalse(self.gate()['passed'])

    def test_coverage_mismatch_is_rejected(self):
        data = json.loads((self.root / 'violations.json').read_text())
        data['coverage']['checked'] = []
        self.write_markers(data)
        self.assertFalse(self.gate()['passed'])

    def test_aes_dedup_requires_matching_checksum_receipt(self):
        from macro_agent.drc_counts import file_ref
        ref=file_ref(self.root/'violations.json')
        (self.root/'drc.rpt.artifacts/violations.json').unlink()
        # Production report is <work>/result/report; this fixture's work is tmp's parent.
        # Relocate before testing rather than write outside the temporary workspace.
        new=self.root.parent/'work/result/report'
        new.parent.mkdir(parents=True)
        shutil.move(self.root,new);self.root=new
        receipt=self.root.parent.parent/'drc-storage-dedup.json'
        data={'details_preserved':True,'removed':[{'removed':'result/report/drc.rpt.artifacts/violations.json',
            'canonical':'result/report/violations.json','sha256':ref['sha256'],'bytes':ref['bytes']}]}
        receipt.write_text(json.dumps(data))
        self.assertTrue(self.gate()['passed'])
        data['removed'][0]['sha256']='wrong';receipt.write_text(json.dumps(data))
        self.assertFalse(self.gate()['passed'])

    def test_structured_report_uses_engine_log_but_conflicts_are_rejected(self):
        new=self.root.parent/'work/result/report';new.parent.mkdir(parents=True)
        shutil.move(self.root,new);self.root=new
        logs=self.root.parent.parent/'logs';logs.mkdir()
        (logs/'drc.log').write_text('| Total | 0 | 0% |')
        (self.root/'drc.rpt').write_text('Structured native report without engine table')
        self.assertTrue(self.gate()['passed'])
        (self.root/'drc.rpt').write_text('| Total | 1 | 100% |')
        self.assertFalse(self.gate()['passed'])

    def test_negative_boolean_or_stale_runtime_rejected(self):
        original = copy.deepcopy(self.summary)
        for value in (-1, True, '2'):
            self.summary = copy.deepcopy(original)
            self.summary['runtime']['per_rule']['minimum_area']['violation_count'] = value
            self.write_summary()
            self.assertFalse(self.gate()['passed'])
        self.summary = original
        self.summary['runtime']['stale_cluster_cache_count'] = 1
        self.write_summary()
        self.assertFalse(self.gate()['passed'])

    def test_actual_final_violation_is_never_quality_clean(self):
        self.summary.update(violation_count=1, status='dirty')
        self.write_summary()
        data = json.loads((self.root / 'violations.json').read_text())
        data.update(count=1, status='dirty', summary={'total': 1, 'by_type': {'minimum_area': 1}, 'by_layer': {'met1': 1}},
                    violations=[{'type': 'minimum_area', 'layer': 'met1', 'bbox': [0, 0, 1, 1]}])
        self.write_markers(data)
        (self.root / 'drc.rpt').write_text('| Total | 1 | 100% |')
        self.assertTrue(reconcile(self.summary, self.root, AUDITED_BINARY)['passed'])
        self.assertFalse(self.gate()['passed'])
        aes = drc_observation(self.summary, report_dir=self.root, producer_sha256=AUDITED_BINARY)
        self.assertTrue(aes['passed'])  # reproduction, not physical quality
        self.assertFalse(aes['quality_clean'])

    def test_aes_reproduction_does_not_ignore_real_conflicts(self):
        result = drc_observation(self.summary, report_dir=self.root, producer_sha256=AUDITED_BINARY)
        self.assertTrue(result['passed'])
        (self.root / 'violations.json').write_text('{}')
        self.assertFalse(drc_observation(self.summary, report_dir=self.root, producer_sha256=AUDITED_BINARY)['passed'])

    def test_truncated_or_malformed_marker_file_never_yields_success(self):
        for text in ('{"violations":[]', '{"violations":[{},]}', '{"violations":[{}{}]}', '{"violations":[]} junk'):
            with self.subTest(text=text):
                p = self.root / 'invalid.json'
                p.write_text(text)
                with self.assertRaises(ValueError):
                    list(marker_stream(p))

    def test_stream_large_and_chunk_boundary(self):
        p = self.root / 'large.json'
        p.write_text('{"count":6000,"violations":[' + ',\n '.join(['{"type":"minimum_area"}'] * 6000) + ']}')
        self.assertEqual(sum(kind == 'marker' for kind, _ in marker_stream(p)), 6000)


if __name__ == '__main__':
    unittest.main()
