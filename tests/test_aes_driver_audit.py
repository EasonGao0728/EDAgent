import copy,unittest
from tools.audit_aes_drivers import audit,directions,ROOT
from macro_agent.def_validation import read_def

class DriverAuditTests(unittest.TestCase):
    def test_reversed_buffer_fails_even_when_undirected_endpoints_match(self):
        masters={'buf':{'A':'INPUT','X':'OUTPUT'},'logic':{'A':'INPUT'}}
        d={'pins':{'a':'+ DIRECTION INPUT'},'components':{'b':{'master':'buf'},'u':{'master':'logic'}},
            'nets':{'a':[('PIN','a'),('b','A')],'buffered':[('b','X'),('u','A')]}}
        self.assertTrue(audit(d,masters)['passed'])
        reversed=copy.deepcopy(d);reversed['nets']['a'][1]=('b','X');reversed['nets']['buffered'][0]=('b','A')
        self.assertFalse(audit(reversed,masters)['passed'])
    def test_unknown_direction_and_duplicate_terminal_fail(self):
        d={'pins':{'a':'+ DIRECTION INPUT'},'components':{},'nets':{'a':[('PIN','a'),('PIN','a')]}}
        self.assertFalse(audit(d,{})['passed'])
        d['nets']['a']=[('PIN','unknown')];self.assertFalse(audit(d,{})['passed'])
    def test_empty_exemption_requires_original_names_and_no_terminals(self):
        d={'pins':{'a':'+ DIRECTION OUTPUT'},'components':{},'nets':{'unused':[]}}
        self.assertFalse(audit(d,{})['passed'])
        self.assertTrue(audit(d,{},allowed_empty_nets={'unused'})['passed'])
        d['nets']['unused']=[('PIN','a')]
        self.assertFalse(audit(d,{},allowed_empty_nets={'unused'})['passed'])
        d['nets']={'new_unused':[]}
        self.assertFalse(audit(d,{},allowed_empty_nets={'unused'})['passed'])
    def test_actual_first_ten_stages_of_archived_cipher_trial(self):
        folder=ROOT/'runs/aes-p1-20261108/downloaded/v1/server-cipher-02/result'
        masters=directions([ROOT/'cases/ibench/aes_sky130_t/pdk/lef/sky130_fd_sc_hd_merged.lef'])
        for stage in ('import_netlist','floorplan','fanout','placement','export_def','cts','to_drv','to_hold','legalization'):
            with self.subTest(stage=stage):
                r=audit(read_def(folder/(stage+'.def')),masters);self.assertTrue(r['passed'],r)
if __name__=='__main__':unittest.main()
