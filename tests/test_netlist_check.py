import tempfile
from pathlib import Path
import unittest
from macro_agent.main_task import ROOT
from macro_agent.netlist_check import parse_flat,verify_import,liberty_bus_ports

class NetlistTests(unittest.TestCase):
    def test_bus_connection_preserves_declared_order_and_rejects_unknown_width(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'a.v';p.write_text('module g(data); input [0:1] data; sram u(.din(data)); endmodule')
            schema={'sram':{'din':['din[1]','din[0]']}}
            d=parse_flat(p,schema)
            self.assertIn(('u','din[1]'),d['nets']['data[0]'])
            self.assertIn(('u','din[0]'),d['nets']['data[1]'])
            for invalid in (None,{'sram':{'din':['din[0]']}}):
                with self.assertRaisesRegex(ValueError,'bus width/schema'):parse_flat(p,invalid)
            p.write_text('module g(data); input data; sram u(.din(data)); endmodule')
            with self.assertRaises(ValueError):parse_flat(p,schema)
    def test_liberty_bus_requires_explicit_unique_range(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'s.lib';text='cell (sram) {\n bus(din) {\n pin(din[1:0]) { }\n }\n}'
            p.write_text(text);self.assertEqual(liberty_bus_ports(p),{'sram':{'din':['din[1]','din[0]']}})
            for bad in (text.replace('pin(din[1:0])','pin(other[1:0])'),text+'\n'+text):
                p.write_text(bad)
                with self.assertRaises(ValueError):liberty_bus_ports(p)
    def test_real_sram_fixture_matches_independent_input_parser(self):
        f=ROOT/'runs/stage1-native-macro-20261106-01'
        lib=ROOT/'third_party/ieda-reference/scripts/foundry/sky130/lib/sky130_sram_1rw1r_44x64_8_TT_1p8V_25C.lib'
        if not (f/'result/iFP_result.def').exists():self.skipTest('native SRAM probe absent')
        r=verify_import(f/'gcd_sram.v',f/'result/iFP_result.def',liberty_bus_ports(lib))
        self.assertTrue(r['passed'],r);self.assertEqual(r['source_instances'],66)
    def test_historical_real_hd_import_matches_raw_verilog(self):
        folder=ROOT/'runs/dsh-desktop-9b53815d1135a901/main-task'
        candidates=list(folder.glob('attempts/*/result/import.def'))
        if not candidates:self.skipTest('real imported fixture unavailable')
        r=verify_import(ROOT/'cases/ibench/gcd_legacy/netlist/gcd.native_2d.v',candidates[0])
        self.assertTrue(r['passed'],r);self.assertEqual(r['source_instances'],255)
    def test_tampered_master_is_detected(self):
        source=ROOT/'cases/ibench/gcd_legacy/netlist/gcd.native_2d.v'
        candidates=list((ROOT/'runs/dsh-desktop-9b53815d1135a901/main-task').glob('attempts/*/result/import.def'))
        if not candidates:self.skipTest('real fixture unavailable')
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'bad.v';p.write_text(source.read_text().replace('sky130_fd_sc_hd__dfxtp_1','WRONG',1))
            self.assertIn('instance_master_mismatch',verify_import(p,candidates[0])['errors'])
    def test_unsupported_assign_and_unresolved_connections_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'a.v'
            for s in ('module g(a); input a; assign x=a; endmodule',
                      'module g(a); input a; cell u(.A(missing)); endmodule',
                      'module g(a); input a; cell u(.A(a),.A(a)); endmodule'):
                p.write_text(s)
                with self.assertRaises(ValueError):parse_flat(p)

if __name__=='__main__':unittest.main()
