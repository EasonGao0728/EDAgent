from pathlib import Path
import difflib
root=Path('/srv/edagent/bp-multi-official-build-v1')
rel='src/operation/iRT/interface/RTInterface.cpp'
p=(root/'source'/rel).read_text()
s=p.replace('#include <cstdlib>','#include <cstdlib>\n#include <array>\n#include <fstream>\n#include <cstdio>\n#include <type_traits>')
h='namespace irt {\nnamespace {'
assert s.count(h)==1
s=s.replace(h,h+'\n'+(root/'route_checkpoint.inc').read_text())
a=s.index('  PinAccessor::initInst();',s.index('void RTInterface::runRT()'))
b=s.index('  SpaceRouter::initInst();',a)
pa,la=s[a:b].split('  LayerAssigner::initInst();')
s=s[:a]+'''  const char* input = std::getenv("IEDA_RT_RESTORE_STATE");
  const char* level = std::getenv("IEDA_RT_RESTORE_LEVEL");
  const std::string resume=level?level:"";
  if(input && resume!="TG" && resume!="LA") throw std::runtime_error("invalid resume stage");
  if(input) transferRouteState(input,true,resume.c_str());
  else {
'''+pa+'''  }
  if(!input || resume=="TG") {
    transferRouteState(std::getenv("IEDA_RT_SAVE_TG"),false,"TG");
    LayerAssigner::initInst();'''+la+'''  }
  transferRouteState(std::getenv("IEDA_RT_SAVE_LA"),false,"LA");
  if (std::getenv("IEDA_RT_STOP_AFTER_LA")) {
    RTLOG.info(Loc::current(),"EDA_LA_MEASUREMENT_STOP");
    std::exit(25);
  }
'''+s[b:]
(root/'router-stage-state.patch').write_text(''.join(difflib.unified_diff(p.splitlines(True),s.splitlines(True),'a/'+rel,'b/'+rel)))
