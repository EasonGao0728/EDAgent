"""Record real terminal coordinates when native detailed routing exhausts its search."""
from pathlib import Path
from difflib import unified_diff

root=Path('/srv/edagent/bp-multi-official-build-v1')
rel='src/operation/iRT/source/module/detailed_router/DetailedRouter.cpp'
source=(root/'source'/rel).read_text()
marker='    routeSinglePath(dr_box);\n    updatePathResult(dr_box);'
assert source.count(marker)==1
candidate=source.replace(marker,'''    routeSinglePath(dr_box);
    if (!dr_box.get_path_head_node() || dr_box.get_end_node_list_idx()<0) {
      auto& n=RTDM.getDatabase().get_net_list().at(dr_task->get_net_idx());
      const auto& r=dr_box.get_box_rect().get_real_rect();
      RTLOG.info(Loc::current(),"EDA_DR_UNREACHABLE net=",n.get_net_name()," box=",r.get_ll_x(),",",r.get_ll_y(),",",r.get_ur_x(),",",r.get_ur_y());
      auto report=[&](const char* which,auto& groups){
        for(auto& group:groups)for(auto* node:group){
          RTLOG.info(Loc::current(),"EDA_DR_TERMINAL ",which," ",node->get_x()," ",node->get_y()," ",node->get_layer_idx()," neighbors=",node->get_neighbor_node_map().size()," visited=",node->isClose());
        }
      };
      report("start",dr_box.get_start_node_list_list());
      report("end",dr_box.get_end_node_list_list());
      RTLOG.error(Loc::current(),"Detailed routing exhausted its graph before all terminal groups connected");
    }
    updatePathResult(dr_box);''')
(root/'router-dr-path-diagnostic.patch').write_text(''.join(unified_diff(source.splitlines(True),
    candidate.splitlines(True),'a/'+rel,'b/'+rel)))
