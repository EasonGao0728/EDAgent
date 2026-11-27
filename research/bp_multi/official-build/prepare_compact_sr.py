"""Generate the downstream-only space-router memory and checkpoint patch."""
import difflib
from pathlib import Path

root = Path('/srv/edagent/bp-multi-official-build-v1')
source = root / 'source'
module = 'src/operation/iRT/source/module/'
header = module + 'space_router/sr_data_manager/SRNode.hpp'
router = module + 'space_router/SpaceRouter.cpp'
interface = 'src/operation/iRT/interface/RTInterface.cpp'
changes = []


def edit(name, text):
    old = (source/name).read_text()
    changes.extend(difflib.unified_diff(old.splitlines(True),text.splitlines(True),'a/'+name,'b/'+name))


def sub(text, old, new):
    assert text.count(old)==1, old
    return text.replace(old,new)


sr = (source/header).read_text()
la = (source/(module+'layer_assigner/la_data_manager/LANode.hpp')).read_text()
# Share the already qualified compact occupancy representation, preserving the
# SR-specific proximal cost, overflowing-net selection and A* state.
compact = la[la.index('  using Neighbors'):la.index('\n};')]
compact = compact.replace('LANode*','SRNode*').replace('Supply& v','const Supply& v').replace('Ignore& v','const Ignore& v')
compact = compact.replace('LayerAssigner::assign','SpaceRouter::route').replace('layer-assignment','space-routing')
compact = sub(compact,'    else RTLOG.error(Loc::current(),"Invalid space-routing direction");',
              '    else if (direction==Direction::kProximal) extra=bit(Orientation::kAbove)|bit(Orientation::kBelow);\n'
              '    else RTLOG.error(Loc::current(),"Invalid space-routing direction");')
compact = sub(compact,'  void set_boundary_wire_unit', '''  void clearDemand() { _nets.clear(); }
  void copyDemand(const SRNode& other) { _nets=other._nets; }
  SRNode* getNeighborNode(Orientation o) const {
    if (!_debug_neighbors) return nullptr;
    auto it=_debug_neighbors->find(o);
    return it==_debug_neighbors->end() ? nullptr : it->second;
  }
  void set_boundary_wire_unit''')
compact = compact.replace('  double measure(int candidate,unsigned extra,int mode)', '''  double measure(int candidate,unsigned extra,int mode,std::set<int>* overflow_nets=nullptr)''')
compact = sub(compact,'      boundary+=mode ?', '''      if (overflow_nets && demand>supply)
        for(const auto& [n,mask]:_nets) if(mask & (1u<<o)) overflow_nets->insert(n);
      boundary+=mode ?''')
compact = sub(compact,'    return boundary+(mode ?', '''    if(overflow_nets && internal>supply_sum)
      for(const auto& entry:_nets) overflow_nets->insert(entry.first);
    return boundary+(mode ?''')
compact = sub(compact,'  double getOverflow() {', '''  std::set<int32_t> getOverflowNetSet() {
    std::set<int32_t> nets;
    measure(-1,0,2,&nets);
    return nets;
  }
  double getOverflow() {''')
# A* prices a hypothetical move at each expansion. Maintain the filtered
# direction counts during occupancy changes so pricing only looks up one net.
compact = sub(compact, '  static unsigned bit(', '''  struct DemandCounts {
    int planar[5]{};
    int vias=0;
  };
  DemandCounts _counts;
  void countMask(DemandCounts& counts,int net,unsigned mask,int sign,bool filtered) const {
    unsigned ignore=0;
    if(filtered && _ignore) {
      auto it=_ignore->find(net);
      if(it!=_ignore->end()) for(auto o:it->second) ignore|=bit(o);
    }
    for(int o=1;o<=4;++o) if((mask & ~ignore) & (1u<<o)) counts.planar[o]+=sign;
    if(!(mask&0x1e) && (mask&0x60) && !(ignore&0x60)) counts.vias+=sign;
  }
  void recount() {
    _counts={};
    for(const auto& [net,mask]:_nets) countMask(_counts,net,mask,1,true);
  }
  static unsigned bit(''')
compact = sub(compact, 'void clearDemand() { _nets.clear(); }','void clearDemand() { _nets.clear(); _counts={}; }')
compact = sub(compact, 'void copyDemand(const SRNode& other) { _nets=other._nets; }',
              '''void copyDemand(const SRNode& other) {
    _nets=other._nets;
    if(_ignore==other._ignore) _counts=other._counts;
    else recount();
  }''')
compact = sub(compact, '_ignore=&v;', '_ignore=&v; recount();')
compact = sub(compact, 'if (change==ChangeType::kAdd && mask) _nets.emplace(it,net,mask);',
              'if (change==ChangeType::kAdd && mask) { _nets.emplace(it,net,mask); countMask(_counts,net,mask,1,true); }')
compact = sub(compact, '    it->second = change', '    countMask(_counts,net,it->second,-1,true);\n    it->second = change')
compact = sub(compact, '    if (!it->second)', '    countMask(_counts,net,it->second,1,true);\n    if (!it->second)')
start,end=compact.index('    int counts[5]'),compact.index('    double boundary=0')
compact=compact[:start]+'''    DemandCounts demand_counts=_counts;
    if(!mode) {
      demand_counts={};
      for(const auto& [net,mask]:_nets) countMask(demand_counts,net,mask,1,false);
    } else if(extra) {
      auto it=std::lower_bound(_nets.begin(),_nets.end(),candidate,
                               [](const auto& entry,int n){return entry.first<n;});
      unsigned mask=it!=_nets.end() && it->first==candidate ? it->second : 0;
      if((mask|extra)!=mask) {
        countMask(demand_counts,candidate,mask,-1,true);
        countMask(demand_counts,candidate,mask|extra,1,true);
      }
    }
    const auto& counts=demand_counts.planar;
    int vias=demand_counts.vias;
'''+compact[end:]
compact=sub(compact,'      for(int k=0;k<counts[o];++k) {demand+=_boundary_wire_unit;internal+=_internal_wire_unit;}',
'''      if(mode) {
        for(int k=0;k<counts[o];++k) {demand+=_boundary_wire_unit;internal+=_internal_wire_unit;}
      } else {
        demand=counts[o]*_boundary_wire_unit;
        internal+=counts[o]*_internal_wire_unit;
      }''')
# Keep A* data and comparator byte-for-byte from the pinned source.
astar=sr[sr.index('#if 1  // astar\n  // single path'):sr.index('\n private:')]
compact=sub(compact,'\n private:', '\n'+astar+'\n private:')
first=sr.index('  std::map<Orientation, SRNode*>& get_neighbor_node_map()')
last=sr.index('#if 1  // astar\n  // single path',sr.index('\n private:'))
sr=sr[:first]+compact+'\n'+sr[last:]
sr=sub(sr,'#include "Direction.hpp"','#include <memory>\n#include "Direction.hpp"')
edit(header,sr)

c=(source/router).read_text()
c=sub(c,'        layer_node_map[layer_idx][x][y].set_orient_supply_map(gcell_map[x][y].get_routing_orient_supply_map()[layer_idx]);',
'''        const auto& supplies=gcell_map[x][y].get_routing_orient_supply_map();
        const auto it=supplies.find(layer_idx);
        if (it!=supplies.end()) layer_node_map[layer_idx][x][y].set_orient_supply_map(it->second);''')
c=sub(c,'        layer_node_map[layer_idx][x][y].get_orient_net_map().clear();\n        layer_node_map[layer_idx][x][y].get_net_orient_map().clear();',
      '        layer_node_map[layer_idx][x][y].clearDemand();')
c=sub(c,'        sr_node.set_orient_net_map(top_sr_node_map[sr_node.get_x()][sr_node.get_y()].get_orient_net_map());\n        sr_node.set_net_orient_map(top_sr_node_map[sr_node.get_x()][sr_node.get_y()].get_net_orient_map());',
      '        sr_node.copyDemand(top_sr_node_map[sr_node.get_x()][sr_node.get_y()]);')
edit(router,c)

api=(source/interface).read_text()
api=sub(api,'  transferRouteState(std::getenv("IEDA_RT_SAVE_LA"),false,"LA");',
        '  if(resume!="SR" && resume!="TA") transferRouteState(std::getenv("IEDA_RT_SAVE_LA"),false,"LA");')
api=sub(api,'resume!="TG" && resume!="LA"', 'resume!="TG" && resume!="LA" && resume!="SR" && resume!="TA"')
api=sub(api,'  SpaceRouter::initInst();\n  RTSR.route();\n  SpaceRouter::destroyInst();','''  if(resume!="SR" && resume!="TA") {
    SpaceRouter::initInst();
    RTSR.route();
    SpaceRouter::destroyInst();
    transferRouteState(std::getenv("IEDA_RT_SAVE_SR"),false,"SR");
  }''')
api=sub(api,'  TrackAssigner::initInst();\n  RTTA.assign();\n  TrackAssigner::destroyInst();','''  if(resume!="TA") {
    TrackAssigner::initInst();
    RTTA.assign();
    TrackAssigner::destroyInst();
    transferRouteState(std::getenv("IEDA_RT_SAVE_TA"),false,"TA");
  }''')
edit(interface,api)
(root/'router-compact-sr.patch').write_text(''.join(changes))
