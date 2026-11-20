import ast, tempfile, unittest
from pathlib import Path
from macro_agent.aes_flow import prune_duplicate_drc_exports

class StorageDedupTests(unittest.TestCase):
    def fixture(self, root):
        report=root/'result/report';(report/'drc.rpt.artifacts').mkdir(parents=True)
        for name in ('violations.json','violation_map.json'):
            (report/name).write_bytes(b'{"count":3,"violations":[1,2,3]}')
            (report/'drc.rpt.artifacts'/name).write_bytes((report/name).read_bytes())
        return report

    def test_complete_details_preserved_and_operation_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);report=self.fixture(root)
            expected=(report/'violations.json').read_bytes()
            rows=prune_duplicate_drc_exports(root)
            self.assertEqual(len(rows),2)
            for name in ('violations.json','violation_map.json'):
                self.assertEqual((report/name).read_bytes(),expected)
                self.assertFalse((report/'drc.rpt.artifacts'/name).exists())
            self.assertEqual(prune_duplicate_drc_exports(root),[])

    def test_mismatch_in_second_file_prevents_all_deletion(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);report=self.fixture(root)
            (report/'drc.rpt.artifacts/violation_map.json').write_bytes(b'different')
            with self.assertRaisesRegex(ValueError,'differs'):prune_duplicate_drc_exports(root)
            self.assertTrue((report/'drc.rpt.artifacts/violations.json').exists())

    def test_missing_canonical_does_not_delete_original(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);report=self.fixture(root);(report/'violations.json').unlink()
            with self.assertRaisesRegex(ValueError,'Unsafe'):prune_duplicate_drc_exports(root)
            self.assertTrue((report/'drc.rpt.artifacts/violations.json').exists())

    def test_all_native_execution_ast_is_unchanged(self):
        root=Path(__file__).resolve().parents[1]
        before=ast.parse((root/'runs/aes-p1-20261108/policy-revision-20261109/macro_agent/aes_flow.py').read_text())
        after=ast.parse((root/'macro_agent/aes_flow.py').read_text())
        after.body=[n for n in after.body if not(isinstance(n,ast.FunctionDef) and n.name=='prune_duplicate_drc_exports')]
        class RemoveStorageCalls(ast.NodeTransformer):
            def visit_If(self,node):
                if len(node.body)==1 and not node.orelse and isinstance(node.body[0],ast.Expr):
                    call=node.body[0].value
                    if isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='prune_duplicate_drc_exports':return None
                return self.generic_visit(node)
        after=RemoveStorageCalls().visit(after)
        self.assertEqual(ast.dump(before),ast.dump(after))

if __name__=='__main__':unittest.main()
