"""Read-only regression using archived original geometry and explicit disconnected controls."""
import gzip
import json
from pathlib import Path
import tempfile

from verify_route import ROOT, PhysicalLibrary, independent_graph, log_check, read_def, track_grid, measure_paths, section, sha
from def_conductors import touch_groups

official=ROOT.parent/'ieda-rootcause-20261112'
old=official/'neighborhood-308-one-round-official-control/result'
log=(old/'rt/rt.log').read_text()
assert log_check(log,308)['passed']
assert not log_check(log.replace('Info report] Completed','Info report] Missing'),308)['passed']
assert not log_check(log,307)['passed']
assert not log_check(log+log,308)['passed']
ref=ROOT/'runs/bp-multi-tg-study-20261121/reference/data'
archive=Path('/srv/benchmarks/iBench/benchmarks/results/full_2d_20261020/s1238_nangate45/routing.def.gz')
text=gzip.decompress(archive.read_bytes()).decode()
with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp)/'routed.def'
    p.write_text(text)
    db=read_def(p)
expected={name:pins for name,pins in db['nets'].items() if len(pins)>=2}
lib=PhysicalLibrary(ref/'input2.lef',[ref/f'input{i}.lef' for i in range(3,10)],db['units'])
graph=independent_graph(text,db,expected,lib)
assert graph['passed'] and graph['net_count']==299 and graph['pins']==1081
row=next(r for r in section(text,'NETS') if r.split()[0] in expected and '+ ROUTED' in r)
cut=row.split('+ ROUTED')[0]
assert text.count(row)==1
broken=independent_graph(text.replace(row,cut),db,expected,lib)
assert not broken['passed'] and broken['disconnected_nets']>0
floater=row+'\n    NEW metal2 ( 200000000 200000000 ) ( 200000030 * )'
extra=independent_graph(text.replace(row,floater),db,expected,lib)
assert not extra['passed'] and extra['floating_primitives']>0
assert len(set(touch_groups([[('M1',0,0,2,2)],[('M2',0,0,2,2)]])))==2
assert len(set(touch_groups([[('M1',0,0,2,2)],[('M1',2,0,4,2),('M2',2,0,4,2)],[('M2',4,0,6,2)]])))==1
old_db=read_def(old/'routed.def')
legacy=measure_paths((old/'routed.def').read_text(),set(old_db['nets']),track_grid(old_db['physical']['TRACKS']))
assert legacy['off_track_by_layer_axis']
print(json.dumps(dict(passed=True,trial='offline only; no iEDA execution',
  ledger_positive='archived 308-net upstream one-round control', missed_module_rejected=True,duplicate_log_rejected=True,
  wrong_net_count_rejected=True,archive_sha256=sha(archive),s1238_nangate45_conductor_graph=graph,
  lost_conductors_detected=broken['disconnected_nets'],floating_primitives_detected=extra['floating_primitives'],
  disconnected_overlapping_cross_layer=True,closed_contact_via_connection=True,off_track_control=legacy['off_track_by_layer_axis']),indent=2))
