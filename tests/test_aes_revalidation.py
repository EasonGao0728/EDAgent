import copy,json,tempfile,unittest
from pathlib import Path
from tools.revalidate_aes_baseline import ROOT,verify,sha,CHECKER
from macro_agent.aes_flow import STAGES

class RevalidationTests(unittest.TestCase):
    def record(self):
        return {'status':'passed','stages':[{'stage':s,'passed':True} for s in STAGES],
                'implementation_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'macro_agent').glob('*.py')}}
    def rejected(self,record,reason):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'run.json').write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,reason):verify(record,p)
    def test_failed_baseline_cannot_be_relabelled(self):
        r=self.record();r['status']='failed';self.rejected(r,'already passed')
    def test_changed_native_producer_requires_new_execution(self):
        r=self.record();r['implementation_sha256']['macro_agent/aes_flow.py']='0'*64
        self.rejected(r,'Unreviewed producer')
    def test_arbitrary_validator_revision_is_not_accepted(self):
        r=self.record();r['implementation_sha256'][CHECKER]='0'*64
        self.rejected(r,'Unreviewed producer or validator')

if __name__=='__main__':unittest.main()
