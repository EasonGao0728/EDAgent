import unittest
from macro_agent.local_repair import local_patch,via_shapes,via_map,marker_counts
import tempfile,json
from pathlib import Path
from macro_agent.local_repair_report import render
from macro_agent.local_template_trial import select_template

DEF='''VERSION 5.8 ;
NETS 2 ;
- n1 ( a X ) ( b A ) + ROUTED met1 ( 5000 5000 ) OLD
 NEW met1 ( 5000 5000 ) ( 7000 * ) ;
- n2 ( c X ) ( d A ) + ROUTED met1 ( 20000 5000 ) OLD ;
END NETS
END DESIGN
'''
SHAPES={n:{'met1':[[-a,-a,a,a]],'via1':[[-50,-50,50,50]],'met2':[[-a,-a,a,a]]} for n,a in [('OLD',100),('NEWV',80)]}

class LocalRepairTests(unittest.TestCase):
 def test_scoped_native_proposal_keeps_other_net_and_wire_exact(self):
  proposal=DEF.replace('OLD','NEWV');patched,changes=local_patch(DEF,proposal,[0,0,10000,10000],SHAPES)
  self.assertEqual(patched,DEF.replace('OLD','NEWV',1));self.assertEqual(len(changes),1)
  self.assertEqual(via_map(patched)[('n2','met1',20000,5000)],'OLD')
 def test_enclosure_crossing_boundary_is_not_admitted(self):
  p,c=local_patch(DEF,DEF.replace('OLD','NEWV'),[5000,0,10000,10000],SHAPES)
  self.assertEqual(p,DEF);self.assertEqual(c,[])
 def test_unknown_via_or_layer_change_is_not_admitted(self):
  self.assertEqual(local_patch(DEF,DEF.replace('OLD','BAD'),[0,0,10000,10000],SHAPES)[1],[])
  other={**SHAPES,'NEWV':{'met2':SHAPES['NEWV']['met1']}}
  self.assertEqual(local_patch(DEF,DEF.replace('OLD','NEWV'),[0,0,10000,10000],other)[1],[])
 def test_native_changes_to_non_via_data_are_not_copied(self):
  p,c=local_patch(DEF,DEF.replace('( 7000 * )','( 9000 * )').replace('OLD','NEWV'),[0,0,10000,10000],SHAPES)
  self.assertIn('( 7000 * )',p);self.assertEqual(len(c),1)
 def test_duplicate_conflicting_vias_fail_closed(self):
  with self.assertRaisesRegex(ValueError,'AMBIGUOUS'):via_map(DEF.replace('NEW met1 ( 5000 5000 ) ( 7000 * )','NEW met1 ( 5000 5000 ) OTHER'))
 def test_truncated_or_inconsistent_marker_counts_fail(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'v.json';p.write_text(json.dumps({'count':1,'summary':{'total':1,'by_type':{'metal_short':1}},'violations':[]}))
   with self.assertRaisesRegex(ValueError,'COUNT'):marker_counts(p,[0,0,1,1])
 def test_report_preserves_unknown_quality_and_escapes_evidence(self):
  text=render({'diagnosis':{'regional_rules_intersecting':{'cut_short':3},'region_dbu':[0,0,10000,10000]},'status':'failed','error':'<script>bad</script>'})
  self.assertIn('未验证',text);self.assertNotIn('<script>bad</script>',text)
  self.assertIn('&lt;script&gt;',text);self.assertIn('不是完整版图或拥塞热图',text)
 def test_template_trial_requires_same_cut_and_actual_net_marker(self):
  marker={'type':'metal_short','net_ids':['n1'],'layer':'met1','bbox':[5090,4990,5100,5010]}
  choice=select_template(via_map(DEF),SHAPES,[marker],[0,0,10000,10000])
  self.assertEqual(choice['after'],'NEWV');self.assertEqual(choice['key'][0],'n1')
  self.assertIsNone(select_template(via_map(DEF),SHAPES,[{**marker,'net_ids':['unrelated']}],[0,0,10000,10000]))
  changed_cut={**SHAPES,'NEWV':{**SHAPES['NEWV'],'via1':[[-40,-40,40,40]]}}
  self.assertIsNone(select_template(via_map(DEF),changed_cut,[marker],[0,0,10000,10000]))

if __name__=='__main__':unittest.main()
