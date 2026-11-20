import importlib.util,sys,types,unittest
from pathlib import Path

# The scanner itself is portable; the resource-limited entry point runs on Linux.
if sys.platform=='win32':sys.modules.setdefault('resource',types.ModuleType('resource'))
spec=importlib.util.spec_from_file_location('case_inventory',Path(__file__).resolve().parents[1]/'tools/inventory_case_features.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def module(name):
    s=importlib.util.spec_from_file_location(name,Path(__file__).resolve().parents[1]/'tools'/f'{name}.py')
    x=importlib.util.module_from_spec(s);s.loader.exec_module(x);return x

c=module('inventory_case_constraints')
l=module('extract_case_library_catalog')
b=module('build_case_perception_report')

class InventoryTests(unittest.TestCase):
    def test_hierarchy_counts_instance_multiplicity_not_definitions(self):
        v=m.structural('module sub(a); input a; BUF_X1 b(.A(a)); endmodule module top(a); input a; sub s1(.a(a)); sub s2(.a(a)); DFF_X1 r(.D(a)); endmodule','top')
        self.assertEqual(v['masters'],{'BUF_X1':2,'DFF_X1':1});self.assertEqual(v['modules'],2)
    def test_escaped_identifiers_and_bus_ports(self):
        v=m.structural('module top(a); input [7:0] a; BUF_X1 \\u.1 (.A(a[0])); endmodule','top')
        self.assertEqual(v['cell_count'],1);self.assertEqual(v['top_pin_bits'],8)
    def test_unsupported_rtl_is_not_counted_as_complete(self):
        v=m.structural('module top(a); input a; always @(a) begin end endmodule','top')
        self.assertEqual(v['status'],'partial')
    def test_ansi_ports_are_not_reported_as_verified_zero(self):
        v=m.structural('module top(input a); BUF_X1 b(.A(a)); endmodule','top')
        self.assertEqual(v['status'],'partial');self.assertIn('unsupported_ANSI_port_header',v['issues'])
    def test_recursive_hierarchy_rejected(self):
        with self.assertRaisesRegex(ValueError,'recursive'):m.structural('module top(a); input a; top t(a); endmodule','top')
    def test_statistics_hash_binds_specific_output(self):
        self.assertEqual(m.expected_hash({'output_sha256':{'netlist/current.v':'good','other.v':'bad'}},'netlist/current.v'),'good')
        self.assertIsNone(m.expected_hash({'output_sha256':{'other.v':'bad'}},'netlist/current.v'))
    def test_lef_whitespace_does_not_lose_area(self):
        cells=l.lef_cells('  MACRO C\n CLASS CORE ;\n SIZE  1.4   BY  2.8 ;\n END C\nMACRO R\nCLASS BLOCK ;\nSIZE 1e2 BY 20 ;\nEND R\n')
        self.assertAlmostEqual(cells['C']['area_um2'],3.92)
        self.assertEqual(cells['R']['area_um2'],2000);self.assertTrue(cells['R']['macro'])
    def test_sdc_numeric_constant_only_no_tcl_execution(self):
        p=c.profile('set period 10.5\ncreate_clock -period $period [get_ports clk]\nset evil [exec something]\ncreate_clock -period $evil [get_ports clk2]')
        self.assertEqual(p['clocks'][0]['period_sdc_units'],10.5)
        self.assertIsNone(p['clocks'][1]['period_sdc_units']);self.assertFalse(p['tcl_executed'])
    def test_missing_library_is_unknown_not_zero_sequential(self):
        r={'origin':'shared','case_id':'x','pdk':'unknown','counts':{'cell_count':2,'masters':{'unmapped_ff':2},'top_pin_bits':1},'macro_instances':0}
        x=b.enrich([r],[],[])[0]
        self.assertIsNone(x['sequential']['count']);self.assertIsNone(x['reference_geometry']['all_cell_area_um2'])
    def test_family_split_groups_related_aes_and_peripheral_variants(self):
        self.assertEqual(b.family({'case_id':'aes_core_sky130_t'}),b.family({'case_id':'aes'}))
        self.assertEqual(b.family({'case_id':'x','logical_design_declared':'apb4_timer'}),b.family({'case_id':'y','logical_design_declared':'osip_timer'}))

if __name__=='__main__':unittest.main()
