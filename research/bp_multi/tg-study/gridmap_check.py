"""Regression for the patched upstream GridMap template; does not execute a router."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

here = Path(__file__).resolve().parent
header = Path('/srv/edagent/ieda-rootcause-20261112/source/src/operation/iRT/source/data_manager/basic/GridMap.hpp')
assert hashlib.sha256(header.read_bytes()).hexdigest() == 'a448687711f3c9b29a0910b61e1288e31a23078401e7db04124139880834d121'
with tempfile.TemporaryDirectory(dir=here) as tmp:
    root = Path(tmp)
    shutil.copy2(header, root/'GridMap.hpp')
    subprocess.run(['patch', '--fuzz=0', 'GridMap.hpp', '-i', str(here/'gridmap-allocation.candidate.patch')], cwd=root, check=True)
    (root/'RTHeader.hpp').write_text('#include <cstdint>\n#include <cstddef>\n#include <utility>\n#include <type_traits>\n')
    (root/'Logger.hpp').write_text('struct Loc { static int current(){return 0;} }; struct L { template<typename... T> void error(T...){throw 1;} }; inline L RTLOG;\n')
    (root/'test.cpp').write_text(r'''
#include <cassert>
#include <new>
#include "GridMap.hpp"
struct Cell {
  inline static bool refuse = false;
  int n = 0;
  static void* operator new[](std::size_t n) {
    if (refuse) throw std::bad_alloc{};
    return ::operator new[](n);
  }
  static void operator delete[](void* p) { ::operator delete[](p); }
};
int main() {
  irt::GridMap<Cell> grid;
  Cell::refuse = true;
  try { grid.init(7, 9); return 1; } catch (const std::bad_alloc&) {}
  assert(grid.empty());
  grid.free();
  Cell::refuse = false;
  grid.init(7, 9, Cell{3});
  grid[5][7].n = 11;
  assert(grid[5][7].n == 11 && grid[6][7].n == 3);
  grid.free();
  assert(grid.empty());
}
''')
    subprocess.run(['c++', '-std=c++17', '-g', '-fsanitize=undefined', '-fno-sanitize-recover=all', 'test.cpp', '-o', 'test'], cwd=root, check=True)
    subprocess.run([str(root/'test')], cwd=root, check=True)
    (here/'gridmap-check.json').write_text(json.dumps({
        'upstream_header_sha256': hashlib.sha256(header.read_bytes()).hexdigest(),
        'patched_header_sha256': hashlib.sha256((root/'GridMap.hpp').read_bytes()).hexdigest(),
        'checks': ['second allocation failure', 'empty after failure', 'cleanup', 'retry', 'normal distinct grid cells'],
        'scope': 'upstream template only, UBSan, standalone with logging facade', 'passed': True}, indent=2))
