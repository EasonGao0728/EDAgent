import unittest
from tools.resume_legacy_quota_checkpoint import amended,EXPECTED
class Checks(unittest.TestCase):
 def state(self):return {'contract':{'case_id':'aes_legacy','goal':'full_backend','budget':{'wall_seconds':100,'executions':22,'model_calls':40}},'created_at':10,'counts':{'executions':11,'model_calls':15},'status':'running','pending':None,'completed':EXPECTED.copy(),'revision':11,'events':[]}
 def test_remaining(self):
  s=self.state();r=amended(s,60,200);self.assertEqual(r['contract']['budget']['wall_seconds'],240);self.assertEqual(s['contract']['budget']['wall_seconds'],100);self.assertEqual(r['counts'],s['counts']);self.assertEqual(r['created_at'],10);self.assertEqual(r['completed'],s['completed']);self.assertFalse(r['quota_continuation']['original_deadline_met'])
 def test_guards(self):
  for key,value in [('pending',{'action':'routing'}),('status','target_met'),('completed',EXPECTED[:-1]),('quota_continuation',{'done':True})]:
   with self.subTest(key=key):
    s=self.state();s[key]=value
    with self.assertRaises(ValueError):amended(s,60,200)
  for interrupted,now in [(9,200),(111,200),(60,80)]:
   with self.subTest(time=(interrupted,now)):
    with self.assertRaises(ValueError):amended(self.state(),interrupted,now)
 def test_counts(self):
  s=self.state();s['counts']['model_calls']=40
  with self.assertRaises(ValueError):amended(s,60,200)
if __name__=='__main__':unittest.main()
