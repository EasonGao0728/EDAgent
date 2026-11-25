from pathlib import Path
from difflib import unified_diff
root=Path('/srv/edagent/bp-multi-official-build-v1')
rel='src/operation/iRT/source/module/detailed_router/DetailedRouter.cpp'
text=(root/'source'/rel).read_text()
end=text.index('void DetailedRouter::buildFixedRect')
marker='  RTLOG.info(Loc::current(), "Completed", monitor.getStatsInfo());'
pos=text.rindex(marker,0,end)
assert text.index('DR chunk commit mismatch')<pos
addition=Path(__file__).with_name('native_terminal_probe.inc').read_text()+'\n'
candidate=text[:pos]+addition+text[pos:]
(root/'router-native-terminal-eco.patch').write_text(''.join(unified_diff(text.splitlines(True),candidate.splitlines(True),'a/'+rel,'b/'+rel)))
