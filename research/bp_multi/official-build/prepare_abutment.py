"""Stage a native PA candidate with explicit, checkpoint-bound terminal escape paths."""
import difflib
import hashlib
import json
from pathlib import Path

root = Path('/srv/edagent/bp-multi-official-build-v1')
runs = root.parent/'main-agent-remote-v1/runs'
evidence = runs/'bp-multi-sram-ce-escape-drc-v1'
batch = json.loads((evidence/'batch-abutment-summary.json').read_bytes())
assert batch['totals']=={'own_pin_aperture_boundary_marker':358}
geometry=json.loads((evidence/'sram-eligibility.json').read_bytes())
assert batch['source']==geometry['checkpoint']
rows=[]
for row in geometry['pins']:
    x,y=row['P']
    a,_=row['A']
    _,b=row['B']
    rows.append(f"{row['net']} gen_139835_:{row['pin']} {x} {y} {a} {b}\n")
assert len(rows)==len(set(rows))==179
(evidence/'screened-escapes.tsv').write_text(''.join(rows))
rel='src/operation/iRT/source/module/pin_accessor/PinAccessor.cpp'
src=(root/'source'/rel).read_text()
v6=json.loads((root/'frozen-ade7f7d2df62bfbe/snapshot.json').read_bytes())
assert hashlib.sha256(src.encode()).hexdigest()==v6['irt_source_delta'][rel]
s=src
def insert(anchor,text):
    global s
    assert s.count(anchor)==1,anchor
    s=s.replace(anchor,text+anchor)

insert('std::vector<LayerCoord> nativeTargets(PAPin* pin)',r'''
// A pin escape file describes actual wires, not virtual extensions of LEF pins.
// The runner binds a frozen, DRC-measured list for this checkpoint only.
struct Escape { int x, y, a, b; std::string net; };
const Escape* escapeFor(PAPin* pin)
{
  static const auto escapes = [] {
    std::map<std::string,Escape> result;
    if (auto path = std::getenv("IEDA_RT_PA_ESCAPE_FILE")) {
      std::ifstream stream(path);
      std::string name, net;
      Escape e;
      while (stream >> net >> name >> e.x >> e.y >> e.a >> e.b) {
        e.net = net;
        if (!result.emplace(name,e).second) RTLOG.error(Loc::current(),"Duplicate pin escape ",name);
      }
      if (!stream.eof() || result.empty()) RTLOG.error(Loc::current(),"Invalid pin escape file");
    }
    return result;
  }();
  auto it=escapes.find(pin->get_pin_name());
  return it==escapes.end() ? nullptr : &it->second;
}

''')
insert('  for (auto& access : pin->get_access_point_list()) {', '''  if (auto e = escapeFor(pin)) {
    return {LayerCoord(e->a,e->b,pin->get_access_point_list().at(0).get_layer_idx())};
  }
''')
insert('    std::sort(access_point_list.begin(), access_point_list.end(),', '''    if (auto e = escapeFor(pa_pin)) {
      auto& shapes = pa_pin->get_routing_shape_list();
      if (shapes.size()!=1) RTLOG.error(Loc::current(),"Pin escape shape changed");
      auto& r = shapes.front().get_real_rect();
      int l=shapes.front().get_layer_idx();
      auto& layer=RTDM.getDatabase().get_routing_layer_list().at(l);
      int w=layer.get_min_width();
      if (RTDM.getDatabase().get_net_list().at(net_pin_pair.first).get_net_name()!=e->net
          || layer.get_layer_name()!="metal3" || r.get_ll_x()!=e->x || r.getXSpan()!=w
          || r.getYSpan()!=w || r.get_ll_y()+w/2!=e->y || e->a>=e->x || e->b==e->y
          || !onPreferredTrack(LayerCoord(e->a,e->b,l))) RTLOG.error(Loc::current(),"Pin escape geometry changed: ",pa_pin->get_pin_name());
      access_point_list.clear();
      access_point_list.emplace_back(pa_pin->get_pin_idx(),LayerCoord(e->x,e->y,l));
    }
''')
s=s.replace('int32_t rank = accessRank(access_point);','int32_t rank = escapeFor(&pa_pin) ? 1 : accessRank(access_point);')
insert('  while (!isConnectedAllEnd(pa_box)) {', '''  if (auto e=escapeFor(pa_task->get_pa_pin())) {
    auto& groups=pa_task->get_pa_group_list();
    auto p=groups.at(0).get_coord_list().at(0);
    LayerCoord a(e->a,e->y,p.get_layer_idx()), b(e->a,e->b,p.get_layer_idx());
    if (groups.at(1).get_coord_list().size()!=1 || !(groups.at(1).get_coord_list().front()==b)
        || p.get_x()!=e->x || p.get_y()!=e->y) RTLOG.error(Loc::current(),"Incomplete PA escape groups");
    pa_box.get_routing_segment_list().emplace_back(p,a);
    pa_box.get_routing_segment_list().emplace_back(a,b);
    updateTaskResult(pa_box);
    resetSingleRouteTask(pa_box);
    return;
  }
''')
patch=''.join(difflib.unified_diff(src.splitlines(True),s.splitlines(True),'a/'+rel,'b/'+rel))
(root/'router-abutment.patch').write_text(patch)
