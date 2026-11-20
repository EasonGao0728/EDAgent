import tempfile
from pathlib import Path
import unittest
from macro_agent.ieda_runtime import parse_placement_report, run_case

class IedaRuntimeTests(unittest.TestCase):
    def test_missing_or_nonzero_checks_do_not_pass(self):
        rows={'Instances Count':'932','Nets Count':'675','- Macro Count':'0','Total HPWL':'9953606',
              'Core Range Violated Count':'0','Row/Site Alignment Violated Count':'0',
              'Power Alignment Violated Count':'0','Overlap Violated Count':'1'}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'summary.txt'
            path.write_text('\n'.join(f'| {k} | {v} |' for k,v in rows.items()))
            self.assertFalse(parse_placement_report(path)['placement_checks_passed'])
            del rows['Overlap Violated Count']
            path.write_text('\n'.join(f'| {k} | {v} |' for k,v in rows.items()))
            with self.assertRaises(KeyError): parse_placement_report(path)

    def test_reject_unknown_case_and_output_escape_before_execution(self):
        with self.assertRaises(ValueError): run_case('C:/outside','arbitrary')
        with self.assertRaises(ValueError): run_case('C:/outside','sky130_gcd')

if __name__=='__main__': unittest.main()
