import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from macro_agent import hold_calibration as h


class HoldCalibrationTests(unittest.TestCase):
    def test_paths_cannot_follow_private_symlinks_or_escape(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'authorized';root.mkdir()
            self.assertEqual(h.checked_path(root/'a',root),root/'a')
            with self.assertRaises(ValueError):h.checked_path(root/'../private',root)

    def test_copy_does_not_overwrite_different_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'src').write_text('a');(p/'dst').write_text('b')
            with self.assertRaises(ValueError):h.copy_source(p/'src',p/'dst',p)
            self.assertEqual((p/'dst').read_text(),'b')

    def report(self,d,rows):
        p=Path(d)/'result/estimated/timing_result.json';p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps({'FLUTE':{'clock_timings':rows}}))

    def test_estimated_measurement_requires_every_expected_clock(self):
        with tempfile.TemporaryDirectory() as d:
            self.report(d,[{'clock_name':'a','setup_wns':1,'setup_tns':0,'hold_wns':-.2,'hold_tns':-2}])
            with self.assertRaises(ValueError):h.estimated(d,[{'name':'a'},{'name':'b'}])
            r=h.estimated(d,[{'name':'a'}]);self.assertEqual(r['min_tns_ns'],-2)

    def test_nonfinite_timing_cannot_pass(self):
        with tempfile.TemporaryDirectory() as d:
            self.report(d,[{'clock_name':'a','setup_wns':float('nan'),'setup_tns':0,'hold_wns':1,'hold_tns':0}])
            with self.assertRaises(ValueError):h.estimated(d,[{'name':'a'}])

    def test_reused_stage_must_match_source_and_output(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);src=p/'source';src.write_text('source');out=p/'output';out.write_text('out')
            e={'source':{'sha256':h.sha(src)},'artifact':{'path':str(out),'sha256':h.sha(out)},'action':'hold','cap':.05,'passed':True}
            h.save(p/'evidence.json',e)
            with patch.object(h,'native',side_effect=AssertionError('no native run')):
                self.assertTrue(h.stage(p,src,p,'hold',.05)['passed'])
                with self.assertRaises(ValueError):h.stage(p,src,p,'hold',.1)
                src.write_text('changed')
                with self.assertRaises(ValueError):h.stage(p,src,p,'hold',.05)

    def test_incomplete_attempt_never_resubmitted(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'stage.tcl').write_text('old')
            with patch.object(h,'native',side_effect=AssertionError('no native run')):
                with self.assertRaises(ValueError):h.stage(p,p/'missing',p,'hold',.05)

    def test_failed_evidence_never_accepted_as_cache(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);h.save(p/'evidence.json',{'passed':False})
            with patch.object(h,'native',side_effect=AssertionError('no native retry')):
                with self.assertRaises(ValueError):h.stage(p,p/'missing',p,'hold',.05)


if __name__=='__main__':unittest.main()
