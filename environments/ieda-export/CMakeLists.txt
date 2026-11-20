cmake_minimum_required(VERSION 3.16)
project(aieda_native_idb_export LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
find_package(OpenMP REQUIRED)
find_package(ZLIB REQUIRED)
find_package(absl CONFIG REQUIRED)
find_package(BISON REQUIRED)
set(SRC /source/src)
set(DB ${SRC}/database)
set(LD ${SRC}/third_party/lefdef)
file(GLOB_RECURSE DATA ${DB}/data/design/*.cpp ${DB}/basic/geometry/*.cpp)
file(GLOB LEF ${LD}/lef/lef/*.cpp)
file(GLOB DEF ${LD}/def/def/*.cpp)
BISON_TARGET(Lef ${LD}/lef/lef/lef.y ${CMAKE_CURRENT_BINARY_DIR}/lef.tab.cpp DEFINES_FILE ${CMAKE_CURRENT_BINARY_DIR}/lef.tab.h COMPILE_FLAGS "-plefyy")
BISON_TARGET(Def ${LD}/def/def/def.y ${CMAKE_CURRENT_BINARY_DIR}/def.tab.cpp DEFINES_FILE ${CMAKE_CURRENT_BINARY_DIR}/def.tab.h COMPILE_FLAGS "-pdefyy")
file(GLOB SERVICES ${DB}/manager/service/lef_service/*.cpp ${DB}/manager/service/def_service/*.cpp)
file(GLOB PROPS ${DB}/manager/builder/lef_builder/property_parser/*.cpp)
file(GLOB GDS ${DB}/manager/parser/gdsii/*.cpp)
list(FILTER GDS EXCLUDE REGEX "GTWriter.cpp$")
add_executable(ieda-idb-export main.cpp binary_writer.cpp /work/gds_write.cpp
 ${DATA} ${LEF} ${DEF} ${SERVICES} ${PROPS} ${GDS} ${BISON_Lef_OUTPUTS} ${BISON_Def_OUTPUTS}
 ${LD}/def/defzlib/defzlib.cpp
 ${DB}/manager/builder/lef_builder/lef_read.cpp
 ${DB}/manager/builder/def_builder/def_read.cpp
 /work/Str.cc)
target_include_directories(ieda-idb-export PRIVATE
 ${CMAKE_CURRENT_BINARY_DIR}
 ${DB}/data/design ${DB}/data/design/db_design ${DB}/data/design/db_layout ${DB}/data/design/db_property
 ${DB}/basic/geometry ${DB}/manager/service/def_service ${DB}/manager/service/lef_service
 ${DB}/manager/service ${DB}/manager/builder/lef_builder ${DB}/manager/builder/def_builder
 ${DB}/manager/builder/gds_builder ${DB}/manager/parser/gdsii
 ${LD}/lef ${LD}/lef/lef ${LD}/def/def ${LD}/def/defzlib
 ${SRC}/utility/string ${SRC}/utility/memory ${SRC}/utility/stdBase
 ${SRC}/utility/solver)
target_compile_options(ieda-idb-export PRIVATE -O1 -w)
set_source_files_properties(/work/Str.cc PROPERTIES COMPILE_OPTIONS "-I${SRC}/utility/stdBase/include")
target_link_libraries(ieda-idb-export PRIVATE OpenMP::OpenMP_CXX ZLIB::ZLIB absl::strings pthread)
