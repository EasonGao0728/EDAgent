// Preserve the physical pin-to-track conductors already measured by PA.
struct DRAccessLead {
  int pin, layer, x, y, a, b;
  bool owns(const Segment<LayerCoord>& segment) const {
    const auto& p=segment.get_first();
    const auto& q=segment.get_second();
    if (p.get_layer_idx()!=layer || q.get_layer_idx()!=layer || p==q) return false;
    auto inside=[](int v,int u,int w){return std::min(u,w)<=v && v<=std::max(u,w);};
    return (p.get_y()==y && q.get_y()==y && inside(p.get_x(),a,x) && inside(q.get_x(),a,x))
        || (p.get_x()==a && q.get_x()==a && inside(p.get_y(),y,b) && inside(q.get_y(),y,b));
  }
};

const std::map<int,std::vector<DRAccessLead>>& drAccessLeads()
{
  static const auto leads=[]{
    std::map<int,std::vector<DRAccessLead>> result;
    const char* path=std::getenv("IEDA_RT_PA_ESCAPE_FILE");
    if(!path) return result;
    std::ifstream f(path);
    std::map<std::string,int> net_ids;
    auto& db=RTDM.getDatabase();
    auto& nets=db.get_net_list();
    for(auto& net:nets) net_ids.emplace(net.get_net_name(),net.get_net_idx());
    auto segments=RTDM.getNetDetailedResultMap(db.get_die());
    std::string net,terminal;
    int x,y,a,b;
    while(f>>net>>terminal>>x>>y>>a>>b) {
      int ni=net_ids.at(net);
      auto& pins=nets.at(ni).get_pin_list();
      auto pin=std::find_if(pins.begin(),pins.end(),[&](auto& p){return p.get_pin_name()==terminal;});
      if(pin==pins.end()) throw std::runtime_error("missing DR access pin");
      auto p=pin->get_access_point().getRealLayerCoord();
      int l=p.get_layer_idx();
      if(p.get_x()!=x || p.get_y()!=y || a>=x || b==y || db.get_routing_layer_list().at(l).get_layer_name()!="metal3")
        throw std::runtime_error("DR access endpoint differs from PA");
      LayerCoord corner(a,y,l),anchor(a,b,l);
      auto contains=[&](const LayerCoord& u,const LayerCoord& v){
        for(auto s:segments.at(ni)){
          auto& first=s->get_first();auto& second=s->get_second();
          if((first==u && second==v) || (first==v && second==u)) return true;
        }
        return false;
      };
      if(!contains(p,corner) || !contains(corner,anchor))
        throw std::runtime_error("missing physical pin-to-track lead before DR: "+terminal);
      result[ni].push_back({pin->get_pin_idx(),l,x,y,a,b});
    }
    if(!f.eof() || result.empty()) throw std::runtime_error("invalid DR access lead list");
    return result;
  }();
  return leads;
}
