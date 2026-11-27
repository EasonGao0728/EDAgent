"""Generate a DR-only storage change for the frozen V13 source tree."""
from pathlib import Path
import difflib
import re
root=Path('/srv/edagent/bp-multi-official-build-v1')
module='src/operation/iRT/source/module/detailed_router/'
patch=[]
def add(name,mapper):
    file=module+name
    original=(root/'source'/file).read_text()
    modified=mapper(original)
    assert original!=modified
    patch.extend(difflib.unified_diff(original.splitlines(True),modified.splitlines(True),'a/'+file,'b/'+file))
def header(s):
    s=s.replace('#include "Direction.hpp"', '#include <boost/container/flat_map.hpp>\n#include <boost/container/flat_set.hpp>\n#include "Direction.hpp"')
    s=s.replace('std::map<Orientation, std::set<int32_t>>','boost::container::flat_map<Orientation, boost::container::flat_set<int32_t>>')
    s=s.replace('std::map<Orientation, DRNode*>','boost::container::flat_map<Orientation, DRNode*>').replace('std::map<Orientation, int32_t>','boost::container::flat_map<Orientation, int32_t>')
    s=s.replace('std::set<int32_t>& net_set','const auto& net_set')
    s=re.sub(r'RTUTIL\.exist\((_\w+|net_set), (\w+)\)',r'(\1.find(\2) != \1.end())',s)
    return s
def implementation(s):
    s=s.replace('std::map<Orientation, DRNode*>& neighbor_node_map','auto& neighbor_node_map')
    s=re.sub(r'RTUTIL\.exist\(([^,\n]+get_(?:neighbor_node|orient_fixed_rect)_map\(\)), ([\w:]+)\)',r'(\1.find(\2) != \1.end())',s)
    # Only geometry and scheduling live in the permanent box map. Results have
    # already been uploaded before the temporary box goes out of scope.
    marker='      DRBox& dr_box = dr_box_map[dr_box_id.get_x()][dr_box_id.get_y()];\n      buildFixedRect'
    assert s.count(marker)==1
    s=s.replace(marker,'''      auto& spec=dr_box_map[dr_box_id.get_x()][dr_box_id.get_y()];
      DRBox dr_box;
      dr_box.set_box_rect(spec.get_box_rect());
      dr_box.set_dr_box_id(spec.get_dr_box_id());
      dr_box.set_dr_iter_param(spec.get_dr_iter_param());
      dr_box.set_initial_routing(spec.get_initial_routing());
      buildFixedRect''')
    marker='  size_t routed_box_num = 0;'
    s=s.replace(marker,marker+'\n  std::atomic<size_t> completed{0};')
    marker='      freeDRBox(dr_box);'
    assert s.count(marker)==1
    s=s.replace(marker,marker+'''
      const auto n=++completed;
      if(n%64==0)RTLOG.info(Loc::current(),"DR boxes committed ",n,"/",total_box_num);''')
    a=s.index('    std::set<Direction> direction_set;',s.index('double DetailedRouter::getKnownBendCost'))
    b=s.index('      bend_cost += bend_unit;',a)
    s=s[:a]+'''    unsigned mask=0;
    auto include=[&](Direction d) { mask |= 1u << static_cast<unsigned>(d); };
    for (auto d : start_node->get_direction_set()) include(d);
    if (start_node->get_parent_node()) include(RTUTIL.getDirection(*start_node->get_parent_node(), *start_node));
    for (auto d : end_node->get_direction_set()) include(d);
    include(RTUTIL.getDirection(*start_node,*end_node));
    if (__builtin_popcount(mask)==2) {
'''+s[b:]
    return s
add('dr_data_manager/DRNode.hpp',header)
add('DetailedRouter.cpp',implementation)
(root/'router-dr-compact-box.patch').write_text(''.join(patch))
