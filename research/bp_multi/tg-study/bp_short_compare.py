"""Reconstruct each checkpoint's native terminal trees and retain approved terminal access."""
from collections import Counter
from pathlib import Path
import struct,subprocess
from bp_short_study import WORK,FAMILY,ORIGINAL,VIA,ROUTE,entries,read,save,keys,native_drc
from analyze_dr_components import net_graph

def export_forest(checkpoint,folder):
    wanted=set(read(WORK/'projection.json')['changed_nets'])
    folder.mkdir(exist_ok=True)
    with checkpoint.open('rb') as f, (folder/'trees.in').open('w') as inp:
        def n():return struct.unpack('<i',f.read(4))[0]
        def word():return f.read(n()).decode()
        word();word();word();size=n();f.read(8)
        nets=[]
        for i in range(size):
            assert n()==i;name=word();f.read(32);pins=[]
            for j in range(n()):
                assert j==n();word();pin=struct.unpack('<5i',f.read(20))[:3];pins.append((j,pin))
            nets.append((name,pins))
        for name,pins in nets:
            wires=f.read(24*n())
            if name not in wanted:continue
            wires=list(struct.iter_unpack('<6i',wires))
            groups=net_graph(wires,pins)
            print(name,len(wires),len(groups),file=inp)
            for w in wires:print(*w,file=inp)
            for g in groups.values():
                print(len(g),file=inp)
                for _,xyz in g:print(*xyz,file=inp)
    with (folder/'trees.in').open() as inp,(folder/'trees.out').open('w') as out:
        subprocess.run([WORK/'forest'],stdin=inp,stdout=out,check=True)
def wirekey(x,y,l,a,b,m):
    return tuple(sorted(((x,y,l),(a,b,m))))
def parsed_trees(folder):
    nets={}
    with (folder/'trees.out').open() as f:
        for name in f:
            wires=Counter();nets[name.strip()]=wires
            for line in f:
                if line=='END\n':break
                x,y,l,a,b,m=map(int,line.split())
                if l==m:wires[wirekey(x,y,l,a,b,m)]+=1
                else:
                    for z in range(min(l,m),max(l,m)):wires[wirekey(x,y,z,x,y,z+1)]+=1
    return nets
def key_of(path):
    l=int(path[1][5:])-1;x=int(path[2]);y=int(path[3])
    if path[6]:
        z=VIA.index(path[6]);return wirekey(x,y,z,x,y,z+1)
    return wirekey(x,y,l,x if path[4]=='*' else int(path[4]),y if path[5]=='*' else int(path[5]),l)
def record(key):
    (x,y,l),(a,b,m)=key
    return f'metal{l+1} ( {x} {y} ) ( {a} {b} )' if l==m else f'metal{m+1} ( {x} {y} ) {VIA[l]}'
def run():
    pre=WORK/'forest-pre';post=WORK/'forest-post'
    export_forest(FAMILY/'recovery-v17-r1/DR-batch.bin',pre)
    export_forest(FAMILY/'terminal-eco/native-probe/terminal-native.bin',post)
    prior=parsed_trees(pre);after=parsed_trees(post)
    text=ORIGINAL.read_text();start=0;stats=Counter();nonmatching=[];changes=[]
    with (pre/'input.def').open('w') as f,(post/'input.def').open('w') as c:
        for m in entries(text):
            name=m[1]
            if name not in prior:continue
            row=m[0];actual=Counter(key_of(r) for r in ROUTE.finditer(row))
            assert sum(actual.values())==row.count('NEW')+1
            extra=actual-after[name];missing=after[name]-actual
            stats['actual_only']+=sum(extra.values());stats['forest_only']+=sum(missing.values())
            if missing or extra:nonmatching.append([name,sum(extra.values()),sum(missing.values())])
            # Explicitly compare the native-forest projection (without even terminal-access additions)
            # against production. Coordinate-specific additions from the DEF are copied to both arms.
            for out,tree in [(f,prior[name]),(c,after[name])]:
                net=tree+extra
                paths=[record(k) for k in net.elements()]
                out.write(text[start:m.start()]+row.partition('+ ROUTED')[0]+('+ ROUTED  '+'\n    NEW  '.join(paths) if paths else '')+' ;')
            if prior[name]!=after[name]:changes.append(name)
            start=m.end()
        f.write(text[start:]);c.write(text[start:])
    save(WORK/'forest-projection.json',dict(detail=nonmatching,changed_after_native_tree=changes,stats=stats))
    native_drc(pre);native_drc(post)
    baseline=keys(pre/'keys.gz');positive=keys(post/'keys.gz');actual=keys(WORK/'production.keys.gz')
    d={}
    for rule in ('metal_short','ALL'):
        choose=lambda s:s if rule=='ALL' else {x for x in s if x.startswith(rule+'|')}
        a,b,c=map(choose,(baseline,positive,actual))
        d[rule]=dict(before=len(a),post_control=len(b),production=len(c),common=len(a&c),added=len(c-a),removed=len(a-c),
           control_only=len(b-c),production_only=len(c-b),confirmed_shared=len(a&b&c),confirmed_added=len((c&b)-a))
    save(WORK/'forest-attribution.json',d)
if __name__=='__main__':run()
