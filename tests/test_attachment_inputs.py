import hashlib
from pathlib import Path
import tempfile
import unittest
from macro_agent import ieda_stages
from macro_agent.main_task import ROOT, dispatch, load, task_backend


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'runs')
        self.folder = Path(self.temp.name)
        reference, _ = ieda_stages.REGISTERED_CASES['ibench_gcd_legacy']
        m = ieda_stages.manifest('ibench_gcd_legacy')
        self.files = []
        for rel in [m['netlist'], m['tech_lef'], *m['cell_lefs'], *m['libs'], m['sdc'], 'manifest.json', 'design.json']:
            source = reference/rel
            data = source.read_bytes()
            upload = self.folder/source.name
            upload.write_bytes(data)
            self.files.append({'name':source.name,'path':str(upload),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})

    def tearDown(self):
        self.temp.cleanup()

    def start(self, files):
        return dispatch({'run':str(self.folder/'task'), 'operation':'start',
                         'case_id':'ibench_gcd_legacy', 'attachment_inputs':files})

    def test_uploads_are_actual_frozen_backend_inputs(self):
        result = self.start(self.files)
        self.assertEqual(result['contract']['input_source'], 'conversation_attachments')
        root = Path(result['contract']['input_root'])
        bound = task_backend(load(self.folder/'task/task.json'))
        self.assertTrue(all(p.is_relative_to(root) for p in bound.input_files()))
        self.assertEqual(bound.manifest()['core_site'], 'unithd')
        for item in result['contract']['attachment_import']['files']:
            Path(item['path']).write_bytes(b'changed upload after freezing')
            self.assertEqual(hashlib.sha256(Path(item['frozen_path']).read_bytes()).hexdigest(),item['sha256'])
        work = self.folder/'work';work.mkdir();bound.setup(work)
        self.assertIn('sky130_fd_sc_hd', (work/'script/DB_script/db_path_setting.tcl').read_text())

    def test_missing_duplicate_and_corrupt_uploads_rejected_before_task_start(self):
        for files in [self.files[:-1], self.files+[self.files[0]], [{**self.files[0],'sha256':'0'*64},*self.files[1:]]]:
            with self.assertRaises(ValueError): self.start(files)
            self.assertFalse((self.folder/'task/task.json').exists())

    def test_changed_netlist_is_not_silently_replaced_by_registered_source(self):
        item = self.files[0]
        data = Path(item['path']).read_bytes()+b'\n// changed\n'
        Path(item['path']).write_bytes(data)
        item.update(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
        with self.assertRaisesRegex(ValueError,'differs from reviewed'): self.start(self.files)

    def test_real_sram_nine_file_pack_is_frozen_without_reference_substitution(self):
        source = ROOT/'inputs/sram_pair_chat'
        files = [{'name':p.name,'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                  'bytes':p.stat().st_size,'transport':'desktop_file_reference'}
                 for p in source.iterdir() if p.is_file()]
        self.assertEqual(len(files),9)
        result = dispatch({'run':str(self.folder/'sram-task'),'operation':'start',
                           'case_id':'sky130_sram_pair','goal':'placement_def','attachment_inputs':files})
        self.assertEqual(result['contract']['input_source'],'conversation_attachments')
        receipt = result['contract']['attachment_import']
        self.assertEqual(len(receipt['files']),9)
        for item in receipt['files']:
            self.assertEqual(hashlib.sha256(Path(item['frozen_path']).read_bytes()).hexdigest(),item['sha256'])
            self.assertTrue(Path(item['frozen_path']).is_relative_to(Path(receipt['input_root'])))
        bound = task_backend(load(self.folder/'sram-task/task.json'))
        self.assertEqual(bound.manifest()['macro_placement']['macros'],['mem0','mem1'])
        self.assertIn('macro_placement',bound.STAGES)
