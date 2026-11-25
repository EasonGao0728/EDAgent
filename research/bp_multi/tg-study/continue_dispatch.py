"""Complete readback, downstream stages and packaging for one already scheduled route."""
from pathlib import Path
import fcntl
import json
import subprocess
import sys
import time
from finish_bp_multi import BRANCH, CASE_ROOT
from verify_pa import RUNS, save
from workbench_route import status


def follow():
    root=RUNS/'dispatch-v11'
    state=root/'continuation.json'
    audit=CASE_ROOT/'qualification-evidence/catalog-v1/bp_multi_official/audit_routed_v7.py'
    with (root/'continuation.lock').open('a') as l:
        try:fcntl.flock(l,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        if state.exists() and json.loads(state.read_bytes()).get('phase') in ('delivery','failed'):
            return
        phase='waiting_for_routing'
        save(state,{'phase':phase})
        try:
            while not (BRANCH/'receipt.json').exists():
                if status(root)['phase'] in ('failed','interrupted'):raise RuntimeError('Route worker ended without a successful receipt')
                time.sleep(15)
            r=json.loads((BRANCH/'receipt.json').read_bytes())
            if r['returncode'] or not r['stage_marker']:raise RuntimeError('Router exit '+str(r['returncode'])+'; original receipt retained')
            for phase,script,args in [
                    ('route_readback',audit,['--version','11']),
                    ('backend',Path(__file__).with_name('finish_bp_multi.py'),['continue'])]:
                save(state,{'phase':phase})
                subprocess.run([sys.executable,'-u',str(script),*args],check=True)
            assert (BRANCH/'backend/delivery/manifest.json').is_file()
            save(state,{'phase':'delivery'})
        except Exception as e:
            save(state,{'phase':'failed','failed_at':phase,'error':str(e)})
            raise


if __name__=='__main__':follow()
