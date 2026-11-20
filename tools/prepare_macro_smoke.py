"""Build a clearly labelled derived integration fixture from pinned public tests.

This is NOT an industrial design or an independent benchmark. Eight BUF_X1 cells
are inserted in the OpenROAD macro_only test's four chains to exercise the
macro-to-standard-cell handoff. Source data are retained unchanged.
"""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'third_party/openroad-macro-reference'
dest=ROOT/'cases/nangate_macro_smoke';dest.mkdir(exist_ok=True)
meta=json.loads((source/'SOURCE.json').read_text())
original=source/'src/mpl/test/testcases/macro_only.v'
text=original.read_text()
text=text.replace('module macro_only','module macro_smoke')
text=text.replace('wire   w1, w2, w3, w4;','wire w1, w2, w3, w4;\n  wire b1,b2,b3,b4,b11,b21,b31,b41;')
for i in range(1,5):
    text=text.replace(f'.I1(w{i})',f'.I1(b{i})')
    text=text.replace(f'.I1(w{i}1)',f'.I1(b{i}1)')
buffers='\n'.join(f'  BUF_X1 B{i}{j} (.A(w{i}{j}), .Z(b{i}{j}));' for i in range(1,5) for j in ('','1'))
text=text.replace('endmodule',buffers+'\nendmodule')
(dest/'macro_smoke.v').write_text(text,encoding='utf-8')
(dest/'constraints.sdc').write_text('# No timing claim; bounded placement integration fixture.\n',encoding='utf-8')
libs=['test/Nangate45/Nangate45_tech.lef','test/Nangate45/Nangate45_stdcell.lef',
      'test/Nangate45/Nangate45_typ.lib','src/mpl/test/testcases/macro_only.lef','src/mpl/test/testcases/macro_only.lib']
inputs=[original]+[source/p for p in libs]
manifest={'schema_version':1,'case_id':'nangate_macro_smoke','top':'macro_smoke',
          'source':meta,'classification':'derived public integration fixture; fake macros, not a silicon benchmark',
          'adaptations':['Add 8 BUF_X1 instances on the 4 macro chains','Create floorplan from netlist; do not load preplaced DEF'],
          'expected_hard_macros':10,'expected_standard_cells':8,'die_microns':[0,0,600,600],
          'core_microns':[5,5,595,595],'required_constraints':['fixed_instances','die_bounds','nonoverlap'],
          'source_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}}
(dest/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(dest)
