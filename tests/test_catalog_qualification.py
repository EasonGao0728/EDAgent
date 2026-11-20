import sys, unittest, tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
from qualify_catalog_native_import import inspect_def
from qualify_catalog_nangate import clock


class QualificationTests(unittest.TestCase):
    def test_pinless_tap_cells_remain_in_netlist_identity(self):
        from macro_agent.aes_netlist import parse
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/"flat.v"
            source.write_text("module d(clk); input clk; TAPCELL_X1 left (); BUF b (.A(clk)); endmodule")
            parsed=parse(source)
            self.assertEqual(parsed["components"],{"left":"TAPCELL_X1","b":"BUF"})
            self.assertEqual(sum(parsed["partitions"].values()),1)
            source.write_text("module dram(dqs); inout dqs; PAD io (.P(dqs)); endmodule")
            self.assertEqual(parse(source)["ports"],{"dqs":"inout"})

    def test_clock_from_real_sdc(self):
        self.assertEqual(clock("create_clock -name CLK -period 1.5  [get_ports CK]"),("CLK","CK"))
        simple="set n core_clock\nset period 1.8\nset p clk_i\ncreate_clock -name $n -period $period [get_ports $p]"
        self.assertEqual(clock(simple),("core_clock","clk_i"))
        with self.assertRaises(ValueError):
            clock(simple.replace("1.8","[expr 1 * 2]"))
        with self.assertRaises(ValueError):
            clock("create_clock -name clk -period 1 [get_ports ck]\ncreate_generated_clock -name div -divide_by 2 [get_pins div/Q]")

    def test_truncated_def_fails_even_if_header_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/"import.def"
            fields="DESIGN d ;\nCOMPONENTS 1 ;\n- a BUF ;\nEND COMPONENTS\nNETS 1 ;\n"
            output.write_text(fields+"END NETS\nEND DESIGN\n")
            with self.assertRaises(ValueError):
                inspect_def(output)
            output.write_text(fields+"- x ( a Z ) ;\nEND NETS\nEND DESIGN\n")
            self.assertEqual(inspect_def(output),("d",1,1))


if __name__=="__main__":
    unittest.main()
