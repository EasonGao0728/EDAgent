import copy,json,unittest,hashlib,io
from pathlib import Path
from tools.resume_aes_storage_checkpoint import ROOT,check_record,sha,sha256_file_digest_compat
class StorageCheckpointGuards(unittest.TestCase):
    def test_python310_digest_matches_stdlib_across_chunk_boundaries(self):
        for data in (b'',b'abc',bytes(range(256))*8193):
            self.assertEqual(sha256_file_digest_compat(io.BytesIO(data),'sha256').hexdigest(),hashlib.file_digest(io.BytesIO(data),'sha256').hexdigest())
        with self.assertRaises(ValueError):sha256_file_digest_compat(io.BytesIO(b'x'),'md5')
    def setUp(self):
        self.record=json.loads((ROOT/'runs/aes-p1-20261108/downloaded/v5c/server-core-01/run.json').read_text())
        self.current={p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'macro_agent').glob('*.py')}
    def test_exact_storage_failure_and_reviewed_revisions(self):
        before=copy.deepcopy(self.record);check_record(self.record,self.current);self.assertEqual(before,self.record)
    def test_timeout_cannot_be_relabelled(self):
        self.record['stages'][-1]['timed_out']=True
        with self.assertRaisesRegex(ValueError,'workspace-cap'):check_record(self.record,self.current)
    def test_partial_routing_cannot_be_reused(self):
        self.record['stages'][10]['passed']=False
        with self.assertRaisesRegex(ValueError,'fourteen'):check_record(self.record,self.current)
    def test_arbitrary_source_revision_rejected(self):
        self.current['macro_agent/aes_flow.py']='0'*64
        with self.assertRaisesRegex(ValueError,'Unreviewed'):check_record(self.record,self.current)
if __name__=='__main__':unittest.main()
