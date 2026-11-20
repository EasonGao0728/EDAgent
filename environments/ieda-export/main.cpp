// Standalone iEDA/iDB export entry. No placement, routing or external converter.
#include "lef_read.h"
#include "def_read.h"
#include "gds_write.h"
#include <fstream>
#include <stdexcept>
int main(int argc,char** argv) {
  try {
    if(argc<5)throw std::runtime_error("Usage: ieda-idb-export input.def output.gds tech.lef cell.lef ...");
    idb::IdbLefService lef;
    std::vector<std::string> files(argv+3,argv+argc);
    if(lef.LefFileInit(files)!=idb::IdbLefServiceResult::kServiceSuccess)throw std::runtime_error("LEF init failed");
    for(auto& path:files) {
      idb::LefRead reader(&lef);
      if(!reader.createDb(path.c_str()))throw std::runtime_error("LEF parse failed: "+path);
    }
    // The public builder shifts nonzero LEF ORIGINs. This qualified export profile
    // admits only zero-origin libraries, so no silent coordinate convention change.
    for(auto cell:lef.get_layout()->get_cell_master_list()->get_cell_master())
      if(cell->get_origin_x()!=0 || cell->get_origin_y()!=0)throw std::runtime_error("Unsupported nonzero LEF ORIGIN");
    idb::IdbDefService def(lef.get_layout());
    if(def.DefFileInit(argv[1])!=idb::IdbDefServiceResult::kServiceSuccess)throw std::runtime_error("DEF init failed");
    idb::DefRead reader(&def);
    if(!reader.createDb(argv[1]))throw std::runtime_error("DEF parse failed");
    idb::Def2GdsWrite writer(&def);
    if(!writer.writeDb(argv[2]))throw std::runtime_error("GDS write failed");
    std::cout<<"IDB_NATIVE_EXPORT_OK "<<def.get_design()->get_design_name()<<std::endl;
  }catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}
}
