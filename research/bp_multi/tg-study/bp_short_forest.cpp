// Run the official native route-tree conversion once per retained terminal component.
#include "Utility.hpp"
#include <iostream>
using namespace irt;
static LayerCoord coord() {
  int x, y, layer;
  if (!(std::cin >> x >> y >> layer)) throw std::runtime_error("Incomplete coordinate");
  return LayerCoord(x,y,layer);
}
int main() {
  std::ios::sync_with_stdio(false);
  std::string name;
  int wire_count, group_count;
  while(std::cin >> name >> wire_count >> group_count) {
    std::vector<Segment<LayerCoord>> wires;
    for(int i=0;i<wire_count;++i){ auto first=coord(); auto last=coord(); wires.emplace_back(first,last); }
    std::cout<<name<<"\n";
    for(int i=0;i<group_count;++i){
      int n; std::cin>>n; std::vector<LayerCoord> roots;
      std::map<LayerCoord,std::set<int32_t>,CmpLayerCoordByXASC> pins;
      for(int j=0;j<n;++j){auto p=coord(); roots.push_back(p);pins[p].insert(j);}
      if(pins.size()<2)continue;
      auto part=wires;
      auto tree=Utility::getTreeByFullFlow(roots,part,pins);
      for(auto edge:Utility::getSegListByTree(tree)){
        for(auto node:{edge.get_first(),edge.get_second()}) {
          auto p=node->value();std::cout<<p.get_x()<<" "<<p.get_y()<<" "<<p.get_layer_idx()<<" ";
        }
        std::cout<<"\n";
      }
    }
    std::cout<<"END\n";
  }
}
