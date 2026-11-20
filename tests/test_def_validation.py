import copy
from pathlib import Path
import unittest
from macro_agent.def_validation import read_def, validate_placement
from macro_agent.ieda_stages import input_files,manifest
from macro_agent.main_task import ROOT

class DefValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Public checked-in installation fixture output, not invented geometry.
        p=ROOT/'runs/ieda-gcd-20261030-225429/result/iPL_result.def'
        if not p.is_file(): raise unittest.SkipTest('Local public GCD reference run is not available')
        cls.design=read_def(p)
    def check(self,design): return validate_placement(self.design,self.design,design,input_files()[2],policy=manifest())
    def test_real_reference_geometry_passes(self): self.assertTrue(self.check(self.design)['passed'])
    def test_net_connectivity_tampering_fails(self):
        d=copy.deepcopy(self.design);d['nets'][next(iter(d['nets']))]=[]
        self.assertIn('net_connectivity_changed',self.check(d)['errors'])
    def test_overlap_and_out_of_bounds_are_rejected(self):
        d=copy.deepcopy(self.design);items=list(d['components'].values())
        items[0]['placement']=['PLACED',-100,0,'N'];items[1]['placement']=items[2]['placement'][:]
        r=self.check(d);self.assertFalse(r['passed'])
        self.assertTrue(any(e.startswith('outside_die:') for e in r['errors']))
        self.assertTrue(any(e.startswith('overlap:') for e in r['errors']))
    def test_only_reviewed_power_pin_additions_allowed(self):
        d=copy.deepcopy(self.design);d['pins']['BAD']='BAD + NET BAD + USE POWER'
        self.assertIn('top_level_pins_changed',self.check(d)['errors'])

    def test_unknown_regions_and_changed_physical_nets_fail_closed(self):
        d=copy.deepcopy(self.design);d['physical']['REGIONS']=['new_region ( 0 0 ) ( 10 10 )']
        self.assertIn('unsupported_mandatory_constraint:REGIONS',self.check(d)['errors'])
        d=copy.deepcopy(self.design);d['physical']['SPECIALNETS']=[]
        self.assertIn('floorplan_physical_constraints_changed',self.check(d)['errors'])

    def test_row_alignment_and_io_placement_are_checked(self):
        d=copy.deepcopy(self.design)
        for v in d['components'].values():
            if v['placement'][0]=='PLACED':v['placement'][1]+=1;break
        self.assertTrue(any(e.startswith('row_site_violation') for e in self.check(d)['errors']))
        d=copy.deepcopy(self.design);d['pins']['clk']='clk + NET clk + DIRECTION INPUT + USE SIGNAL'
        self.assertIn('unplaced_or_invalid_io:clk',self.check(d)['errors'])

    def test_connected_master_pin_resolution_rejects_bad_pin(self):
        d=copy.deepcopy(self.design)
        for net,pins in d['nets'].items():
            for i,(inst,pin) in enumerate(pins):
                if inst!='PIN':pins[i]=(inst,'FAKE_PIN');break
            else:continue
            break
        r=validate_placement(d,d,d,input_files()[2],policy=manifest())
        self.assertTrue(any(e.startswith('unresolved_terminal') for e in r['errors']))
