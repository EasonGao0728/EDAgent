import copy,json,tempfile,unittest
from pathlib import Path
from macro_agent.full_backend import timing_optimization_gate,STAGES,for_case
from macro_agent.main_task import dispatch,ROOT
from macro_agent.native_gds import validate

class FullBackendTests(unittest.TestCase):
    def test_native_report_must_exist_and_prove_no_unaudited_optimization(self):
        data=json.loads((ROOT/'runs/stage1-backend-gaps-20261106-v2/result/to/ito_pass_report.json').read_text())
        self.assertTrue(timing_optimization_gate(data,'drv')['passed'])
        self.assertTrue(timing_optimization_gate(data,'hold')['passed'])
        for failure in ('missing','mutation','violations','unavailable'):
            d=copy.deepcopy(data);p=d['passes'][0]
            if failure=='missing':d['passes']=[]
            if failure=='mutation':p['canonical_hash_after']='tampered'
            if failure=='violations':p['timing_quality_after']['buckets']['slew']['violations']=1
            if failure=='unavailable':p['timing_quality_after']['available']=False
            self.assertFalse(timing_optimization_gate(d,'drv')['passed'],failure)

    def test_full_goal_keeps_core_state_machine_and_rejects_wrong_case(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'runs') as t:
            s=dispatch({'run':t,'operation':'start','case_id':'ibench_gcd_legacy','goal':'full_backend'})
            self.assertEqual([p['stage'] for p in s['plan']],STAGES)
            self.assertFalse(s['contract']['maker_enabled'])
            self.assertIn('native_abstract_gds_readback',s['contract']['required_backend_gates'])
            self.assertEqual(s['allowed_actions'],['import_netlist','stop'])
            with self.assertRaises(ValueError):dispatch({'run':t,'operation':'act','action':'gds_export','state_id':s['state_id'],'action_id':'skip'})
            r=dispatch({'run':t,'operation':'retrieve','query':'netlist gds validation','backend_version':s['contract']['backend_version']})
            self.assertEqual(r['status'],'matched')
        with self.assertRaises(ValueError):for_case('sky130_sram_pair')

    def test_gds_checks_detect_removed_route_and_wrong_units(self):
        import klayout.db as db
        source=ROOT/'runs/stage1-public-idb-gds-20261107-02/result'
        reference=ROOT/'cases/ibench/gcd_legacy/pdk/lef'
        args=(source/'filler.def',reference/'sky130_fd_sc_hd.tlef',[reference/'sky130_fd_sc_hd_merged.lef'])
        self.assertTrue(validate(source/'final.gds',*args)['passed'])
        with tempfile.TemporaryDirectory() as t:
            l=db.Layout();l.read(str(source/'final.gds'));l.dbu*=1000;p=Path(t)/'wrong.gds';l.write(str(p))
            self.assertIn('database_unit_mismatch',validate(p,*args)['errors'])
            l=db.Layout();l.read(str(source/'final.gds'));l.cell('clk').clear();p=Path(t)/'missing.gds';l.write(str(p))
            self.assertIn('missing_routed_net:clk',validate(p,*args)['errors'])

if __name__=='__main__':unittest.main()
