"""Mutation checks on real frozen reports; never modify the run evidence."""
import json, shutil, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from tools.audit_aes_timing_ties import audit, read_def

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'runs/aes-p1-20261108/downloaded/v5/server-cipher-01'
TASK=ROOT/'runs/dsh-desktop-262a748e730bc1db/main-task/task.json'


@unittest.skipUnless(BASE.exists() and TASK.exists(),'Frozen AES diagnostic evidence unavailable')
class TimingTieGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.desktop=Path(json.loads(TASK.read_text(encoding='utf-8'))['accepted_work'])
        cls.design=read_def(BASE/'result/filler.def')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.a=Path(self.tmp.name)/'server';self.b=Path(self.tmp.name)/'desktop'
        for src,dest in ((BASE,self.a),(self.desktop,self.b)):
            shutil.copytree(src/'result/timing',dest/'result/timing',ignore=shutil.ignore_patterns('*.v','*.skew','*.cap','*.trans','*.fanout'))
        mock=patch('tools.audit_aes_timing_ties.read_def',return_value=self.design)
        mock.start();self.addCleanup(mock.stop)

    def check(self):return audit(self.a,self.b,'aes_cipher_top')

    def report_change(self,old,new):
        p=self.b/'result/timing/aes_cipher_top.rpt';s=p.read_text();self.assertIn(old,s)
        p.write_text(s.replace(old,new,1))

    def test_real_equivalent_minimum_paths(self):
        r=self.check();self.assertTrue(r['passed']);self.assertEqual(len(r['different_selected_paths']),3)
        self.assertFalse(r['exact_report_text_equal'])

    def test_tns_change_rejected(self):
        self.report_change('-473.987','-473.986')
        with self.assertRaisesRegex(ValueError,'TNS'):self.check()

    def test_setup_value_change_rejected(self):
        self.report_change('4.213f','4.214f')
        with self.assertRaisesRegex(ValueError,'not a tied'):self.check()

    def test_subdisplay_precision_change_rejected(self):
        p=self.b/'result/timing/wire_paths/wire_path_4.json';d=json.loads(p.read_text())
        d[1]['inst_arc_0']['Incr']+=0.000000001;p.write_text(json.dumps(d))
        with self.assertRaisesRegex(ValueError,'precision'):self.check()

    def test_disconnected_pin_rejected(self):
        p=self.b/'result/timing/wire_paths/wire_path_4.json';d=json.loads(p.read_text())
        d[3]['node_2']['Point']=d[3]['node_2']['Point'].replace(':A0 ',':NONEXISTENT ')
        p.write_text(json.dumps(d))
        with self.assertRaisesRegex(ValueError,'not connected'):self.check()

    def test_nonzero_ideal_clock_delay_rejected(self):
        p=self.b/'result/timing/aes_cipher_top.rpt';lines=p.read_text().splitlines();points=0
        for i,line in enumerate(lines):
            if line.startswith('| Point '):points+=1
            if points==4 and line.startswith('| clock network delay (ideal)'):
                fields=line.split('|');fields[7]=' 0.001 ';lines[i]='|'.join(fields);break
        else:self.fail('Clock row missing')
        p.write_text('\n'.join(lines))
        with self.assertRaisesRegex(ValueError,'Nonzero clock'):self.check()

    def test_missing_full_precision_path_rejected(self):
        (self.b/'result/timing/wire_paths/wire_path_4.json').unlink()
        with self.assertRaises(FileNotFoundError):self.check()


if __name__=='__main__':unittest.main()
