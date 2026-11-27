"""Compare actual V7 and V8 LANode computations on the build host."""
import json
from pathlib import Path
import shlex
import subprocess
import tarfile

root=Path('/srv/edagent/bp-multi-official-build-v1')
tmp=root/'la-tests'
tmp.mkdir(exist_ok=True)
rel='src/operation/iRT/source/module/layer_assigner/la_data_manager/LANode.hpp'
with tarfile.open(root.parent/'ieda-rootcause-20261112/official-build-source.tar.gz') as ar:
    members=[m for m in ar if m.name.endswith('/'+rel)]
    assert len(members)==1
    (tmp/'LANodeReference.hpp').write_bytes(ar.extractfile(members[0]).read().replace(b'LANode',b'LANodeReference'))
test=r'''
#include "ChangeType.hpp"
#include "LANodeReference.hpp"
#include "LANode.hpp"
#include <cassert>
#include <iostream>
#include <random>
using namespace irt;
int main() {
  Utility::initInst();
  LANode a; LANodeReference b; std::mt19937 rng(62153);
  std::map<Orientation,int> supply{{Orientation::kWest,4},{Orientation::kEast,2},{Orientation::kNorth,1}};
  std::map<int,std::set<Orientation>> ignore{{2,{Orientation::kAbove,Orientation::kWest}},{4,{Orientation::kNorth}}};
  a.set_orient_supply_map(supply); b.set_orient_supply_map(supply);
  a.set_ignore_net_orient_map(ignore); b.set_ignore_net_orient_map(ignore);
  a.set_boundary_wire_unit(0.25); b.set_boundary_wire_unit(0.25);
  a.set_internal_wire_unit(0.5); b.set_internal_wire_unit(0.5);
  a.set_internal_via_unit(1.75); b.set_internal_via_unit(1.75);
  for(int i=0;i<12000;++i){
    int net=rng()%23; std::set<Orientation> directions;
    for(int j=1;j<=6;++j) if(rng()%3==0) directions.insert(static_cast<Orientation>(j));
    auto change=rng()%2?ChangeType::kAdd:ChangeType::kDel;
    a.updateDemand(net,directions,change); b.updateDemand(net,directions,change);
    if(a.get_orient_net_map()!=b.get_orient_net_map() || a.get_net_orient_map()!=b.get_net_orient_map()
       || a.getOverflow()!=b.getOverflow() || a.getDemand()!=b.getDemand()) return 2;
    int probe=rng()%30;
    for(auto d:{Direction::kHorizontal,Direction::kVertical})
      if(a.getOverflowCost(probe,d,17)!=b.getOverflowCost(probe,d,17)) return 3;
  }
  std::cout << "updates=12000 choices=24000 sizeof_V7=" << sizeof(b) << " sizeof_V8=" << sizeof(a) << "\n";
}
'''
(tmp/'test.cpp').write_text(test)
record=next(r for r in json.loads((root/'build/compile_commands.json').read_bytes()) if r['file'].endswith('/LayerAssigner.cpp'))
cmd=shlex.split(record['command'])
# Use original include paths and definitions; only valid-input paths are exercised.
cmd=cmd[:cmd.index('-o')]+['-I'+str(tmp),'-I'+str((root/'source'/rel).parent),str(tmp/'test.cpp'),'-ffunction-sections',
                           '-Wl,--gc-sections',str(root/'build/lib/libirt_utility.a'),str(root/'build/lib/libirt_logger.a'),'-o',str(tmp/'test')]
subprocess.run(cmd,cwd=record['directory'],check=True)
print(subprocess.check_output([tmp/'test'],text=True))
