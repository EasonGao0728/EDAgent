import copy
import tempfile
from pathlib import Path
import unittest
from macro_agent.macro_stages import accept_macro_candidate
from macro_agent.main_task import ROOT,dispatch

class MacroTests(unittest.TestCase):
    def fixture(self):
        d={'units':1000,'components':{'mem0':{'master':'sram','placement':None},'mem1':{'master':'sram','placement':None},'u':{'master':'buf','placement':None}},'nets':{'n':[('u','A'),('mem0','D')]},'physical':{},'pins':{}}
        cells={'sram':{'hard_macro':True,'size':[100,100]},'buf':{'hard_macro':False,'size':[10,10]}}
        m={'macro_placement':{'macros':['mem0','mem1']},'core_area_microns':[0,0,1,1]}
        a=copy.deepcopy(d)
        a['components']['mem0']['placement']=['PLACED',0,0,'N'];a['components']['mem1']['placement']=['PLACED',200,0,'N']
        a['components']['u']['placement']=['PLACED',-1,-1,'N']
        return d,a,cells,m
    def test_only_known_unplaced_sentinel_is_accepted(self):
        d,a,c,m=self.fixture();self.assertTrue(accept_macro_candidate(d,a,c,m)['passed'])
        a['components']['u']['placement'][1]=-2
        self.assertFalse(accept_macro_candidate(d,a,c,m)['passed'])
    def test_overlap_core_and_connectivity_changes_fail(self):
        for change in ('overlap','outside','net'):
            d,a,c,m=self.fixture()
            if change=='overlap':a['components']['mem1']['placement'][1]=50
            elif change=='outside':a['components']['mem1']['placement'][1]=950
            else:a['nets']['n']=[]
            self.assertFalse(accept_macro_candidate(d,a,c,m)['passed'],change)
    def test_macro_contract_uses_same_host_and_correct_rag(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'runs') as t:
            s=dispatch({'run':t,'operation':'start','case_id':'sky130_sram_pair'})
            self.assertEqual([p['stage'] for p in s['plan']][2],'macro_placement')
            self.assertFalse(s['contract']['maker_enabled'])
            self.assertNotIn('This registered GCD case has zero hard macros',s['limitations'])
            r=dispatch({'run':t,'operation':'retrieve','query':'macro coordinates','backend_version':s['contract']['backend_version']})
            self.assertEqual(r['status'],'matched');self.assertIn('sram-ieda',r['hits'][0]['source_ref'])

if __name__=='__main__':unittest.main()
