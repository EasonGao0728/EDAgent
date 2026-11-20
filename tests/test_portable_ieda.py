import json
from pathlib import Path
import tempfile
import unittest

from macro_agent.portable_ieda import adapt_placement_config
from macro_agent import main_task


class PortableRuntimeTests(unittest.TestCase):
    def test_config_adaptation_preserves_quality_gate_and_source(self):
        src=Path('cases/ibench/gcd_legacy/config/pl_default_config.json')
        original=src.read_bytes()
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'pl.json';f.write_bytes(original)
            adapt_placement_config(f)
            j=json.loads(f.read_text())['PL']
            self.assertNotIn('MP',j)
            self.assertEqual(j['GP']['Nesterov']['target_overflow'],0.1)
            self.assertEqual(j['GP']['Density']['bin_cnt_x'],16)
            self.assertEqual(j['Filler'],json.loads(original)['PL']['Filler'])
            self.assertEqual(src.read_bytes(),original)

    def test_old_contract_cannot_silently_use_new_binary(self):
        with tempfile.TemporaryDirectory(dir=main_task.ROOT/'runs') as d:
            f=Path(d);state=main_task.dispatch({'run':d,'operation':'start','case_id':'sky130_gcd'})
            raw=main_task.load(f/'task.json');raw['contract']['image']='old-build';main_task.save(f/'task.json',raw)
            state=main_task.dispatch({'run':d,'operation':'observe'})
            with self.assertRaisesRegex(ValueError,'BACKEND_VERSION_CHANGED'):
                main_task.dispatch({'run':d,'operation':'act','action':'import_netlist','state_id':state['state_id'],'reason':'test','action_id':'old'},execute=lambda *_:self.fail('must not execute'))
            self.assertEqual(main_task.load(f/'task.json')['counts']['executions'],0)

    def test_source_placement_not_modified_by_local_fullflow(self):
        p=main_task.ROOT/'runs/portable-local-cli-20261105/bundle/bundle.json'
        if not p.is_file():self.skipTest('Real local fullflow integration receipt is not installed')
        v=json.loads(p.read_text());ref=v['source_def']
        self.assertEqual(main_task.file_ref(Path(ref['path']))['sha256'],ref['sha256'])
