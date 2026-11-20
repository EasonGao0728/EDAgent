import copy,tempfile,unittest
from pathlib import Path
from macro_agent import aes_netlist,swerv_backend as s
from macro_agent.aes_transforms import check
from macro_agent.placement_registry import first_run_admitted

class SwervTests(unittest.TestCase):
 def test_real_inputs(self):
  v=s.preflight(s.ROOT/'cases/ibench'/s.CASE)
  self.assertEqual(v['standard_cells'],6777);self.assertEqual(len(v['hard_macros']),3)
  self.assertFalse(v['native_fullflow_qualified'])
 def test_explicit_bus_order_and_width(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x.v';p.write_text('module top(a,b); input a,b; RAM u(.D({a,b})); endmodule')
   value=aes_netlist.parse(p,{'RAM':{'D':['D[1]','D[0]']}})
   self.assertIn((('PIN','a'),('u','D[1]')),value['partitions'])
   with self.assertRaises(ValueError):aes_netlist.parse(p,{'RAM':{'D':['D[0]']}})
   with self.assertRaises(ValueError):aes_netlist.parse(p)
 def test_fixed_macro_and_buffer_guard(self):
  before={'design':'x','units':2000,'die':[0,0,100,100],'pins':{},'components':{'m':{'master':'RAM','placement':['FIXED',0,0,'N']}},'nets':{'n':[('m','A'),('PIN','a')]}}
  after=copy.deepcopy(before);after['components']['buf']={'master':'BUF_X4','placement':None}
  after['nets']={'n':[('PIN','a'),('buf','A')],'n2':[('buf','Z'),('m','A')]}
  self.assertTrue(check(before,after,'cts',s.BUFFERS)['passed'])
  after['components']['m']['placement'][1]=2
  self.assertFalse(check(before,after,'cts',s.BUFFERS)['passed'])
 def test_admission_is_case_bound(self):
  card={'tool_id':'ieda_imp_swerv','experimental_admission':'registered_swerv_first_run_v1','evidence':{'passed':True,'native_fullflow_qualified':False}}
  self.assertTrue(first_run_admitted(card,'swerv_nangate45_v1'))
  self.assertFalse(first_run_admitted(card,'sky130_sram_pair_v1'))
  card['tool_id']='arbitrary';self.assertFalse(first_run_admitted(card,'swerv_nangate45_v1'))
 def test_unplaced_syntax_preserves_semantics_and_raw_file(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x.def';p.write_text('VERSION 5.8 ;\nDESIGN x ;\nUNITS DISTANCE MICRONS 2000 ;\nCOMPONENTS 1 ;\n- u BUF_X4 + UNPLACED ( -1 -1 ) ;\nEND COMPONENTS\nPINS 0 ;\nEND PINS\nNETS 0 ;\nEND NETS\nEND DESIGN\n')
   original=p.read_bytes();v=s.normalize_unplaced(p)
   self.assertEqual(v['changed_records'],1);self.assertTrue(v['semantic_equality'])
   self.assertEqual(p.with_suffix('.native.def').read_bytes(),original)
   self.assertEqual(s.normalize_unplaced(p)['changed_records'],0)

if __name__=='__main__':unittest.main()
