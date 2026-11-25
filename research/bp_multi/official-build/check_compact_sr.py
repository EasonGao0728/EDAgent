"""Compare compact SR occupancy, A* pricing and overflow membership against the original."""
import json
from pathlib import Path
import shlex
import subprocess
import tarfile

root=Path('/srv/edagent/bp-multi-official-build-v1')
test_dir=root/'sr-tests'
test_dir.mkdir(exist_ok=True)
rel='src/operation/iRT/source/module/space_router/sr_data_manager/SRNode.hpp'
with tarfile.open(root.parent/'ieda-rootcause-20261112/official-build-source.tar.gz') as archive:
    matches=[m for m in archive if m.name.endswith('/'+rel)]
    assert len(matches)==1
    original=archive.extractfile(matches[0]).read().replace(b'SRNode',b'SRNodeReference')
    (test_dir/'SRNodeReference.hpp').write_bytes(original)
test=r'''
#include "ChangeType.hpp"
#include "SRNodeReference.hpp"
#include "SRNode.hpp"
#include <iostream>
#include <random>
using namespace irt;
int main() {
  Utility::initInst();
  std::mt19937 random(60817);
  std::map<Orientation,int> supply{{Orientation::kWest,4},{Orientation::kEast,2},{Orientation::kNorth,1}};
  std::map<int,std::set<Orientation>> ignore{{2,{Orientation::kAbove,Orientation::kWest}},{4,{Orientation::kNorth}}};
  for(double unit:{0.25,0.3}) {
    SRNode a; SRNodeReference b;
    a.set_orient_supply_map(supply); b.set_orient_supply_map(supply);
    a.set_ignore_net_orient_map(ignore); b.set_ignore_net_orient_map(ignore);
    a.set_boundary_wire_unit(unit); b.set_boundary_wire_unit(unit);
    a.set_internal_wire_unit(unit*1.5); b.set_internal_wire_unit(unit*1.5);
    a.set_internal_via_unit(1.75); b.set_internal_via_unit(1.75);
    for(int i=0;i<6000;++i) {
      if(i && i%500==0) {
        a.clearDemand(); b.get_orient_net_map().clear(); b.get_net_orient_map().clear();
      }
      int net=random()%23; std::set<Orientation> directions;
      for(int d=1;d<=6;++d) if(random()%3==0) directions.insert(static_cast<Orientation>(d));
      auto change=random()%2?ChangeType::kAdd:ChangeType::kDel;
      a.updateDemand(net,directions,change); b.updateDemand(net,directions,change);
      if(a.get_orient_net_map()!=b.get_orient_net_map() || a.get_net_orient_map()!=b.get_net_orient_map()
         || a.getOverflow()!=b.getOverflow() || a.getDemand()!=b.getDemand() ||
         a.getOverflowNetSet()!=b.getOverflowNetSet()) return 2;
      SRNode copy; copy.set_ignore_net_orient_map(ignore); copy.copyDemand(a);
      if(copy.get_net_orient_map()!=b.get_net_orient_map()) return 4;
      int probe=random()%30;
      for(auto d:{Direction::kHorizontal,Direction::kVertical,Direction::kProximal})
        if(a.getOverflowCost(probe,d,17)!=b.getOverflowCost(probe,d,17)) return 3;
    }
  }
  std::cout << "updates=12000 choices=36000 original_bytes=" << sizeof(SRNodeReference)
            << " compact_bytes=" << sizeof(SRNode) << "\n";
}
'''
(test_dir/'test.cpp').write_text(test)
record=next(r for r in json.loads((root/'build/compile_commands.json').read_bytes()) if r['file'].endswith('/SpaceRouter.cpp'))
args=shlex.split(record['command'])
args=args[:args.index('-o')]+['-I'+str(test_dir),'-I'+str((root/'source'/rel).parent),str(test_dir/'test.cpp'),
                              '-ffunction-sections','-Wl,--gc-sections',str(root/'build/lib/libirt_utility.a'),
                              str(root/'build/lib/libirt_logger.a'),'-o',str(test_dir/'test')]
subprocess.run(args,cwd=record['directory'],check=True)
subprocess.run([test_dir/'test'],check=True)
