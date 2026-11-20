import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from macro_agent.remote_client import model_context

class MacroContextTests(unittest.TestCase):
 def test_large_audit_keeps_contract_errors_and_exact_archive(self):
  value={'contract':{'budget':{'wall_seconds':7200},'hard_constraints':['fixed macros']},'state_id':'s','latest_evidence':{'independent_macro_check':{'passed':False,'errors':['overlap'],'macros':['a','b','c'],'restored_unplaced_stdcell_sentinels':['std'+str(i) for i in range(6777)]}}}
  original=copy.deepcopy(value)
  with tempfile.TemporaryDirectory() as d:
   v=model_context(value,Path(d));self.assertEqual(value,original);self.assertEqual(v['contract'],original['contract'])
   check=v['latest_evidence']['independent_macro_check'];self.assertFalse(check['passed']);self.assertEqual(check['errors'],['overlap']);self.assertEqual(check['macros'],['a','b','c'])
   self.assertEqual(check['restored_unplaced_stdcell_sentinels_summary']['count'],6777)
   ref=v['macro_audit_snapshot_ref'];raw=Path(ref['path']).read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),ref['sha256']);self.assertEqual(json.loads(raw),original)
   self.assertLess(len(json.dumps(v)),2500)
if __name__=='__main__':unittest.main()
