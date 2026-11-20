import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macro_agent import hold_repair as r, hold_calibration as h


class RepairTests(unittest.TestCase):
    def elf(self):
        data=bytearray(256)
        data[:6]=b'\x7fELF\x02\x01'
        struct.pack_into('<H',data,18,62)
        struct.pack_into('<Q',data,32,64)
        struct.pack_into('<HH',data,54,56,1)
        struct.pack_into('<IIQQQQQQ',data,64,1,5,128,0xd2b7b6,0,64,64,4096)
        data[128:138]=bytes.fromhex('66 2e 0f 1f 84 00 00 00 00 00')
        return bytes(data)

    def test_patch_is_identity_pinned_and_changes_only_reserved_nop(self):
        data=self.elf()
        with self.assertRaisesRegex(ValueError,'IDENTITY'):r.guarded_binary(data)
        with patch.object(r,'BASE_SHA',r.hashlib.sha256(data).hexdigest()):
            out,meta=r.guarded_binary(data)
        self.assertEqual(meta['file_offset'],128)
        self.assertEqual(out[:128],data[:128]);self.assertEqual(out[138:],data[138:])
        self.assertEqual(out[128:138],bytes.fromhex('85 d2 75 04 ff 44 24 2c 66 90'))

    def test_patch_rejects_changed_instructions_even_with_matching_identity(self):
        data=bytearray(self.elf());data[128]=0x90;data=bytes(data)
        with patch.object(r,'BASE_SHA',r.hashlib.sha256(data).hexdigest()):
            with self.assertRaisesRegex(ValueError,'INSTRUCTION'):r.guarded_binary(data)

    def test_rc_comparison_rejects_nan_and_material_difference(self):
        a=dict.fromkeys(r.TIMING_KEYS,0.)
        self.assertTrue(r.comparable(a,a))
        self.assertFalse(r.comparable(a,{**a,'min_worst_slack_ns':float('nan')}))
        self.assertFalse(r.comparable(a,{**a,'max_tns_ns':.001}))

    def test_direct_flute_does_not_claim_sta_initialization(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'result/estimated/timing_result.json';p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'FLUTE':{'clock_timings':[{'clock_name':'clk','setup_wns':1,'setup_tns':0,'hold_wns':0,'hold_tns':0}]}}))
            out=h.estimated(d,[{'name':'clk'}],'direct_flute')
            self.assertIn('without prior STA',out['method'])
            with self.assertRaisesRegex(ValueError,'INITIALIZATION'):h.estimated(d,[{'name':'clk'}],'unknown')
            (Path(d)/'stage.tcl').write_text('run_timing_eval -routing_type FLUTE')
            with self.assertRaisesRegex(ValueError,'PROTOCOL_SCRIPT'):h.estimated(d,[{'name':'clk'}])

    def test_resume_requires_qualified_measurement_before_native(self):
        with tempfile.TemporaryDirectory() as d,patch.object(r,'OUT',Path(d)),patch.object(h,'native',side_effect=AssertionError('must not run')):
            p=Path(d)/'rc-qualification/qualification.json';p.parent.mkdir();p.write_text('{"comparative_estimated_screening_qualified": false}')
            with self.assertRaisesRegex(ValueError,'MEASUREMENT_GATE'):r.resume_budgets(Path(d)/'resume')


if __name__=='__main__':unittest.main()
