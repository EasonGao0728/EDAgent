"""Record native module boundaries and memory for the running process, without starting a tool."""
import json
from pathlib import Path
import re
import time

from verify_pa import RUNS, usage
from qualify_route_state import DR_SHA
from macro_agent.remote_native import identity

branch=RUNS/('full-lazy-'+DR_SHA[:12])
handle=json.loads((RUNS/'qualification-live.json').read_bytes())
assert handle['run']==branch.name and handle['start_ticks']
marker=re.compile(r'\b(\w+)\.cpp:\d+ Info (\w+)\] (Starting\.\.\.|Completed \(elapsed|Saved route checkpoint)')
modules={'access','analyze','generate','assign','route','report','runRT','transferRouteState','routeLAModel','buildLANodeMap','buildLANodeNeighbor','buildOrientSupply'}
with (branch/'result/rt/rt.log').open('r',errors='replace') as source,(branch/'module-observations.jsonl').open('x',buffering=1) as out:
    source.seek(0,2)
    while identity(handle['pid'])==handle['start_ticks']:
        records=[line.rstrip() for line in source.readlines() if (m:=marker.search(line)) and m[2] in modules]
        if records:
            rss,vm=usage(handle['pid'])
            out.write(json.dumps({'observed_at':time.time(),'rss_hwm':rss,'vm_peak':vm,'native_events':records})+'\n')
        time.sleep(2)
