"""Select a one-net, same-track-grid detour using the actual markers and conductor geometry."""
from collections import defaultdict,Counter
import heapq
import re
from bp_short_study import *
from def_conductors import analyze_net
def intersect(a,b):
    return min(a[2],b[2])>=max(a[0],b[0]) and min(a[3],b[3])>=max(a[1],b[1])
def intersection(a,b):
    return max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])
def parse_path(r):
    x,y=int(r[2]),int(r[3]);return r[1],x,y,x if r[4] in ('*',None) else int(r[4]),y if r[5] in ('*',None) else int(r[5]),r[6]
def wire_box(x,y,a,b,width):
    h=width//2;return min(x,a)-h,min(y,b)-h,max(x,a)+h,max(y,b)+h
def shape_list(data,lib):
    layer,x,y,a,b,via=data
    if via:
        for l,i,j,k,h in lib.vias[via]:yield l,(x+i,y+j,x+k,y+h),'via'
    else:yield layer,wire_box(x,y,a,b,lib.width[layer]),'wire'
def library():
    ref=REFERENCE/'data'
    return PhysicalLibrary(ref/'input2.lef',[ref/f'input{i}.lef' for i in range(3,10)],2000)
def key_data(k):
    rule,kind,idx,l,coords,req,nets=k.split('|')
    return l,tuple(map(int,coords.split(','))),nets.rstrip(',').split(',')
def get_scan():
    text=ORIGINAL.read_text();lib=library()
    d=read(WORK/'diagnosis.json');tile0=d['tiles'][0]['bounds_um'];region=tuple(i*2000 for i in tile0)
    roi=(region[0]-16000,region[1]-16000,region[2]+16000,region[3]+16000)
    allkeys=keys(WORK/'production.keys.gz','metal_short')
    sample=heapq.nsmallest(768,allkeys,key=lambda k:hashlib.sha256(k.encode()).digest())
    named={n for k in sample for n in key_data(k)[2]}
    sampled=defaultdict(list);hit=defaultdict(list);grid=defaultdict(list);segments=[]
    for k in allkeys:
        l,box,names=key_data(k)
        if tile(box)==tile(region):
            for n in names:hit[n,l].append((k,box))
    def cells(box):
        for i in range(box[0]//4000,box[2]//4000+1):
            for j in range(box[1]//4000,box[3]//4000+1):yield i,j
    for entry in entries(text):
        name=entry[1]
        for ix,r in enumerate(ROUTE.finditer(entry[0])):
            data=parse_path(r);l,x,y,a,b,via=data
            if name not in named and not intersect(wire_box(x,y,a,b,600),roi):continue
            for sl,box,kind in shape_list(data,lib):
                if name in named:sampled[name,sl].append((box,kind))
                if not intersect(box,roi):continue
                for i,j in cells(intersection(roi,box)):grid[sl,i,j].append((name,box,kind))
                if via or sl not in ('metal4','metal5','metal6') or not intersect(box,region):continue
                if max(abs(x-a),abs(y-b))<2800:continue
                overlaps=[(k,bx) for k,bx in hit.get((name,sl),()) if intersect(box,bx)]
                if len(overlaps)>=3:segments.append((len(overlaps),name,ix,data,overlaps))
    classes=Counter();example={}
    for k in sample:
        l,bx,(n1,n2)=key_data(k)
        s1=[(b,t) for b,t in sampled[n1,l] if intersect(b,bx)]
        s2=[(b,t) for b,t in sampled[n2,l] if intersect(b,bx)]
        types=set()
        for a,t in s1:
            for b,u in s2:
                if intersect(intersection(a,bx),b):types.add('/'.join(sorted((t,u))))
        label='+'.join(sorted(types)) if types else ('obs_marker' if 'obs' in (n1,n2) else 'unresolved')
        classes[label]+=1;example.setdefault(label,k)
    save(WORK/'geometry-sample.json',dict(n=len(sample),method='lowest SHA-256 of canonical keys; DEF wires and LEF via metal enclosure intersections within the actual native bounding box',classes=classes,examples=example))
    def contacts(l,box,name):
        # One width of clearance is a ranking proxy. Acceptance uses the native all-rule deck.
        halo=lib.width[l];q=(box[0]-halo,box[1]-halo,box[2]+halo,box[3]+halo)
        return {(n,l,b) for i,j in cells(q) for n,b,t in grid[l,i,j] if n!=name and intersect(b,q)}
    ranked=[]
    print('short-bearing segments',len(segments),'largest',max([i[0] for i in segments],default=0),flush=True)
    for _,name,ix,data,overlaps in sorted(segments,key=lambda v:-v[0])[:700]:
        l,x,y,a,b,_=data;horizontal=y==b
        center=y if horizontal else x
        varying=0 if horizontal else 1
        low,high=sorted((x,a) if horizontal else (y,b))
        low=max(low+1120,region[varying]);high=min(high-1120,region[varying+2])
        phase=4670 if horizontal else 11340
        snap=lambda z:phase+round((z-phase)/560)*560
        layer=int(l[5:]);adj=5 if layer in (4,6) else 4;al=f'metal{adj}'
        via=VIA[min(layer,adj)-1]
        for start in range(snap(low)+560,snap(high)-2239,3920):
            end=min(start+22400,snap(high)-560)
            if end-start<2240:continue
            point=lambda axis,fix:(axis,fix) if horizontal else (fix,axis)
            p=point(start,center);q=point(end,center)
            box=wire_box(*p,*q,lib.width[l])
            covered=[k for k,bx in overlaps if intersect(bx,box) and start+300 < (bx[varying]+bx[varying+2])/2 < end-300]
            if len(covered)<3:continue
            choices=[]
            for z in (4,5,6):
                if z==layer:continue
                alt=f'metal{z}'
                via_layers=range(min(layer,z),max(layer,z))
                lifts=[(f'metal{i+1}',*p,*p,VIA[i-1]) for i in via_layers]
                drops=[(f'metal{i+1}',*q,*q,VIA[i-1]) for i in via_layers]
                choices.append(lifts+[(alt,*p,*q,None)]+drops)
            for off in (-20,-12,-8,-5,-3,-2,-1,1,2,3,5,8,12,20):
                mid=center+off*560
                u=point(start,mid);v=point(end,mid)
                choices.append([(l,*p,*p,via),(al,*p,*u,None),(l,*u,*u,via),(l,*u,*v,None),
                            (l,*v,*v,via),(al,*v,*q,None),(l,*q,*q,via)])
            for candidates in choices:
                potential=set()
                for path in candidates:
                    for sl,bb,typ in shape_list(path,lib):potential.update(contacts(sl,bb,name))
                score=len(covered)-len({(n,sl) for n,sl,_ in potential})
                if score<=0:continue
                paths=[(l,x,y,*p,None),*candidates,(l,*q,a,b,None)] if (x if horizontal else y)<(a if horizontal else b) else [(l,a,b,*p,None),*candidates,(l,*q,x,y,None)]
                ranked.append((score,len(covered),-len(potential),name,ix,paths,covered))
    ranked.sort(key=lambda z:(-z[0],-z[1],z[3],z[4]))
    print('net detours with estimated gain',len(ranked),flush=True)
    if not ranked:raise ValueError('No feasible marker-guided detour')
    db=read_def(ORIGINAL);netrows={m[1]:m for m in entries(text) if m[1] in {v[3] for v in ranked[:100]}}
    seen=set()
    for score,coverage,neg_contacts,name,ix,paths,covered in ranked[:100]:
        m=netrows[name];row=m[0];r=list(ROUTE.finditer(row))[ix]
        def fmt(path):
            l,x,y,a,b,via=path
            return f'{l} ( {x} {y} ) '+(via if via else f'( {a} {b} )')
        lead='+ ROUTED  ' if r[0].startswith('+') else 'NEW  '
        replacement=lead+'\n    NEW  '.join(map(fmt,paths))
        newrow=row[:r.start()]+replacement+row[r.end():]
        ref=digest_text(newrow)
        if ref in seen:continue
        seen.add(ref)
        ok,floating,_=analyze_net(newrow.rstrip(';').strip(),db,lib,db['nets'][name])
        if not ok or floating:continue
        item=dict(name=name,ordinal=ix,original=r[0],replacement=replacement,targeted_keys=covered,
                  parent=HASH,region_um=tile0,native_layer=paths[0][0],estimated_foreign_contacts=-neg_contacts,
                  ranked_score=score,net_terminal_count=len(db['nets'][name]),one_net_prefilter_connected=True)
        save(WORK/'proposal.json',item);return
    raise ValueError('No candidate preserved local pin connectivity')
def digest_text(s):return hashlib.sha256(s.encode()).hexdigest()
def trial():
    item=read(WORK/'proposal.json')
    folder=WORK/'trial';folder.mkdir(exist_ok=True)
    if digest(ORIGINAL)!=item['parent']:raise ValueError('Wrong parent DEF')
    text=ORIGINAL.read_text();m=next(m for m in entries(text) if m[1]==item['name']);row=m[0]
    r=list(ROUTE.finditer(row))[item['ordinal']];assert r[0]==item['original']
    candidate=text[:m.start()+r.start()]+item['replacement']+text[m.start()+r.end():]
    path=folder/'input.def';path.write_text(candidate)
    native_drc(folder)
    db=read_def(path);expected={n:p for n,p in db['nets'].items() if len(p)>=2}
    graph=independent_graph(candidate,db,expected,library())
    before=keys(WORK/'production.keys.gz');after=keys(folder/'keys.gz')
    missing=before-after;new=after-before
    removed_type=Counter(k.split('|')[0] for k in missing);added_type=Counter(k.split('|')[0] for k in new)
    target=set(item['targeted_keys'])
    region=tuple(i*2000 for i in item['region_um'])
    def inside(k):return tile(key_data(k)[1])==tile(region)
    old=Counter(k.split('|')[0] for k in before);fresh=Counter(k.split('|')[0] for k in after)
    accepted=(graph['passed'] and graph['net_count']==78493 and graph['pins']==270267 and not graph['disconnected_nets'] and not graph['floating_primitives']
              and len(after)<len(before) and fresh['metal_short']<old['metal_short'] and bool(target&missing) and sum(map(inside,after))<sum(map(inside,before)))
    result=dict(status='accepted' if accepted else 'rejected',parent=HASH,candidate_sha256=digest(path),whole_chip_graph=graph,
                before=old,after=fresh,removed=removed_type,added=added_type,hotspot_before=sum(map(inside,before)),hotspot_after=sum(map(inside,after)),
                hotspot_short_before=sum(inside(k) for k in before if k.startswith('metal_short|')),hotspot_short_after=sum(inside(k) for k in after if k.startswith('metal_short|')),
                target_removed=len(target&missing),target_count=len(target),subset_net=item['name'],total_before=len(before),total_after=len(after))
    assert digest(ORIGINAL)==HASH
    save(WORK/'trial-result.json',result)
