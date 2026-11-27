// Read-only index of existing conductors and obstructions, with incremental ECO reservations.
#include <boost/geometry.hpp>
#include <boost/geometry/index/rtree.hpp>
#include <array>
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <queue>
#include <set>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>
#include <vector>
namespace bg=boost::geometry;
namespace bi=bg::index;
using Point=bg::model::point<int,2,bg::cs::cartesian>;
using Rect=bg::model::box<Point>;
using Owner=std::pair<int,int>; // net, removable original segment index (-1 for fixed geometry)
using Entry=std::pair<Rect,Owner>;
using Tree=bi::rtree<Entry,bi::quadratic<16>>;
using Node=std::array<int,3>;
using Box=std::array<int,4>;
using Grid=std::array<int,3>;
using Key=uint64_t;
static constexpr Key END=UINT64_MAX;
Key key(Node p){return (Key(p[0])<<26)|(Key(p[1])<<4)|p[2];}
Node unpack(Key p){return {int(p>>26),int((p>>4)&0x3fffff),int(p&15)};}
int distance(Node a,Node b){return abs(a[0]-b[0])+abs(a[1]-b[1])+350*abs(a[2]-b[2]);}
Rect rect(Box b){return Rect(Point(b[0],b[1]),Point(b[2],b[3]));}
struct Router {
  Tree trees[15];
  Grid tracks[6][2];
  int width[6];
  bool reuse_copper=std::getenv("EDA_ECO_REUSE_COPPER")!=nullptr;
  std::map<int,std::vector<Box>> pin_ports;
  std::set<Owner> removed;
  bool negotiate=false;
  int penalty=0;
  std::set<Owner>* touched=nullptr;
  Box die, via[5][3];
  void load(std::istream& tasks,const char* geometry){
    for(int& x:die)tasks>>x;
    for(auto& layer:tracks)for(auto& axis:layer)for(int& x:axis)tasks>>x;
    for(int& x:width)tasks>>x;
    for(auto& v:via)for(auto& b:v)for(int& x:b)tasks>>x;
    std::vector<Entry> items[15];
    std::ifstream data(geometry,std::ios::binary);
    std::ifstream ids;
    if(const char* file=std::getenv("EDA_ECO_ORIGINS"))ids.open(file,std::ios::binary);
    if(const char* file=std::getenv("EDA_ECO_REMOVED")){
      std::ifstream f(file);int net,seg;while(f>>net>>seg)removed.insert({net,seg});
    }
    std::array<int32_t,6> r;
    while(data.read(reinterpret_cast<char*>(r.data()),sizeof r)){
      if(r[1]<0||r[1]>=15)throw std::runtime_error("bad geometry layer");
      int seg=-1;
      if(ids.is_open()&&!ids.read(reinterpret_cast<char*>(&seg),sizeof(seg)))throw std::runtime_error("short geometry origins");
      if(!removed.count({r[0],seg}))items[r[1]].emplace_back(rect({r[2],r[3],r[4],r[5]}),Owner{r[0],seg});
    }
    if(!data.eof()||data.gcount())throw std::runtime_error("invalid geometry file");
    for(int l=0;l<15;l++){trees[l]=Tree(items[l]);std::vector<Entry>().swap(items[l]);}
    if(const char* pins=std::getenv("EDA_ECO_PIN_PORTS")){
      std::ifstream f(pins);int net;Box b;
      while(f>>net>>b[0]>>b[1]>>b[2]>>b[3])pin_ports[net].push_back(b);
      if(!f.eof())throw std::runtime_error("invalid access ports");
    }
    if(const char* file=std::getenv("EDA_ECO_STEMS")){
      std::ifstream f(file);Node u,v;int net,grade;
      while(f>>net>>u[0]>>u[1]>>u[2]>>v[0]>>v[1]>>v[2]>>grade){
        if(grade!=2||u[2]!=v[2])throw std::runtime_error("invalid preserved stem");
        shapes(u,v,[&](int l,Box bx){trees[l].insert({rect(bx),{net,-1}});return true;});
      }
      if(!f.eof())throw std::runtime_error("cannot read preserved stems");
    }
  }
  bool track(int l,int axis,int coord)const {
    auto [s,n,p]=tracks[l][axis];
    return coord>=s && coord<=s+(n-1)*p && (coord-s)%p==0;
  }
  template<class Fn> bool shapes(Node a,Node b,Fn fn){
    int l=a[2];
    if(l==b[2]){
      int h=width[l]/2;
      return fn(l,Box{std::min(a[0],b[0])-h,std::min(a[1],b[1])-h,std::max(a[0],b[0])+h,std::max(a[1],b[1])+h});
    }
    int z=std::min(l,b[2]);int layers[]={z,z+1,z+10};
    for(int i=0;i<3;i++){
      Box r=via[z][i];
      for(int j=0;j<4;j++)r[j]+=a[j%2];
      if(!fn(layers[i],r))return false;
    }
    return true;
  }
  bool allowed(int net,Node a,Node b,bool spacing){
    penalty=0;
    return shapes(a,b,[&](int l,Box r){
      if(r[0]<die[0]||r[1]<die[1]||r[2]>die[2]||r[3]>die[3])return false;
      if(l==0){
        auto ports=pin_ports.find(net);
        if(ports==pin_ports.end()||std::none_of(ports->second.begin(),ports->second.end(),
              [&](const Box& port){return bg::covered_by(rect(r),rect(port));}))return false;
      }
      int pad=spacing?width[(l>=10?l-10:l)]-1:0;
      Rect q=rect({r[0]-pad,r[1]-pad,r[2]+pad,r[3]+pad});
      auto hits=bi::intersects(q)&&bi::satisfies([&](const Entry& e){return e.second.first!=net && !removed.count(e.second);});
      for(auto hit=trees[l].qbegin(hits);hit!=trees[l].qend();++hit){
        if(!spacing&&reuse_copper){
          Rect overlap;
          if(bg::intersection(q,hit->first,overlap)){
            auto own=bi::intersects(overlap)&&bi::satisfies([&](const Entry& e){
              return e.second.first==net && !removed.count(e.second) && bg::covered_by(overlap,e.first);
            });
            if(trees[l].qbegin(own)!=trees[l].qend())continue;
          }
        }
        if(!negotiate || hit->second.second<0)return false;
        penalty+=18000;
        if(touched)touched->insert(hit->second);
      }
      return true;
    });
  }
  struct Step{int cost;Key previous;};
  std::vector<Node> find(int net, Node a,Node b,const std::vector<Node>& starts,const std::vector<Node>& ends,
                         int margin,bool spacing){
    Box window{std::max(die[0],std::min(a[0],b[0])-margin),std::max(die[1],std::min(a[1],b[1])-margin),
               std::min(die[2],std::max(a[0],b[0])+margin),std::min(die[3],std::max(a[1],b[1])+margin)};
    auto inside=[&](Node n){return n[0]>=window[0]&&n[1]>=window[1]&&n[0]<=window[2]&&n[1]<=window[3];};
    std::vector<int> axes[2];
    for(int d=0;d<2;d++){
      auto& v=axes[d];
      for(int l=1;l<=5;l++){
        auto [s,n,p]=tracks[l][d];
        int i=std::max(0,(window[d]-s+p-1)/p);
        for(;i<n && s+i*p<=window[d+2];i++)v.push_back(s+i*p);
      }
      for(const auto* list:{&starts,&ends})for(auto vtx:*list)if(inside(vtx))v.push_back(vtx[d]);
      auto ports=pin_ports.find(net);
      if(ports!=pin_ports.end())for(Box port:ports->second){
        for(int c:{port[d]+width[0]/2,port[d+2]-width[0]/2}){
          if(c>=window[d]&&c<=window[d+2])v.push_back(c);
        }
      }
      std::sort(v.begin(),v.end());v.erase(std::unique(v.begin(),v.end()),v.end());
    }
    std::priority_queue<std::pair<int64_t,Key>> frontier[2];
    std::unordered_map<Key,Step> seen[2];
    std::array<int,2> expanded{};
    Node aim[]={b,a};
    auto push=[&](int side,Node n,int cost,Key parent){
      Key k=key(n);auto it=seen[side].find(k);
      if(it!=seen[side].end()&&it->second.cost<=cost)return;
      seen[side][k]={cost,parent};
      frontier[side].emplace(-(int64_t(cost)+distance(n,aim[side])*2),k);
    };
    for(Node p:starts)if(inside(p))push(0,p,0,END);
    for(Node p:ends)if(inside(p))push(1,p,0,END);
    while(!frontier[0].empty()&&!frontier[1].empty()){
      int side=expanded[0]>expanded[1]?1:0;
      auto [priority,k]=frontier[side].top();frontier[side].pop();
      Node p=unpack(k);int cost=seen[side].at(k).cost,l=p[2];
      if(-priority!=int64_t(cost)+distance(p,aim[side])*2)continue;
      expanded[side]++;
      if(seen[1-side].count(k)){
        std::vector<Node> raw;
        for(Key j=k;j!=END;j=seen[0].at(j).previous)raw.push_back(unpack(j));
        std::reverse(raw.begin(),raw.end());
        for(Key j=seen[1].at(k).previous;j!=END;j=seen[1].at(j).previous)raw.push_back(unpack(j));
        std::vector<Node> path;
        for(Node v:raw){
          if(path.size()>=2){
            auto u=path[path.size()-2], w=path.back();
            if(u[2]==v[2]&&w[2]==v[2]&&((u[0]==w[0]&&w[0]==v[0])||(u[1]==w[1]&&w[1]==v[1]))&&allowed(net,u,v,spacing))path.pop_back();
          }
          path.push_back(v);
        }
        return path;
      }
      for(int d=0;d<2;d++){
        if(l!=0&&!track(l,1-d,p[1-d]))continue;
        auto& axis=axes[d];auto i=std::lower_bound(axis.begin(),axis.end(),p[d])-axis.begin();
        for(int sign:{-1,1}){
          auto j=i+sign;
          if(j<0||j>=static_cast<long>(axis.size()))continue;
          Node n=p;n[d]=axis[j];
          if(allowed(net,p,n,spacing))push(side,n,cost+penalty+distance(p,n)*(d!=(l%2)?2:1),k);
        }
      }
      for(int dz:{-1,1}){
        Node n=p;n[2]+=dz;
        if(n[2]<int(pin_ports.empty())||n[2]>5)continue;
        if(allowed(net,p,n,spacing))push(side,n,cost+penalty+560,k);
      }
    }
    if(std::getenv("EDA_ECO_DIAG")){
      std::cerr<<"search "<<net<<" margin "<<margin<<" spacing "<<spacing
               <<" reached "<<seen[0].size()<<' '<<seen[1].size()<<"\n";
    }
    return {};
  }
};
int main(int argc,char**argv){
  if(argc!=4&&argc!=5)return 2;
  Router r;std::ifstream tasks(argv[1]);r.load(tasks,argv[2]);
  if(argc==5){
    std::ifstream previous(argv[4]);int number,grade;Node u,v;
    while(previous>>number>>u[0]>>u[1]>>u[2]>>v[0]>>v[1]>>v[2]>>grade){
      if(!r.allowed(number,u,v,grade))throw std::runtime_error("reserved bridge disagrees with geometry");
      r.shapes(u,v,[&](int l,Box bx){r.trees[l].insert({rect(bx),{number,-1}});return true;});
    }
    if(!previous.eof())throw std::runtime_error("invalid reserved bridges");
  }
  std::ofstream out(argv[3]);int net,done=0,open=0;Node a,b;size_t na,nb;
  std::ofstream displaced;
  if(const char* path=std::getenv("EDA_ECO_DISPLACE")){displaced.open(path);r.negotiate=true;}
  while(tasks>>net>>a[0]>>a[1]>>a[2]>>b[0]>>b[1]>>b[2]>>na>>nb){
    std::vector<Node> starts(na),ends(nb),path;
    for(auto* nodes:{&starts,&ends})for(auto& n:*nodes)for(int& x:n)tasks>>x;
    if(!tasks)throw std::runtime_error("truncated task");
    bool used_spacing=true;
    std::vector<int> margins{4000,12000,32000,80000};
    if(std::getenv("EDA_ECO_EXTENDED"))margins={180000,420000};
    for(int margin:margins){
      for(bool spacing:{true,false}){
        if(r.negotiate && spacing)continue;
        path=r.find(net,a,b,starts,ends,margin,spacing);
        if(!path.empty()){used_spacing=spacing;break;}
      }
      if(!path.empty())break;
    }
    if(path.empty()){std::cerr<<"OPEN "<<net<<"\n";open++;}
    else {
      std::set<Owner> affected;
      if(r.negotiate)r.touched=&affected;
      for(size_t i=1;i<path.size();i++){
        auto u=path[i-1],v=path[i];
        if(!r.allowed(net,u,v,used_spacing))throw std::runtime_error("merged segment check failed");
        r.shapes(u,v,[&](int l,Box bx){r.trees[l].insert({rect(bx),{net,-1}});return true;});
        out<<net<<" "<<u[0]<<" "<<u[1]<<" "<<u[2]<<" "<<v[0]<<" "<<v[1]<<" "<<v[2]<<" "<<used_spacing<<"\n";
      }
      r.touched=nullptr;
      for(auto [other,seg]:affected){displaced<<other<<" "<<seg<<"\n";r.removed.insert({other,seg});}
    }
    if(++done%25==0){out.flush();std::cerr<<"tasks "<<done<<" open "<<open<<"\n";}
  }
  std::cerr<<"tasks "<<done<<" open "<<open<<"\n";return open?3:0;
}
