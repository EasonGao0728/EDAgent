import sys, unittest, tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
from qualify_catalog_native_import import inspect_def
from qualify_catalog_nangate import clock


class QualificationTests(unittest.TestCase):
    def test_clock_from_real_sdc(self):
        self.assertEqual(clock("create_clock -name CLK -period 1.5  [get_ports CK]"),("CLK","CK"))
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
