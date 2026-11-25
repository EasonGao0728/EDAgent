"""Read a single existing run; preserve sparse measurements without submitting iEDA."""
import json
import os
from pathlib import Path
import re
import sys
import time

from verify_pa import RUNS, usage
from macro_agent.remote_native import identity

def observe():
    live=json.loads((RUNS/'qualification-live.json').read_bytes())
    path=(RUNS/live['run']).resolve(strict=True)
    assert path.is_relative_to(RUNS.resolve()) and path.relative_to(RUNS.resolve()).as_posix()==sys.argv[1]
    assert path.parent==RUNS.resolve() or path.relative_to(RUNS.resolve()).as_posix() in ('full-lazy-a299a1d992ac/recovery-v12','full-lazy-a299a1d992ac/recovery-v13','full-lazy-a299a1d992ac/recovery-v14')
    worker=live['pid']
    pathlog=path/'result/rt/rt.log'
    journal=path/'observations.jsonl'
    with journal.open('a',buffering=1) as out:
        while live['start_ticks'] and identity(worker)==live['start_ticks']:
            with pathlog.open('rb') as f:
                f.seek(max(0,pathlog.stat().st_size-65536))
                lines=f.read(65536).decode(errors='replace').splitlines()
            event=next((line for line in reversed(lines) if re.search(r'(?:Routed|Assigned|DR boxes committed) \d+/|Begin iteration|End Iteration|Error|Fatal',line)),'')
            rss,vm=usage(worker)
            out.write(json.dumps(dict(time=time.time(),rss_hwm=rss,vm_peak=vm,event=event))+'\n')
            time.sleep(30)
        print(path, 'worker exited',flush=True)

if __name__=='__main__':observe()
