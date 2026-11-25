"""Generate the SR-to-TA adapter for a verified finite-track boundary port table."""
from pathlib import Path
import difflib

root=Path('/srv/edagent/bp-multi-official-build-v1')
prefix='src/operation/iRT/'
patch=[]
def edit(path,old,new):
    patch.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),'a/'+path,'b/'+path))

rel=prefix+'interface/RTInterface.cpp'
old=(root/'source'/rel).read_text()
fn=r'''
// Project global guides from pad-only edge GCells to the physical track domain.
// Keep a real piece of preferred-layer metal back to every original IO terminal.
void connectBoundaryGuides() {
  const char* path=std::getenv("IEDA_RT_BOUNDARY_LEADS");
  if(!path)return;
  std::ifstream file(path);
  int xmin,xmax,ymin,ymax;
  if(!(file>>xmin>>xmax>>ymin>>ymax) || xmin>xmax || ymin>ymax)
    throw std::runtime_error("invalid boundary track domain");
  auto& db=RTDM.getDatabase();
  auto& nets=db.get_net_list();
  std::map<std::string,int> ids;
  for(auto& n:nets)ids.emplace(n.get_net_name(),n.get_net_idx());
  auto guides=RTDM.getNetGlobalResultMap(db.get_die());
  auto detailed=RTDM.getNetDetailedResultMap(db.get_die());
  std::set<int> done;
  int leads=0,changed=0,collapsed=0;
  auto projection=[&](LayerCoord p){
    p.set_x(std::clamp(p.get_x(),xmin,xmax));p.set_y(std::clamp(p.get_y(),ymin,ymax));return p;
  };
  std::string net,terminal;int l,x,y,a,b;
  while(file>>net>>terminal>>l>>x>>y>>a>>b) {
    const int id=ids.at(net);
    auto& pins=nets.at(id).get_pin_list();
    auto pin=std::find_if(pins.begin(),pins.end(),[&](auto& p){return p.get_pin_name()==terminal;});
    LayerCoord endpoint(x,y,l),anchor(a,b,l);
    if(pin==pins.end() || !(pin->get_access_point().getRealLayerCoord()==endpoint) || endpoint==anchor ||
       ((x!=a)==(y!=b)))throw std::runtime_error("boundary endpoint does not match PA: "+net);
    auto& layer=db.get_routing_layer_list().at(l);
    if((layer.get_prefer_direction()==Direction::kHorizontal)!=(y==b) ||
       RTUTIL.getScaleList(a,a,layer.getXTrackGridList()).empty() ||
       RTUTIL.getScaleList(b,b,layer.getYTrackGridList()).empty())
      throw std::runtime_error("boundary lead not on preferred native track: "+net);
    auto gp=projection(pin->get_access_point().getGridLayerCoord());
    auto& axes=db.get_gcell_axis();
    if(!RTUTIL.isInside(RTUTIL.getRealRectByGCell(gp,axes),anchor))
      throw std::runtime_error("boundary anchor does not match projected GCell: "+net);
    if(done.insert(id).second) {
      auto it=guides.find(id);
      if(it==guides.end())throw std::runtime_error("missing original boundary guide: "+net);
      using Key=std::array<int,6>;
      std::set<Key> segments;
      bool touched=false;
      for(auto s:it->second) {
        auto p=projection(s->get_first()),q=projection(s->get_second());
        if(!(p==s->get_first()) || !(q==s->get_second())){touched=true;++changed;}
        if(p==q){++collapsed;continue;}
        if(CmpLayerCoordByXASC()(q,p))std::swap(p,q);
        segments.insert({p.get_x(),p.get_y(),p.get_layer_idx(),q.get_x(),q.get_y(),q.get_layer_idx()});
      }
      if(!touched)throw std::runtime_error("no affected guide for boundary IO: "+net);
      for(auto s:it->second)RTDM.updateNetGlobalResultToGCellMap(ChangeType::kDel,id,s);
      for(const auto& c:segments)RTDM.updateNetGlobalResultToGCellMap(ChangeType::kAdd,id,
          new Segment<LayerCoord>(LayerCoord(c[0],c[1],c[2]),LayerCoord(c[3],c[4],c[5])));
    }
    auto& ds=detailed[id];
    bool present=std::any_of(ds.begin(),ds.end(),[&](auto s){
      return (s->get_first()==endpoint && s->get_second()==anchor) || (s->get_first()==anchor && s->get_second()==endpoint);
    });
    if(!present)RTDM.updateNetDetailedResultToGCellMap(ChangeType::kAdd,id,new Segment<LayerCoord>(endpoint,anchor));
    ++leads;
  }
  if(!file.eof() || !leads)throw std::runtime_error("invalid boundary lead table");
  RTLOG.info(Loc::current(),"EDA_BOUNDARY_LEADS ports=",leads," nets=",done.size()," guide_changes=",changed," collapsed=",collapsed);
}
'''
marker='class RouteStateIO {'
assert old.count(marker)==1 and old.count('  if(resume!="TA") {')==1
new=old.replace(marker,fn+'\n'+marker).replace('  if(resume!="TA") {','  if(resume!="TA") {\n    connectBoundaryGuides();')
edit(rel,old,new)
rel=prefix+'source/module/detailed_router/DetailedRouter.cpp'
old=(root/'source'/rel).read_text()
marker='    return result;\n  }();\n  return leads;'
assert old.count(marker)==1
extra=r'''    if(const char* edge=std::getenv("IEDA_RT_BOUNDARY_LEADS")){
      std::ifstream ports(edge);
      int xmin,xmax,ymin,ymax,l;
      if(!(ports>>xmin>>xmax>>ymin>>ymax))throw std::runtime_error("invalid boundary lead header");
      while(ports>>net>>terminal>>l>>x>>y>>a>>b){
        int ni=net_ids.at(net);
        auto& pins=nets.at(ni).get_pin_list();
        auto pin=std::find_if(pins.begin(),pins.end(),[&](auto& p){return p.get_pin_name()==terminal;});
        LayerCoord p(x,y,l),q(a,b,l);
        if(pin==pins.end() || !(pin->get_access_point().getRealLayerCoord()==p) || (x==a)==(y==b))
          throw std::runtime_error("boundary lead changed at DR: "+net);
        auto& segs=segments.at(ni);
        if(!std::any_of(segs.begin(),segs.end(),[&](auto s){return
          (s->get_first()==p && s->get_second()==q) || (s->get_second()==p && s->get_first()==q);}))
          throw std::runtime_error("missing physical boundary connection at DR: "+net);
        result[ni].push_back({pin->get_pin_idx(),l,x,y,a,b});
      }
      if(!ports.eof())throw std::runtime_error("malformed DR boundary lead table");
    }
'''
edit(rel,old,old.replace(marker,extra+marker))
(root/'router-boundary-guides.patch').write_text(''.join(patch))
