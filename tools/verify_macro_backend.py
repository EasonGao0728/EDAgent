"""Operator-only commissioning: run fixed adapters before admitting tool cards.

Does not invoke an LLM or bypass the production Dispatcher. This is a bounded
installation smoke test; only successful geometry/report/roundtrip checks
produce admission evidence. All logs remain in a fresh run directory.
"""
import argparse,json
from pathlib import Path
from macro_agent import openroad_stages as backend
from macro_agent import ieda_runtime as rt
from macro_agent.placement_registry import record_verification

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True)
    args=parser.parse_args();work=Path(args.run).resolve()
    if not work.is_relative_to((backend.ROOT/'runs').resolve()):raise ValueError('Run must be under runs')
    if work.exists():raise ValueError('Use a fresh run directory; historical failures are retained')
    # Probe installed immutable image before provisioning work files.
    cfg=backend.config();rt.invoke(['image','inspect',cfg['image'],'--format','{{.Id}}'],timeout=10)
    version=rt.invoke(['run','--pull=never','--rm','--network','none','--entrypoint',cfg['executable'],cfg['image'],'-version'],timeout=20).strip()
    cfg['version']=version
    (backend.ROOT/'.cache/openroad').mkdir(parents=True,exist_ok=True)
    (backend.ROOT/'.cache/openroad/backend.json').write_text(json.dumps(cfg,indent=2),encoding='utf-8')
    work.mkdir();backend.setup(work)
    report={'status':'running','case':'nangate_macro_smoke','backend':cfg,'stages':[],
            'scope':'derived public integration fixture, fake macro models; no PPA claims'}
    target=work/'verification.json'
    try:
        for stage in backend.STAGES:
            result=backend.execute(stage,work);report['stages'].append({'stage':stage,'result':result})
            target.write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps({'stage':stage,'status':'passed','result':result}),flush=True)
        report['status']='completed';target.write_text(json.dumps(report,indent=2),encoding='utf-8')
        record_verification('openroad_hier_rtlmp',version,cfg['image'],target)
        # Cross-backend iPL support must be admitted separately by the registry.
        record_verification('ieda_ipl_nangate',rt.IMAGE,rt.IMAGE,target)
    except Exception as exc:
        report.update(status='failed',error=str(exc));target.write_text(json.dumps(report,indent=2),encoding='utf-8');raise

if __name__=='__main__':main()
