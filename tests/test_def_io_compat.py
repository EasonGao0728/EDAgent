import tempfile,unittest
from pathlib import Path
from macro_agent.def_io_compat import convert,write_equivalent,equivalent


class IOCompatibilityTests(unittest.TestCase):
    def fixture(self,extra=''):
        return 'DESIGN x ;\nUNITS DISTANCE MICRONS 2000 ;\nCOMPONENTS 0 ;\nEND COMPONENTS\nPINS 1 ;\n- data[0] + NET n + DIRECTION INPUT + USE SIGNAL + PORT + LAYER metal5 ( -400 -400 ) ( 400 400 ) + PLACED ( 960 417900 ) E '+extra+' ;\nEND PINS\nNETS 1 ;\n- n ( PIN data[0] ) ;\nEND NETS\nEND DESIGN\n'
    def test_equivalent_syntax_does_not_relocate_pin_or_change_net(self):
        with tempfile.TemporaryDirectory() as d:
            a,b,c=[Path(d)/n for n in ('a.def','b.def','c.def')];raw=self.fixture();a.write_text(raw)
            r=write_equivalent(a,b);self.assertEqual(r['changed_pins'],1);self.assertTrue(equivalent(a,b))
            self.assertNotIn('+ PORT',b.read_text());self.assertIn('( 960 417900 ) E',b.read_text())
            write_equivalent(b,c,explicit=True);self.assertTrue(equivalent(a,c));self.assertEqual(a.read_text(),raw)
            with self.assertRaises(ValueError):write_equivalent(a,a)
    def test_rejects_multiport_and_unsupported_geometry(self):
        with self.assertRaisesRegex(ValueError,'multi-PORT'):convert(self.fixture('+ PORT + LAYER metal6 ( 0 0 ) ( 1 1 ) + PLACED ( 2 2 ) N'))
        with self.assertRaisesRegex(ValueError,'Unsupported'):convert(self.fixture('+ VIA v12'))
    def test_semantic_check_rejects_real_io_move(self):
        with tempfile.TemporaryDirectory() as d:
            a,b=[Path(d)/n for n in ('a.def','b.def')];a.write_text(self.fixture());b.write_text(self.fixture().replace('960 417900','960 417901'))
            self.assertFalse(equivalent(a,b))

if __name__=='__main__':unittest.main()
