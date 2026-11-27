// Included inside irt's anonymous namespace. Files are local, schema- and input-bound.
class RouteStateIO {
 public:
  RouteStateIO(const std::string& path,bool read): reading(read) {
    stream.exceptions(std::ios::badbit|std::ios::failbit);
    stream.open(path,std::ios::binary|(read?std::ios::in:(std::ios::out|std::ios::trunc)));
  }
  template<class T> T scalar(T v={}) {
    static_assert(std::is_arithmetic_v<T>);
    if(reading) stream.read(reinterpret_cast<char*>(&v),sizeof(v));
    else stream.write(reinterpret_cast<const char*>(&v),sizeof(v));
    return v;
  }
  int count(size_t value,int limit) {
    if(value>size_t(limit)) throw std::runtime_error("checkpoint collection too large");
    int n=scalar<int32_t>(value);
    if(n<0||n>limit) throw std::runtime_error("invalid checkpoint count");
    return n;
  }
  void match(int expected) {
    if(scalar<int32_t>(expected)!=expected) throw std::runtime_error("checkpoint schema or dimensions differ");
  }
  void name(const std::string& expected) {
    match(expected.size());
    if(reading) {std::string n(expected.size(),' ');stream.read(n.data(),n.size());if(n!=expected)throw std::runtime_error("checkpoint identity mismatch");}
    else stream.write(expected.data(),expected.size());
  }
  PlanarRect rect(const PlanarRect& r) {
    int a=scalar(r.get_ll_x()),b=scalar(r.get_ll_y()),c=scalar(r.get_ur_x()),d=scalar(r.get_ur_y());
    return PlanarRect(a,b,c,d);
  }
  EXTLayerRect ext(EXTLayerRect v) {
    v.set_real_rect(rect(v.get_real_rect()));v.set_grid_rect(rect(v.get_grid_rect()));v.set_layer_idx(scalar(v.get_layer_idx()));return v;
  }
  void finish() {
    match(0x5441494c);
    if(reading && stream.rdbuf()->sgetc()!=std::char_traits<char>::eof()) throw std::runtime_error("trailing route checkpoint data");
    stream.close();
  }
  bool reading;
 private:
  std::fstream stream;
};

void transferRouteState(const char* path,bool restore,const char* stage)
{
  if (!path || !*path) return;
  const char* binding=std::getenv("IEDA_RT_STATE_BINDING");
  if(!binding || std::string(binding).size()!=64) throw std::runtime_error("missing frozen routing-input binding");
  std::string file(path),temp=file+".partial";
  RouteStateIO io(restore?file:temp,restore);
  io.name("ieda-route-state-v1");io.name(stage);io.name(binding);
  auto& db=RTDM.getDatabase();auto& die=db.get_die();auto& gc=db.get_gcell_map();
  auto& nets=db.get_net_list();io.match(nets.size());io.match(gc.get_x_size());io.match(gc.get_y_size());
  auto change=ChangeType::kAdd;
  for(auto& n:nets) {
    io.match(n.get_net_idx());io.name(n.get_net_name());
    auto& box=n.get_bounding_box();
    auto r=io.rect(box.get_real_rect()), g=io.rect(box.get_grid_rect());
    if(restore){box.set_real_rect(r);box.set_grid_rect(g);}
    io.match(n.get_pin_list().size());
    for(auto& pin:n.get_pin_list()){
      io.match(pin.get_pin_idx());io.name(pin.get_pin_name());
      auto& ap=pin.get_access_point();auto real=ap.getRealLayerCoord();auto grid=ap.get_grid_coord();
      int x=io.scalar(real.get_x()),y=io.scalar(real.get_y()),l=io.scalar(real.get_layer_idx());
      int gx=io.scalar(grid.get_x()),gy=io.scalar(grid.get_y());
      if(restore){
        AccessPoint p(pin.get_pin_idx(),LayerCoord(x,y,l));p.set_grid_coord(PlanarCoord(gx,gy));
        pin.set_access_point(p);RTDM.updateNetAccessPointToGCellMap(change,n.get_net_idx(),&pin.get_access_point());
      }
    }
  }
  auto segments=[&](bool global) {
    using Coords=std::array<int32_t,6>;
    auto groups=global?RTDM.getNetGlobalResultMap(die):RTDM.getNetDetailedResultMap(die);
    if(restore && !groups.empty())throw std::runtime_error("route-state restore requires fresh routing database");
    for(auto& n:nets){
      const int ni=n.get_net_idx();std::vector<Coords> records;
      if(!restore && groups.count(ni))for(auto s:groups.at(ni)){
        auto a=s->get_first(),b=s->get_second();
        records.push_back({a.get_x(),a.get_y(),a.get_layer_idx(),b.get_x(),b.get_y(),b.get_layer_idx()});
      }
      std::sort(records.begin(),records.end());
      int count=io.count(records.size(),10000000);
      for(int i=0;i<count;++i){
        Coords c=restore?Coords{}:records[i];for(auto& v:c)v=io.scalar(v);
        if(restore){
          auto s=new Segment<LayerCoord>(LayerCoord(c[0],c[1],c[2]),LayerCoord(c[3],c[4],c[5]));
          if(global)RTDM.updateNetGlobalResultToGCellMap(change,ni,s);
          else RTDM.updateNetDetailedResultToGCellMap(change,ni,s);
        }
      }
    }
  };
  segments(false);segments(true);
  auto patches=RTDM.getNetDetailedPatchMap(die);
  for(auto& n:nets){
    int ni=n.get_net_idx();std::vector<EXTLayerRect> items;
    if(!restore && patches.count(ni))for(auto p:patches.at(ni))items.push_back(*p);
    auto key=[](EXTLayerRect& a){auto r=a.get_real_rect(),g=a.get_grid_rect();return std::array<int,9>{
      a.get_layer_idx(),r.get_ll_x(),r.get_ll_y(),r.get_ur_x(),r.get_ur_y(),g.get_ll_x(),g.get_ll_y(),g.get_ur_x(),g.get_ur_y()};};
    std::sort(items.begin(),items.end(),[&](auto a,auto b){return key(a)<key(b);});
    int ct=io.count(items.size(),10000000);
    for(int i=0;i<ct;++i){auto p=io.ext(restore?EXTLayerRect():items[i]);if(restore)RTDM.updateNetDetailedPatchToGCellMap(change,ni,new EXTLayerRect(p));}
  }
  auto violations=RTDM.getViolationSet(die);auto vi=violations.begin();int nv=io.count(violations.size(),10000000);
  for(int i=0;i<nv;++i){
    Violation v;if(!restore)v=**vi++;
    v.set_violation_type(static_cast<ViolationType>(io.scalar<int>(static_cast<int>(v.get_violation_type()))));
    v.set_violation_shape(io.ext(v.get_violation_shape()));v.set_is_routing(io.scalar<uint8_t>(v.get_is_routing()));
    v.set_required_size(io.scalar(v.get_required_size()));
    auto& ids=v.get_violation_net_set();auto it=ids.begin();int count=io.count(ids.size(),nets.size()+1);
    for(int j=0;j<count;++j){int id=io.scalar(restore?0:*it++);if(restore)ids.insert(id);}
    if(restore)RTDM.updateViolationToGCellMap(change,new Violation(v));
  }
  for(int x=0;x<gc.get_x_size();++x)for(int y=0;y<gc.get_y_size();++y){
    auto& cell=gc[x][y];
    cell.set_boundary_wire_unit(io.scalar(cell.get_boundary_wire_unit()));
    cell.set_internal_wire_unit(io.scalar(cell.get_internal_wire_unit()));
    cell.set_internal_via_unit(io.scalar(cell.get_internal_via_unit()));
    auto& supply=cell.get_routing_orient_supply_map();
    auto si=supply.begin();int ns=io.count(supply.size(),db.get_routing_layer_list().size());
    for(int i=0;i<ns;++i){
      int l=io.scalar(restore?0:si->first);auto& m=supply[l];auto it=m.begin();int ct=io.count(m.size(),8);
      for(int j=0;j<ct;++j){int o=io.scalar(restore?0:int(it->first));int v=io.scalar(restore?0:it++->second);if(restore)m[static_cast<Orientation>(o)]=v;}
      if(!restore)++si;
    }
    auto& ignore=cell.get_routing_ignore_net_orient_map();auto ii=ignore.begin();int ni=io.count(ignore.size(),db.get_routing_layer_list().size());
    for(int i=0;i<ni;++i){
      int l=io.scalar(restore?0:ii->first);auto& local=ignore[l];auto it=local.begin();int nn=io.count(local.size(),nets.size()+1);
      for(int j=0;j<nn;++j){
        int net=io.scalar(restore?0:it->first);auto& dirs=local[net];auto di=dirs.begin();int nd=io.count(dirs.size(),8);
        for(int d=0;d<nd;++d){int o=io.scalar(restore?0:int(*di++));if(restore)dirs.insert(static_cast<Orientation>(o));}
        if(!restore)++it;
      }
      if(!restore)++ii;
    }
  }
  io.finish();
  if(!restore && std::rename(temp.c_str(),file.c_str())!=0)throw std::runtime_error("cannot publish routing checkpoint");
  RTLOG.info(Loc::current(),restore?"Restored route checkpoint ":"Saved route checkpoint ",stage);
}
