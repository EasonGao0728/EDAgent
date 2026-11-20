import json,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools.audit_aes_timing_ties import audit,read_def
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'runs/aes-p1-20261108/downloaded/v5c/server-legacy-02'
TASK=ROOT/'runs/dsh-desktop-d60fc838a3964422/main-task/task.json'
@unittest.skipUnless(BASE.exists() and TASK.exists(),'Real Legacy evidence required')
class LegacyTieChecks(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.work=Path(json.loads(TASK.read_text(encoding='utf-8'))['accepted_work']);cls.design=read_def(BASE/'result/filler.def')
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.a=Path(tmp.name)/'a';self.b=Path(tmp.name)/'b'
  for src,dest in [(BASE,self.a),(self.work,self.b)]:shutil.copytree(src/'result/timing',dest/'result/timing')
  m=patch('tools.audit_aes_timing_ties.read_def',return_value=self.design);m.start();self.addCleanup(m.stop)
 def check(self):return audit(self.a,self.b,'aes')
 def test_real_removal_tie(self):
  r=self.check();self.assertTrue(r['passed']);self.assertEqual(len(r['different_selected_paths']),1)
 def test_precision_change(self):
  p=self.b/'result/timing/wire_paths/wire_path_6.json';d=json.loads(p.read_text());d[2]['inst_arc_1']['Incr']+=1e-9;p.write_text(json.dumps(d))
  with self.assertRaises(ValueError):self.check()
 def test_footer_change(self):
  p=self.b/'result/timing/aes.rpt';s=p.read_text();pos=s.rfind('library removal time');s=s[:pos]+s[pos:].replace('0.345','0.346',1);p.write_text(s)
  with self.assertRaises(ValueError):self.check()
 def test_unknown_footer(self):
  p=self.b/'result/timing/aes.rpt';p.write_text(p.read_text().replace('library removal time','library unknown time'))
  with self.assertRaises(ValueError):self.check()
