from difflib import unified_diff
from pathlib import Path

root=Path('/srv/edagent/bp-multi-official-build-v1')
rel='src/operation/iRT/source/module/detailed_router/DetailedRouter.cpp'
original=(root/'source'/rel).read_text()
s=original
def add(old,new):
    global s
    assert s.count(old)==1,old
    s=s.replace(old,new)

add('#include <cstdlib>', '#include <cstdlib>\n#include <fstream>')
add('namespace {\nbool nativeTrackGraph()', 'namespace {\n'+(root/'dr_access_leads.inc').read_text()+'\nbool nativeTrackGraph()')
add('void DetailedRouter::route()\n{','void DetailedRouter::route()\n{\n  drAccessLeads(); // Validate native PA geometry before the first box splits its wires.')
add('      if (least_one_coord_in_box) {','''      const auto& leads=drAccessLeads();
      auto lead=leads.find(net_idx);
      bool fixed_access=lead!=leads.end() && std::any_of(lead->second.begin(),lead->second.end(),
          [&](const auto& l){return l.owns(*segment);});
      if (least_one_coord_in_box && !fixed_access) {''')
marker='  std::map<int32_t, std::vector<DRGroup>> net_group_list_map;'
add(marker,marker+'''
  const auto& leads=drAccessLeads();
  for(const auto& [net,items]:leads) for(const auto& l:items) {
    LayerCoord anchor(l.a,l.b,l.layer);
    if(RTUTIL.isInside(box_real_rect,anchor)) {
      DRGroup group;
      group.get_coord_direction_map()[anchor].insert(routing_layer_list.at(l.layer).get_prefer_direction());
      net_group_list_map[net].push_back(group);
    }
  }''')
marker='        pin_group_map[access_point->get_pin_idx()]'
add(marker,'''        auto lead=leads.find(net_idx);
        if(lead!=leads.end() && std::any_of(lead->second.begin(),lead->second.end(),
            [&](const auto& l){return l.pin==access_point->get_pin_idx();})) continue;
'''+marker)
(root/'router-dr-access-leads.patch').write_text(''.join(unified_diff(original.splitlines(True),s.splitlines(True),'a/'+rel,'b/'+rel)))
