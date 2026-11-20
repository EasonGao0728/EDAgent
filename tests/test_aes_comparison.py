import json,tempfile,unittest
from pathlib import Path
from tools.compare_aes_runs import ROOT,routes,normalized_script,timing_text,violation_records,gds_geometry_equal

class ComparisonTests(unittest.TestCase):
    def test_gds_exact_geometry_ignores_hierarchy_but_not_shape_or_units(self):
        import klayout.db as db
        left,right=db.Layout(),db.Layout();left.dbu=right.dbu=.001
        a,b=left.create_cell('top'),right.create_cell('top');child=right.create_cell('child')
        a.shapes(left.layer(1,0)).insert(db.Box(0,0,10,20))
        child.shapes(right.layer(1,0)).insert(db.Box(0,0,10,20));b.insert(db.CellInstArray(child.cell_index(),db.Trans()))
        self.assertTrue(gds_geometry_equal(left,right,'top'))
        child.shapes(right.layer(1,0)).insert(db.Box(10,0,11,20))
        self.assertFalse(gds_geometry_equal(left,right,'top'))
        self.assertFalse(gds_geometry_equal(left,left,'missing'))
        right.dbu=.002;self.assertFalse(gds_geometry_equal(left,right,'top'))

    def test_real_route_record_order_difference_is_canonicalized(self):
        base=ROOT/'runs/portable-baseline-20261105'
        a=base/'server-4/result/routing.def';b=base/'local-4/result/routing.def'
        self.assertNotEqual(a.read_bytes(),b.read_bytes());self.assertEqual(routes(a),routes(b))
    def test_only_script_line_endings_are_normalized(self):
        with tempfile.TemporaryDirectory() as t:
            a=Path(t)/'a.tcl';b=Path(t)/'b.tcl'
            a.write_bytes(b'puts OK\nexit\n');b.write_bytes(b'puts OK\r\nexit\r\n')
            self.assertEqual(normalized_script(a),normalized_script(b))
            b.write_bytes(b'puts WRONG\r\nexit\r\n');self.assertNotEqual(normalized_script(a),normalized_script(b))
    def test_violation_locations_and_count_are_checked(self):
        source=ROOT/'runs/portable-baseline-20261105/server-4/result/report/violations.json'
        actual=violation_records(source)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'v.json';d=json.loads(source.read_text())
            d['violations'][0]['bbox'][0]+=1;p.write_text(json.dumps(d))
            self.assertNotEqual(actual,violation_records(p))
            d['count']+=1;p.write_text(json.dumps(d))
            with self.assertRaisesRegex(ValueError,'count mismatch'):violation_records(p)
    def test_timing_numbers_survive_header_normalization(self):
        with tempfile.TemporaryDirectory() as t:
            a=Path(t)/'a';b=Path(t)/'b'
            a.write_text('Generate the report at yesterday\niSTA elapsed time: 1s\nSlack -1.2\n')
            b.write_text('Generate the report at today\niSTA elapsed time: 5s\nSlack -1.2\n')
            self.assertEqual(timing_text(a),timing_text(b))
            b.write_text('Slack -1.1\n');self.assertNotEqual(timing_text(a),timing_text(b))
    def test_streaming_details_preserve_order_invariance_and_duplicates(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'a.json';q=Path(t)/'b.json'
            rows=[{'bbox':[1,2,3,4],'net':'a','value':1.25},{'net':'b','bbox':[2,3,4,5]}]
            meta={'count':3,'coordinate_units':'DBU','dbu_per_micron':1000}
            p.write_text(json.dumps({**meta,'violations':[rows[0],rows[1],rows[0]]}))
            q.write_text(json.dumps({'violations':[rows[1],rows[0],rows[0]],**meta},indent=2))
            self.assertEqual(violation_records(p),violation_records(q))
            q.write_text(json.dumps({**meta,'violations':[rows[1],rows[1],rows[0]]}))
            self.assertNotEqual(violation_records(p),violation_records(q))
            q.write_text(p.read_text()[:-2])
            with self.assertRaisesRegex(ValueError,'truncated'):violation_records(q)
if __name__=='__main__':unittest.main()
