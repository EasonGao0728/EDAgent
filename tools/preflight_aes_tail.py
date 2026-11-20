"""Diagnostic only: test post-route stages using archived failed-run output.

This never qualifies a case, runs placement/routing, or claims full-flow success.
"""
import json, shutil, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from macro_agent import aes_flow

source = ROOT / 'runs/aes-p1-20261108/downloaded/v4/server-cipher-01'
work = ROOT / 'runs/aes-p1-20261108/local-tail-preflight-v5'
reference = ROOT / 'cases/ibench/aes_sky130_t'
work.mkdir(exist_ok=False)
aes_flow.setup(work, reference)
shutil.copyfile(source / 'result/filler.def', work / 'result/filler.def')
record = {'purpose': 'diagnostic_only_no_acceptance', 'full_flow_executed': False,
          'p1_accepted': False, 'version': aes_flow.VERSION, 'created_at': time.time(),
          'source_filler_sha256': aes_flow.sha(source / 'result/filler.def'),
          'status': 'running', 'stages': []}
try:
    for stage in ('drc', 'timing', 'gds_export', 'routed_readback'):
        print('RUN ' + stage, flush=True)
        result = aes_flow.execute(stage, work, reference)
        result['stage'] = stage
        record['stages'].append(result)
        aes_flow.write(work / 'diagnostic.json', record)
        print(stage + ': ' + str(result.get('passed')), flush=True)
        if result.get('passed') is not True:
            raise RuntimeError('Diagnostic stage failed: ' + stage)
    record['status'] = 'passed_diagnostic_only'
except Exception as exc:
    record.update(status='failed', error=str(exc))
    raise
finally:
    record['finished_at'] = time.time()
    aes_flow.write(work / 'diagnostic.json', record)
