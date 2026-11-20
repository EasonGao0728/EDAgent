"""Native public-iDB export, with independent read-only GDS checks."""
import hashlib,json,re,subprocess,time,uuid
from pathlib import Path
from .def_validation import read_def,lef_cells,section
ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'environments/ieda-export/runtime-manifest.json'
def ref(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def input_files():
    m=json.loads(MANIFEST.read_text());return [MANIFEST,ROOT/m['executable'],Path(__file__)]

def validate(gds,def_path,tech_lef,cell_lefs):
    import klayout.db as db
    design=read_def(def_path);layout=db.Layout();layout.read(str(gds));top=layout.cell(design['design'])
    errors=[];checked=0;io_checked=0;net_checked=0
    if top is None:errors.append('missing_design_top')
    if [c.name for c in layout.top_cells()]!=[design['design']]:errors.append('unexpected_top_cells')
    if abs(layout.dbu-1/design['units'])>1e-9:errors.append('database_unit_mismatch')
    layers=re.findall(r'^LAYER (\S+)',tech_lef.read_text(),re.M)
    layer_ids={name:layout.find_layer(i,0) for i,name in enumerate(layers)}
    zero=layout.find_layer(0,0);cells={}
    for f in cell_lefs:cells.update(lef_cells(f,design['units']))
    referenced={layout.cell(i.cell_index).name for i in top.each_inst()} if top else set()
    if top:
        die=design['die'];outline=layout.find_layer(0,2)
        box=top.bbox(outline) if outline is not None else None
        if box is None or any(abs(a-b)>1 for a,b in zip([box.left,box.bottom,box.right,box.top],die)):
            errors.append('die_outline_scale_or_location_mismatch')
    for name,value in design['components'].items():
        cell=layout.cell('Instance_'+name)
        if cell is None or cell.name not in referenced:errors.append('missing_instance:'+name);continue
        _,x,y,o=value['placement'];w,h=cells[value['master']]['size']
        if o in ('E','W','FE','FW'):w,h=h,w
        expected=db.Box(x,y,x+w,y+h)
        boxes=[s.bbox() for s in cell.shapes(zero).each()] if zero is not None else []
        if expected not in boxes:errors.append('instance_bbox_mismatch:'+name)
        checked+=1
    pins=layout.cell('PINS')
    if not pins or 'PINS' not in referenced:errors.append('missing_io_reference')
    for name,pin in design['pins'].items():
        shapes=re.findall(r'\+ LAYER (\S+) \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \)',pin)
        if not shapes:continue
        placed=re.search(r'\+ (?:PLACED|FIXED) \( (-?\d+) (-?\d+) \) (\w+)',pin)
        if not placed or placed[3] not in ('N','S','E','W'):errors.append('unsupported_io_orientation:'+name);continue
        x,y=map(int,placed.group(1,2))
        for layer,x1,y1,x2,y2 in shapes:
            def transform(a,b):
                return {'N':(a,b),'S':(-a,-b),'E':(b,-a),'W':(-b,a)}[placed[3]]
            corners=[transform(a,b) for a in (int(x1),int(x2)) for b in (int(y1),int(y2))]
            expected=db.Box(x+min(a for a,b in corners),y+min(b for a,b in corners),x+max(a for a,b in corners),y+max(b for a,b in corners))
            idx=layer_ids.get(layer)
            boxes=[s.bbox() for s in pins.shapes(idx).each()] if pins is not None and idx is not None else []
            if expected not in boxes:errors.append('io_shape_mismatch:'+name)
        io_checked+=1
    empty_nets_checked=[];single_terminal_nets_checked=[]
    net_rows={row.split()[0]:row for row in section(def_path.read_text(encoding='utf-8'),'NETS')}
    for name,terminals in design['nets'].items():
        c=layout.cell(name)
        # A preserved declaration with no electrical endpoints has no route to
        # export. Its empty cell reference is still mandatory; connected nets
        # and all routed geometry retain the existing independent checks.
        if not terminals:
            if re.search(r'\+\s*(?:ROUTED|FIXED|COVER)\b|\bNEW\s+\S+\s+\(',net_rows[name]):
                errors.append('unexpected_routing_on_empty_net:'+name)
            elif c is None or name not in referenced:
                errors.append('missing_declared_empty_net:'+name)
            elif not c.bbox().empty():
                errors.append('unexpected_geometry_on_empty_net:'+name)
            else:empty_nets_checked.append(name)
            continue
        # A single electrical endpoint does not require an interconnect. Keep
        # its named, empty hierarchy reference; still validate any explicitly
        # routed single-terminal net and every multi-terminal net below.
        if len(terminals)==1 and not re.search(r'\+\s*(?:ROUTED|FIXED|COVER)\b|\bNEW\s+\S+\s+\(',net_rows[name]):
            if c is None or name not in referenced:
                errors.append('missing_single_terminal_net:'+name)
            elif not c.bbox().empty():
                errors.append('unexpected_geometry_on_unrouted_single_terminal_net:'+name)
            else:single_terminal_nets_checked.append(name)
            continue
        if c is None or name not in referenced or c.bbox().empty():errors.append('missing_routed_net:'+name)
        else:net_checked+=1
    for row in design.get('physical',{}).get('SPECIALNETS',[]):
        name=row.split()[0];c=layout.cell(name)
        if c is None or name not in referenced or c.bbox().empty():errors.append('missing_power_net:'+name)
    # Independently reconstruct all regular routed center-line segments. Width,
    # via cuts and foundry layer mapping need separate validation; do not claim LVS.
    points_checked=0
    for row in section(def_path.read_text(),'NETS'):
        name=row.split()[0];c=layout.cell(name)
        if c is None:continue
        for match in re.finditer(r'(?:\+ ROUTED|NEW)\s+(\S+)\s+(.+?)(?=\s+NEW\s+|$)',row):
            layer,body=match.groups();idx=layer_ids.get(layer)
            if idx is None:errors.append('missing_route_layer:'+layer);continue
            body=body.split(' RECT ')[0]
            coords=re.findall(r'\(\s*(-?\d+|\*)\s+(-?\d+|\*)(?:\s+-?\d+)?\s*\)',body)
            old=None;region=db.Region(c.begin_shapes_rec(idx))
            for sx,sy in coords:
                if (sx=='*' or sy=='*') and old is None:errors.append('unsupported_initial_wildcard:'+name);break
                x=int(sx) if sx!='*' else old[0];y=int(sy) if sy!='*' else old[1]
                # A one-DBU box probes that the exported net covers the exact DEF point.
                if (db.Region(db.Box(x,y,x+1,y+1))-region).area()>0:errors.append('route_coordinate_not_covered:'+name+':'+layer)
                if old and old!=(x,y):
                    a,b=old
                    probe=db.Box(min(a,x),min(b,y),max(a,x)+1,max(b,y)+1)
                    if (db.Region(probe)-region).area()>0:errors.append('route_segment_not_covered:'+name+':'+layer)
                old=(x,y);points_checked+=1
    return {'passed':not errors,'errors':sorted(set(errors)),'producer':'public iEDA/iDB + recorded local native binary writer patch',
       'reader':'KLayout (read-only; no conversion or output rewrite)','gds':ref(gds),'source_def':ref(def_path),
       'top':design['design'],'dbu_um':layout.dbu,'instances_checked':checked,'io_checked':io_checked,
       'routed_nets_checked':net_checked,'route_points_checked':points_checked,
       'declared_empty_nets_checked':sorted(empty_nets_checked),
       'unrouted_single_terminal_nets_checked':sorted(single_terminal_nets_checked),
       'layer_mapping':{n:i for i,n in enumerate(layers)},'signoff_clean':False,
       'limitations':['LEF abstracts and routed geometry only; no transistor-level library GDS',
          'iDB layer order, not qualified foundry stream-out mapping','Center-line coverage and component/IO geometry checks; not LVS or full polygon equivalence']}

def export(work,base):
    work=Path(work);m=json.loads(MANIFEST.read_text());binary=ROOT/m['executable']
    if ref(binary)['sha256']!=m['executable_sha256']:raise ValueError('Native iDB binary changed')
    reference=base.input_files()[0]
    for _ in Path(base.manifest()['netlist']).parts:reference=reference.parent
    output=work/'result/final.gds';log=work/'logs/gds_export.log';name='aieda-gds-'+uuid.uuid4().hex[:12]
    args=base.rt.docker()+['run','--rm','--pull=never','--name',name,'--network','none','--cpus','2','--memory','4g','--pids-limit','64',
       '--mount',f'type=bind,source={reference},target=/reference,readonly','--mount',f'type=bind,source={work},target=/work',
       '--mount',f'type=bind,source={binary.parent},target=/native,readonly','--env','OMP_NUM_THREADS=2','--env','OMP_THREAD_LIMIT=2',
       m['image'],'timeout','--kill-after=5','120','/native/ieda-idb-export','/work/result/filler.def','/work/result/final.gds',
       '/reference/'+base.manifest()['tech_lef'],*['/reference/'+p for p in base.manifest()['cell_lefs']]]
    start=time.monotonic()
    with log.open('w') as out:
        try:code=subprocess.run(args,stdout=out,stderr=subprocess.STDOUT,timeout=140,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode
        except subprocess.TimeoutExpired:
            base.rt.invoke(['kill',name]);raise
    if code or 'IDB_NATIVE_EXPORT_OK' not in log.read_text(errors='replace'):raise ValueError('Native GDS export failed: '+str(log))
    check=validate(output,work/'result/filler.def',reference/base.manifest()['tech_lef'],[reference/p for p in base.manifest()['cell_lefs']])
    (work/'result/gds-validation.json').write_text(json.dumps(check,indent=2))
    if not check['passed']:raise ValueError('Native GDS validation failed: '+str(work/'result/gds-validation.json'))
    return {'artifact':str(output),'log':str(log),'seconds':round(time.monotonic()-start,3),'validation':check,'native_export_version':m}
