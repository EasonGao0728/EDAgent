import json,tempfile,unittest
from pathlib import Path
from macro_agent.main_decisions import store


class PlanningBudgetTests(unittest.TestCase):
    def test_sub_limit_matches_contract_and_existing_state_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.assertEqual(store(root)['model_call_limit'],40)
            (root/'task.json').write_text(json.dumps({'contract':{'budget':{'model_calls':64}}}))
            self.assertEqual(store(root)['model_call_limit'],64)
            (root/'main-decisions.json').write_text(json.dumps({'model_call_limit':40,'model_calls':32}))
            self.assertEqual(store(root),{'model_call_limit':40,'model_calls':32})


if __name__=='__main__':unittest.main()
