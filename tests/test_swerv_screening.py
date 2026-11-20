import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from macro_agent import swerv_screening as study, swerv_backend, remote_client
from macro_agent.def_validation import read_def


class ScreeningTests(unittest.TestCase):
    def test_io_stale_coordinate_reproduces_false_short_hpwl(self):
        from tools.analyze_swerv_screening import pin_hpwl
        cells={'BUF':{'size':(2,1),'pins':{'A':(0,0)}}}
        text='DESIGN x ;\nUNITS DISTANCE MICRONS 2000 ;\nCOMPONENTS 1 ;\n- u BUF + PLACED ( 2000 4000 ) N ;\nEND COMPONENTS\nPINS 1 ;\n- p + NET n + PORT + LAYER metal5 ( -400 -400 ) ( 400 400 ) + PLACED ( 200000 400000 ) N ;\nEND PINS\nNETS 1 ;\n- n ( u A ) ( PIN p ) ;\nEND NETS\nEND DESIGN\n'
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.def';p.write_text(text)
            self.assertEqual(round(pin_hpwl(p,cells)['all_um']*2000),594000)
            self.assertEqual(round(pin_hpwl(p,cells,(-1,-1))['all_um']*2000),6002)

    def test_idb_rectangle_mean_is_not_pin_bounding_box_center(self):
        from tools import analyze_swerv_screening as analysis
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);lef=root/'cases/ibench/swerv_nangate45/pdk/lef';lef.mkdir(parents=True)
            (lef/'cell.lef').write_text('MACRO BUF\nSIZE 12 BY 2 ;\n PIN A\n PORT\n LAYER metal1 ;\n RECT 0 0 1 1 ;\n RECT 2 0 3 1 ;\n RECT 10 0 12 1 ;\n END\n END A\nEND BUF\n')
            with patch.object(analysis,'ROOT',root):
                self.assertEqual(analysis.library()['BUF']['pins']['A'],(6,.5))
                self.assertEqual(analysis.library('idb_rect_mean')['BUF']['pins']['A'],(4.6665,.5))

    def test_independent_pin_hpwl_uses_orientation_and_dbu(self):
        from tools.analyze_swerv_screening import pin_hpwl
        cells={'BUF':{'size':(2,1),'pins':{'A':(.25,.5),'Z':(1.75,.5)}}}
        text='DESIGN x ;\nUNITS DISTANCE MICRONS 1000 ;\nCOMPONENTS 2 ;\n- u BUF + PLACED ( 0 0 ) N ;\n- v BUF + PLACED ( 10000 0 ) FN ;\nEND COMPONENTS\nNETS 1 ;\n- n ( u Z ) ( v A ) + USE SIGNAL ;\nEND NETS\nEND DESIGN\n'
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.def';p.write_text(text)
            self.assertEqual(pin_hpwl(p,cells)['all_um'],10)
            p.write_text(text.replace('10000 0 ) FN','10000 0 ) N'))
            self.assertEqual(pin_hpwl(p,cells)['all_um'],8.5)

    def test_macro_seed_changes_only_selected_coordinates(self):
        m=swerv_backend.manifest()
        rows=['- '+n+' '+c+' + FIXED ( 1000 1000 ) N' for n,c in m['expected_macro_masters'].items()]
        rows+=['- cell BUF_X4 + UNPLACED']
        text='VERSION 5.8 ;\nDESIGN swerv_wrapper ;\nUNITS DISTANCE MICRONS 2000 ;\nDIEAREA ( 0 0 ) ( 675260 691600 ) ;\nCOMPONENTS 4 ;\n'+' ;\n'.join(rows)+' ;\nEND COMPONENTS\nNETS 1 ;\n- n ( cell A ) ( PIN port ) ;\nEND NETS\nPINS 1 ;\n- port + NET n + FIXED ( 100 100 ) N ;\nEND PINS\nEND DESIGN\n'
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'input.def';out=Path(d)/'candidate.def';source.write_text(text)
            r=study.historical_seed(source,out,m)
            self.assertTrue(r['other_parsed_fields_equal'])
            self.assertEqual(source.read_text(),text)
            a,b=read_def(source),read_def(out)
            self.assertEqual(a['nets'],b['nets']);self.assertEqual(a['pins'],b['pins'])
            self.assertEqual(a['components']['cell'],b['components']['cell'])
            self.assertEqual(b['components']['gen_11599_']['placement'],['FIXED',420000,12200,'N'])
            bad=dict(m);bad['core_area_microns']=[0,0,1,1]
            with self.assertRaisesRegex(ValueError,'outside core'):study.historical_seed(source,out,bad)

    def test_transport_never_accepts_arbitrary_action_or_retries_timeout(self):
        with patch.object(remote_client.subprocess,'run') as p:
            with self.assertRaises(ValueError):remote_client.swerv_screening('routing')
            p.assert_not_called()
            p.side_effect=remote_client.subprocess.TimeoutExpired('ssh',45)
            with self.assertRaisesRegex(RuntimeError,'REMOTE_REPLY_UNKNOWN'):remote_client.swerv_screening('start')
            self.assertEqual(p.call_count,1)


if __name__=='__main__':unittest.main()
