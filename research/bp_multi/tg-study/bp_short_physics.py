"""Join native whole-chip short markers to named conductors, independent of route scoring."""
from collections import defaultdict,Counter
from bp_short_study import *
from bp_short_hotspot import library,key_data,parse_path,shape_list,intersect,intersection
from def_conductors import rectangles
from decimal import Decimal
from macro_agent.pin_metrics import transform
def run():
    lib=library();text=ORIGINAL.read_text();db=read_def(ORIGINAL)
    final=keys(WORK/'production.keys.gz','metal_short');pre=keys(WORK/'forest-pre/keys.gz','metal_short')
    raw=keys(WORK/'pre/keys.gz','metal_short');after_raw=keys(WORK/'control/keys.gz','metal_short')
    cross=Counter();tier=defaultdict(Counter)
    index=defaultdict(lambda:defaultdict(list));records=[]
    def bins(box):
        for x in range(int(box[0]//10000),int(box[2]//10000)+1):
            for y in range(int(box[1]//10000),int(box[3]//10000)+1):yield (x,y)
    for k in sorted(final):
        l,box,(a,b)=key_data(k);idx=len(records);records.append((k,l,box,a,b,[],[]))
        for n,side in [(a,0),(b,1)]:
            grid=index[n,l]
            for tile_id in bins(box):grid[tile_id].append((idx,side))
        label='retained' if k in pre else 'new'
        cross[label+'/'+('raw_before' if k in raw else 'absent_raw_before')+'/'+('raw_after' if k in after_raw else 'absent_raw_after')]+=1
        tier[l][label]+=1
    for k in pre-final:tier[key_data(k)[0]]['removed']+=1
    def add(name,l,box,kind):
        grid=index.get((name,l))
        if grid is None:return
        for b in bins(box):
            for idx,side in grid.get(b,[]):
                rec=records[idx];shapes=rec[5+side]
                if intersect(rec[2],box) and (box,kind) not in shapes:shapes.append((box,kind))
    for ent in entries(text):
        name=ent[1]
        for r in ROUTE.finditer(ent[0]):
            data=parse_path(r)
            for l,box,kind in shape_list(data,lib):
                if kind=='wire':kind='H' if data[2]==data[4] else 'V'
                add(name,l,box,kind)
    refs=read(REFERENCE/'manifest.json')
    masters=set(refs['expected_macro_masters'].values()) if isinstance(refs['expected_macro_masters'],dict) else set(refs['expected_macro_masters'])
    macro_names=set(refs['expected_macro_masters'])
    obs={};macro_boxes=[]
    for p in refs['cell_lefs']:
        for m in re.finditer(r'^MACRO (\S+)\s*$(.*?)^END \1\s*$',(REFERENCE/p).read_text(),re.S|re.M):
            block=re.search(r'^\s*OBS\s*$(.*?)^\s*END\s*$',m[2],re.M|re.S)
            obs[m[1]]=rectangles(block[1],lambda w:int(Decimal(w)*2000)) if block else []
    for inst,ref in db['components'].items():
        master=ref['master'];_,x,y,o=ref['placement'];w,h,_=lib.cells[master]
        if inst in macro_names or master in masters:
            width,height=(h,w) if o in ('E','W','FE','FW') else (w,h)
            macro_boxes.append([inst,x,y,x+width,y+height])
        for l,u,v,s,t in obs.get(master,()):
            if ('obs',l) not in index:continue
            u,v=transform(u,v,w,h,o);s,t=transform(s,t,w,h,o)
            add('obs',l,(x+min(u,s),y+min(v,t),x+max(u,s),y+max(v,t)),'OBS')
    assert len(macro_boxes)==26
    involved={name for name,_ in index}
    for name,pins in db['nets'].items():
        if name not in involved:continue
        for inst,pin in pins:
            for l,x,y,a,b in lib.pin(db,inst,pin):
                add(name,l,(x/2,y/2,a/2,b/2),'PIN')
    dirs={m[1]:re.search(r'\bDIRECTION (HORIZONTAL|VERTICAL)',m[2])[1] for m in re.finditer(r'^LAYER (metal\d+)\s*$(.*?)^END \1\s*$',(REFERENCE/refs['tech_lef']).read_text(),re.M|re.S)}
    assert set(rec[1] for rec in records)<=dirs.keys()
    groups=Counter();supports=Counter();per_layer=defaultdict(Counter);matrix=Counter();examples={};inside=Counter();unresolved=Counter()
    for k,l,box,a,b,left,right in records:
        cx=(box[0]+box[2])/2;cy=(box[1]+box[3])/2
        region=next((m[0] for m in macro_boxes if m[1]<=cx<m[3] and m[2]<=cy<m[4]),None)
        inside['inside_macro' if region else 'outside_macro']+=1
        ways=set();wrong=[]
        for aa,x in left:
            for bb,y in right:
                if min(intersection(aa,box)[2],bb[2])<=max(intersection(aa,box)[0],bb[0]) or min(intersection(aa,box)[3],bb[3])<=max(intersection(aa,box)[1],bb[1]):continue
                if 'OBS' in (x,y):kind='obstacle'
                elif 'PIN' in (x,y):kind='pin_metal'
                elif x in ('H','V') and y in ('H','V'):kind='perpendicular_wires' if x!=y else 'parallel_wires'
                elif 'via'==x==y:kind='two_vias'
                else:kind='wire_via'
                ways.add(kind);wrong.append(any(t in ('H','V') and t!=dirs[l][0] for t in (x,y)))
        if ways:
            for w in ways:supports[w]+=1
        label='+'.join(sorted(ways)) or 'unresolved'
        groups[label]+=1;per_layer[l][label]+=1;examples.setdefault(label,k)
        if not ways:
            boundary=any(intersect(intersection(aa,box),bb) for aa,_ in left for bb,_ in right)
            unresolved['closed_contact' if boundary else 'no_matched_pair']+=1
        matrix['all_explanations_use_wrong_way_wire' if wrong and all(wrong) else 'some_explanation_uses_wrong_way_wire' if any(wrong) else 'no_wrong_way_witness']+=1
    save(WORK/'physical-causes.json',dict(marker_count=len(final),layer_directions=dirs,inside_macro=inside,
          exclusive_geometry=groups,nonexclusive_geometry=supports,wrong_way=matrix,layer_geometry=per_layer,examples=examples,
          attribution_by_layer=tier,checkpoint_cross_tab=cross,macro_boxes_dbu=macro_boxes,unresolved_detail=unresolved))
if __name__=='__main__':run()
