import tempfile,unittest
from pathlib import Path
import klayout.db as db
from macro_agent.native_gds import validate


class SingleTerminalGds(unittest.TestCase):
    def check(self,ends=1,routed=False,geometry=False,referenced=True,io_geometry=True):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);g=p/'sample.gds';d=p/'sample.def';lef=p/'tech.lef'
            lef.write_text('LAYER metal1\n TYPE ROUTING ;\nEND metal1\n')
            endpoints=' '.join('( PIN p%d )'%i for i in range(ends))
            route=' + ROUTED metal1 ( 100 100 ) ( 200 100 )' if routed else ''
            d.write_text('VERSION 5.8 ;\nDESIGN sample ;\nUNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 1000 1000 ) ;\nCOMPONENTS 0 ;\nEND COMPONENTS\nPINS 2 ;\n- p0 + NET test + LAYER metal1 ( 0 0 ) ( 10 10 ) + FIXED ( 100 100 ) N ;\n- p1 + NET test + LAYER metal1 ( 0 0 ) ( 10 10 ) + FIXED ( 200 100 ) N ;\nEND PINS\nNETS 1 ;\n- test '+endpoints+route+' ;\nEND NETS\nEND DESIGN\n')
            layout=db.Layout();layout.dbu=.001;top=layout.create_cell('sample')
            top.shapes(layout.layer(0,2)).insert(db.Box(0,0,1000,1000))
            pins=layout.create_cell('PINS');top.insert(db.CellInstArray(pins.cell_index(),db.Trans()))
            if io_geometry:
                for x in (100,200):pins.shapes(layout.layer(0,0)).insert(db.Box(x,100,x+10,110))
            if referenced:
                net=layout.create_cell('test');top.insert(db.CellInstArray(net.cell_index(),db.Trans()))
                if geometry:net.shapes(layout.layer(0,0)).insert(db.Box(99,99,202,102))
            layout.write(str(g));return validate(g,d,lef,[])

    def test_unrouted_single_terminal_retained(self):
        v=self.check();self.assertTrue(v['passed'],v['errors'])
        self.assertEqual(v['unrouted_single_terminal_nets_checked'],['test'])

    def test_single_terminal_reference_required(self):
        self.assertIn('missing_single_terminal_net:test',self.check(referenced=False)['errors'])

    def test_missing_real_route_still_rejected(self):
        self.assertIn('missing_routed_net:test',self.check(ends=2)['errors'])

    def test_explicit_single_terminal_route_still_checked(self):
        self.assertIn('missing_routed_net:test',self.check(routed=True)['errors'])
        self.assertTrue(self.check(routed=True,geometry=True)['passed'])

    def test_spurious_unrouted_geometry_rejected(self):
        self.assertIn('unexpected_geometry_on_unrouted_single_terminal_net:test',self.check(geometry=True)['errors'])

    def test_pin_geometry_check_unchanged(self):
        self.assertIn('io_shape_mismatch:p0',self.check(io_geometry=False)['errors'])

    def test_empty_declaration_behavior_preserved(self):
        v=self.check(ends=0);self.assertTrue(v['passed'],v['errors'])
        self.assertEqual(v['declared_empty_nets_checked'],['test'])

    def test_multi_terminal_route_geometry_passes(self):
        self.assertTrue(self.check(ends=2,routed=True,geometry=True)['passed'])

if __name__=='__main__':unittest.main()
