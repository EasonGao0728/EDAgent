from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from macro_agent.adapters.toy import load_case
from macro_agent.geometry import hpwl

case = load_case(ROOT / "cases/toy/connected_groups.json")
print(f"{case['case_id']} | {len(case['nets'])} nets | weighted HPWL = {hpwl(case):g} {case['units']}")
