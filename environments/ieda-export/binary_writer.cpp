// Local native binary serializer for the public iEDA GdsData representation.
// Geometry remains produced by iEDA Def2GdsWrite; no DEF conversion library.
#include "GTWriter.hpp"
#include <cmath>
#include <cstdint>
#include <fstream>
#include <stdexcept>
#include <vector>
namespace idb {
namespace {
using Bytes=std::vector<unsigned char>;
void be16(Bytes& b,int value){b.push_back((value>>8)&255);b.push_back(value&255);}
void be32(Bytes& b,int32_t value){uint32_t u=static_cast<uint32_t>(value);for(int i=3;i>=0;--i)b.push_back((u>>(i*8))&255);}
void real8(Bytes& b,double value){
  if(!std::isfinite(value))throw std::runtime_error("Non-finite GDS real");
  if(value==0){b.insert(b.end(),8,0);return;}
  unsigned sign=value<0?128:0;value=std::abs(value);int exponent=64;
  while(value>=1){value/=16;++exponent;}
  while(value<1.0/16){value*=16;--exponent;}
  if(exponent<0||exponent>127)throw std::runtime_error("GDS real overflow");
  b.push_back(sign|exponent);
  for(int i=0;i<7;++i){value*=256;auto v=static_cast<unsigned>(value);b.push_back(v&255);value-=v;}
}
void record(std::ofstream* out,unsigned type,unsigned data_type,Bytes bytes={}){
  if(bytes.size()%2)bytes.push_back(0);
  if(bytes.size()+4>65534)throw std::runtime_error("GDS record too long");
  Bytes head;be16(head,bytes.size()+4);head.push_back(type);head.push_back(data_type);
  out->write(reinterpret_cast<const char*>(head.data()),head.size());
  out->write(reinterpret_cast<const char*>(bytes.data()),bytes.size());
  if(!*out)throw std::runtime_error("GDS stream failed");
}
void i16(std::ofstream* o,unsigned t,int v,unsigned dt=2){Bytes b;be16(b,v);record(o,t,dt,b);}
void i32(std::ofstream* o,unsigned t,int32_t v){Bytes b;be32(b,v);record(o,t,3,b);}
void str(std::ofstream* o,unsigned t,const std::string& v){record(o,t,6,Bytes(v.begin(),v.end()));}
Bytes timestamp(){Bytes b;for(int n:{2026,1,1,0,0,0,2026,1,1,0,0,0})be16(b,n);return b;}
}
GdsiiTextWriter::GdsiiTextWriter()=default;
GdsiiTextWriter::GdsiiTextWriter(GdsData* d,const std::string file){init(file,d);}
GdsiiTextWriter::~GdsiiTextWriter(){if(_stream){_stream->close();delete _stream;}_data=nullptr;}
bool GdsiiTextWriter::init(std::string file,GdsData* d){
  if(file.empty()||!d)return false;
  if(_stream){_stream->close();delete _stream;}
  _data=d;_stream=new std::ofstream(file,std::ios::out|std::ios::binary|std::ios::trunc);
  if(!*_stream)throw std::runtime_error("Cannot open GDS output");return true;
}
bool GdsiiTextWriter::close(){_stream->close();return !_stream->fail();}
void GdsiiTextWriter::flush(){_stream->flush();if(!*_stream)throw std::runtime_error("Cannot flush GDS");_data->clear_struct_list();}
bool GdsiiTextWriter::begin(){
  i16(_stream,0,600);record(_stream,1,2,timestamp());str(_stream,2,"iEDA_iDB_abstract");
  Bytes b;real8(b,_data->get_unit().dbu_in_user());real8(b,_data->get_unit().dbu_in_meter());record(_stream,3,5,b);return true;
}
bool GdsiiTextWriter::finish(){writeStruct();writeTopStruct();write_endlib();flush();return close();}
void GdsiiTextWriter::write_endlib()const{record(_stream,4,0);}
void GdsiiTextWriter::write_bgnstr(GdsStruct*)const{record(_stream,5,2,timestamp());}
void GdsiiTextWriter::write_strname(GdsStruct* s)const{str(_stream,6,s->get_name());}
void GdsiiTextWriter::write_endstr()const{record(_stream,7,0);}
void GdsiiTextWriter::writeTopStruct(){
  auto s=_data->get_top_struct();if(!s)throw std::runtime_error("GDS top missing");
  write_bgnstr(s);write_strname(s);for(auto e:s->get_element_list())write_struct_element(e);write_endstr();
}
void GdsiiTextWriter::writeStruct(){
  for(auto s:_data->get_struct_list()){write_bgnstr(s);write_strname(s);for(auto e:s->get_element_list())write_struct_element(e);write_endstr();}flush();
}
void GdsiiTextWriter::write_layer(GdsLayer layer)const{if(layer<0)throw std::runtime_error("Invalid GDS layer");i16(_stream,13,layer);}
void GdsiiTextWriter::write_xy(GdsElemBase* e)const{
  Bytes b;for(auto xy:e->get_xy().get_coords()){be32(b,xy.x);be32(b,xy.y);}
  if(b.empty())throw std::runtime_error("Empty GDS XY");record(_stream,16,3,b);
}
void GdsiiTextWriter::write_strans(const GdsStrans& s)const{
  if(s.bit_flag)i16(_stream,26,s.bit_flag,1);
  if(s.mag!=1){Bytes b;real8(b,s.mag);record(_stream,27,5,b);}
  if(s.angle!=0){Bytes b;real8(b,s.angle);record(_stream,28,5,b);}
}
void GdsiiTextWriter::write_property(GdsElemBase* e)const{
  for(const auto& [attr,value]:e->get_property_map()){if(attr<0)continue;i16(_stream,43,attr);str(_stream,44,value);}
}
void GdsiiTextWriter::write_endel()const{record(_stream,17,0);}
void GdsiiTextWriter::write_struct_element(GdsElemBase* e)const{
  if(!e)throw std::runtime_error("Null GDS element");
  switch(e->get_elem_type()){
    case GdsElemType::kBoundary:{auto x=dynamic_cast<GdsBoundary*>(e);record(_stream,8,0);write_layer(x->layer);i16(_stream,14,x->data_type);break;}
    case GdsElemType::kPath:{auto x=dynamic_cast<GdsPath*>(e);record(_stream,9,0);write_layer(x->layer);i16(_stream,14,x->data_type);i16(_stream,33,(int)x->path_type);i32(_stream,15,x->width);break;}
    case GdsElemType::kSref:{auto x=dynamic_cast<GdsSref*>(e);record(_stream,10,0);str(_stream,18,x->sname);write_strans(x->strans);break;}
    case GdsElemType::kAref:{auto x=dynamic_cast<GdsAref*>(e);record(_stream,11,0);str(_stream,18,x->sname);write_strans(x->strans);Bytes b;be16(b,x->col);be16(b,x->row);record(_stream,19,2,b);break;}
    case GdsElemType::kText:{auto x=dynamic_cast<GdsText*>(e);record(_stream,12,0);write_layer(x->layer);i16(_stream,22,x->text_type);i16(_stream,23,(int)x->presentation,1);write_strans(x->strans);write_xy(e);str(_stream,25,x->str);write_property(e);write_endel();return;}
    case GdsElemType::kNode:{auto x=dynamic_cast<GdsNode*>(e);record(_stream,21,0);write_layer(x->layer);i16(_stream,42,x->node_type);break;}
    case GdsElemType::kBox:{auto x=dynamic_cast<GdsBox*>(e);record(_stream,45,0);write_layer(x->layer);i16(_stream,46,x->box_type);break;}
    default:throw std::runtime_error("Unsupported GDS element");
  }
  write_xy(e);write_property(e);write_endel();
}
}
