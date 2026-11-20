"""Prepare a reproducible source patch; retain the verified upstream slice intact."""
import hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'third_party/ieda-public-idb'
work=ROOT/'.cache/idb-export-build';work.mkdir(exist_ok=True)
p=source/'src/database/manager/builder/gds_builder/gds_write.cpp'
text=p.read_text()
changes=[('  write_version();\n  write_design();\n',''),
 ('new GdsStruct("DIEAREA")','new GdsStruct(_def_service->get_design()->get_design_name())'),
 ('GdsStruct* gds_struct = new GdsStruct("PINS");','addSRefDefault("PINS");\n  GdsStruct* gds_struct = new GdsStruct("PINS");'),
 ('#include "../../../data/design/IdbDesign.h"','#include "IdbDesign.h"')]
for old,new in changes:
    if text.count(old)!=1:raise ValueError('Unexpected upstream text: '+old)
    text=text.replace(old,new)
(work/'gds_write.cpp').write_text(text)
compat=(source/'src/utility/string/Str.cc').read_text()
compat=compat.replace('return std::string(absl::StripPrefix(str, prefix));','if (str.starts_with(prefix)) str.remove_prefix(prefix.size()); return std::string(str);')
compat=compat.replace('return std::string(absl::StripSuffix(str, suffix));','if (str.ends_with(suffix)) str.remove_suffix(suffix.size()); return std::string(str);')
(work/'Str.cc').write_text(compat)
for name in ('CMakeLists.txt','main.cpp','binary_writer.cpp'):
    shutil.copyfile(ROOT/'environments/ieda-export'/name,work/name)
(work/'patch-manifest.json').write_text(json.dumps({'upstream':json.loads((source/'source-manifest.json').read_text())['commit'],
 'changes':['Design name as the single top','Reference IO pins from top','Omit detached metadata cells','Compile the local binary GDS serializer against public iDB GdsData'],
 'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in work.glob('*') if p.is_file() and p.suffix in ('.cpp','.txt')}},indent=2))
