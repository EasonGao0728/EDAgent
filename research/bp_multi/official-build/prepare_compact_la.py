"""Stage the layer-assigner memory change; preserve the V7 binary."""
from pathlib import Path
import difflib

root=Path('/srv/edagent/bp-multi-official-build-v1')
folder='src/operation/iRT/source/module/layer_assigner/'
header=folder+'la_data_manager/LANode.hpp'
cpp=folder+'LayerAssigner.cpp'
changes=[]
def add(rel,old,new):
    changes.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),'a/'+rel,'b/'+rel))

p=(root/'source'/header).read_text()
begin=p.index('  std::map<Orientation, LANode*>& get_neighbor_node_map()')
oldcalc=p[p.index('  double calcCost('):p.index('  double getDemand()')]
new=r'''  using Neighbors = std::map<Orientation, LANode*>;
  using Supply = std::map<Orientation, int32_t>;
  using Ignore = std::map<int32_t, std::set<Orientation>>;
  Neighbors& get_neighbor_node_map() {
    if (!_debug_neighbors) _debug_neighbors = std::make_shared<Neighbors>();
    return *_debug_neighbors;
  }
  const Supply& get_orient_supply_map() const { static const Supply empty; return _supply ? *_supply : empty; }
  const Ignore& get_ignore_net_orient_map() const { static const Ignore empty; return _ignore ? *_ignore : empty; }
  auto get_orient_net_map() const {
    std::map<Orientation,std::set<int32_t>> result;
    for (const auto& [net,mask] : _nets) for (int o=1;o<=6;++o)
      if (mask & (1u<<o)) result[static_cast<Orientation>(o)].insert(net);
    return result;
  }
  auto get_net_orient_map() const {
    Ignore result;
    for (const auto& [net,mask] : _nets) for (int o=1;o<=6;++o)
      if (mask & (1u<<o)) result[net].insert(static_cast<Orientation>(o));
    return result;
  }
  void set_boundary_wire_unit(double v) { _boundary_wire_unit=v; }
  void set_internal_wire_unit(double v) { _internal_wire_unit=v; }
  void set_internal_via_unit(double v) { _internal_via_unit=v; }
  // Both maps belong to GCell and stay const throughout LayerAssigner::assign.
  void set_orient_supply_map(Supply& v) { _supply=&v; }
  void set_ignore_net_orient_map(Ignore& v) { _ignore=&v; }
  void updateDemand(int32_t net, const std::set<Orientation>& directions, ChangeType change) {
    unsigned mask=0;
    for (auto o: directions) mask |= bit(o);
    auto it=std::lower_bound(_nets.begin(),_nets.end(),net,[](const auto& entry,int n){return entry.first<n;});
    if (it==_nets.end() || it->first!=net) {
      if (change==ChangeType::kAdd && mask) _nets.emplace(it,net,mask);
      return;
    }
    it->second = change==ChangeType::kAdd ? it->second|mask : it->second & ~mask;
    if (!it->second) _nets.erase(it);
  }
  bool validDemandUnit() {return _boundary_wire_unit>0 && _internal_wire_unit>0 && _internal_via_unit>0;}
  double getOverflowCost(int32_t net,Direction direction,double unit) {
    unsigned extra=0;
    if (direction==Direction::kHorizontal) extra=bit(Orientation::kWest)|bit(Orientation::kEast);
    else if (direction==Direction::kVertical) extra=bit(Orientation::kSouth)|bit(Orientation::kNorth);
    else RTLOG.error(Loc::current(),"Invalid layer-assignment direction");
    return unit*measure(net,extra,1);
  }
  double getOverflow() {return measure(-1,0,2);}
  double getDemand() {return measure(-1,0,0);}
''' + oldcalc + r'''
 private:
  static unsigned bit(Orientation o) {return 1u<<static_cast<unsigned>(o);}
  // Evaluate the hypothetical added wire without copying and updating two nested maps.
  double measure(int candidate,unsigned extra,int mode) {
    if (!validDemandUnit()) RTLOG.error(Loc::current(),"Invalid layer-assignment demand units");
    int counts[5]={}; int vias=0; bool found=false;
    constexpr unsigned planar=0x1e, vertical=0x60;
    auto account=[&](int net,unsigned mask){
      unsigned ignore=0;
      if (mode && _ignore) {
        const auto it=_ignore->find(net);
        if(it!=_ignore->end()) for(auto o:it->second) ignore |= bit(o);
      }
      for(int o=1;o<=4;++o) if((mask & ~ignore) & (1u<<o)) ++counts[o];
      if(!(mask&planar) && (mask&vertical) && !(ignore&vertical)) ++vias;
    };
    for(const auto& [net,mask]:_nets) {
      if(extra && net==candidate){account(net,mask|extra);found=true;}
      else account(net,mask);
    }
    if(extra && !found) account(candidate,extra);
    double boundary=0,internal=0,supply_sum=0;
    auto overflow=[&](double d,double s){return mode==1 ? calcCost(d,s) : std::max(0.0,d-s);};
    const auto& supplies=get_orient_supply_map();
    for(int o=1;o<=4;++o) {
      double demand=0;
      for(int k=0;k<counts[o];++k) {demand+=_boundary_wire_unit;internal+=_internal_wire_unit;}
      const auto it=supplies.find(static_cast<Orientation>(o));
      double supply=it==supplies.end()?0:it->second*_boundary_wire_unit;
      boundary+=mode ? overflow(demand,supply) : counts[o]*_boundary_wire_unit;
    }
    for(int k=0;k<vias;++k) internal+=_internal_via_unit;
    for(const auto& [o,s]:supplies) supply_sum+=s*_internal_wire_unit;
    return boundary+(mode ? overflow(internal,supply_sum) : internal);
  }
  double _boundary_wire_unit=-1, _internal_wire_unit=-1, _internal_via_unit=-1;
  std::shared_ptr<Neighbors> _debug_neighbors;
  const Supply* _supply=nullptr;
  const Ignore* _ignore=nullptr;
  std::vector<std::pair<int32_t,uint8_t>> _nets;
};
}  // namespace irt
'''
add(header,p,p[:begin].replace('#include "Direction.hpp"', '#include <memory>\n#include "Direction.hpp"')+new)
p=(root/'source'/cpp).read_text()
s=p.replace('  buildLANodeNeighbor(la_model);','  if (std::getenv("IEDA_RT_LA_DEBUG_GRAPH")) buildLANodeNeighbor(la_model);')
anchor='        layer_node_map[layer_idx][x][y].set_orient_supply_map(gcell_map[x][y].get_routing_orient_supply_map()[layer_idx]);'
assert s.count(anchor)==1
s=s.replace(anchor,'''        auto& supplies=gcell_map[x][y].get_routing_orient_supply_map();
        auto it=supplies.find(layer_idx);
        if (it!=supplies.end()) layer_node_map[layer_idx][x][y].set_orient_supply_map(it->second);''')
add(cpp,p,s)
(root/'router-compact-la.patch').write_text(''.join(changes))
