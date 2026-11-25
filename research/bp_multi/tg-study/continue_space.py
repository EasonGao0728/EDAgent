"""Run a qualified repair from the frozen LA state and hand off only verified output."""
import os
from pathlib import Path
import subprocess
import sys
from resume_space import FAMILY, RUNS, save, attempt_name

if __name__=='__main__':
    directory=Path(__file__).resolve().parent
    auditor=directory.parent/'bp_multi_official/audit_routed_v7.py'
    revision=int(sys.argv[1]) if sys.argv[1:] else 12
    assert revision in (12,13,14,16,17)
    state=RUNS/'dispatch-v11'/attempt_name(revision).replace('recovery-','repair-',1)/'continuation.json'
    env=dict(os.environ,PYTHONPATH=os.pathsep.join(map(str,(directory,auditor.parent))))
    try:
        steps=(
            ('routing','resume_space.py',[{12:'whole',13:'boundary',14:'dr',16:'batch',17:'stable'}[revision]]),
            ('route_readback',auditor,['--version',str(revision)]),
            ('backend','finish_bp_multi.py',['continue','--revision',str(revision)]))
        if sys.argv[2:]==['--backend-only']:
            import json
            previous=json.loads(state.read_bytes())
            validation=json.loads((FAMILY/attempt_name(revision)/'route-validation.json').read_bytes())
            assert previous.get('failed_at')=='backend' and validation['passed']
            steps=steps[-1:]
        elif sys.argv[2:]:raise ValueError('Unknown continuation mode')
        for phase,script,args in steps:
            save(state,{'phase':phase})
            subprocess.run([sys.executable,'-u',str(script),*args],cwd=directory,env=env,check=True)
        assert (FAMILY/'backend/delivery/manifest.json').exists()
        save(state,{'phase':'delivery'})
    except Exception as exc:
        save(state,{'phase':'failed','failed_at':phase,'error':str(exc)})
        raise
