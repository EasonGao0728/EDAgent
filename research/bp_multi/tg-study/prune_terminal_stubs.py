"""Remove only whole terminal-free stubs in residual search windows, proving pin connectivity."""
from collections import defaultdict,deque
from pathlib import Path
import json
import struct
import shutil
import sys
from analyze_dr_components import net_graph
from bind_terminal_eco import digest,PARENT


def prune(folder,prior,output):
    windows=set()
    tile=16000
    with (folder/'last39.txt').open() as f:
        for _ in range(29):next(f)
        for row in f:
            n,x,y,l,a,b,m,u,v=map(int,row.split())
            for _ in range(u+v):next(f)
            for i in range(min(x,a)//tile-2,max(x,a)//tile+3):
                for j in range(min(y,b)//tile-2,max(y,b)//tile+3):windows.add((i,j))
    failures={row['index'] for row in json.loads((prior/'terminal-components.json').read_bytes())['failures']}
    parent=prior/'DR-batch.bin';assert digest(parent)==PARENT
    output.mkdir(exist_ok=True)
    result=output/'pruned.bin'
    mods={}
    with parent.open('rb') as src,result.open('xb') as out:
        def num():return struct.unpack('<i',src.read(4))[0]
        def name():return src.read(num())
        name();name();name()
        n=num();src.read(8);all_pins=[]
        for i in range(n):
            assert num()==i
            name();src.read(32)
            pins=[]
            for j in range(num()):
                assert num()==j
                name();x,y,l,_,_=struct.unpack('<5i',src.read(20));pins.append((j,(x,y,l)))
            all_pins.append(pins)
        pos=src.tell();src.seek(0);out.write(src.read(pos))
        for i,pins in enumerate(all_pins):
            ct=num();data=src.read(24*ct);wires=list(struct.iter_unpack('<6i',data))
            local={j for j,(x,y,l,a,b,m) in enumerate(wires) if (x//tile,y//tile) in windows and (a//tile,b//tile) in windows}
            removed=[]
            if local and i not in failures and ct>1:
                edges=defaultdict(list)
                groups,labels=net_graph(wires,pins,True,edges)
                assert len(groups)==1
                neighbors=defaultdict(set)
                for u,v in edges:neighbors[u].add(v);neighbors[v].add(u)
                anchors={p for _,p in pins}
                leaves=deque(v for v,adj in neighbors.items() if len(adj)<=1 and v not in anchors)
                while leaves:
                    v=leaves.pop()
                    for u in list(neighbors[v]):
                        neighbors[u].remove(v)
                        if len(neighbors[u])==1 and u not in anchors:leaves.append(u)
                    neighbors[v].clear()
                keep=set()
                for (u,v),indices in edges.items():
                    if labels[u] in groups and v in neighbors[u]:keep.update(indices)
                removed=sorted(local-keep)
                if removed:
                    drop=set(removed)
                    remaining=[s for j,s in enumerate(wires) if j not in drop]
                    assert len(net_graph(remaining,pins))==1
                    mods[i]=removed
                    data=b''.join(struct.pack('<6i',*s) for s in remaining)
            out.write(struct.pack('<i',ct-len(removed)));out.write(data)
        shutil.copyfileobj(src,out,1<<20)
    (output/'removed-stubs.json').write_text(json.dumps(mods,separators=(',',':')))
    proof=dict(original=PARENT,derived=digest(result),indexed_deletions=digest(output/'removed-stubs.json'),
               touched_nets=len(mods),total_removed=sum(map(len,mods.values())),scope='terminal-free dead-end or floating wires in residual windows')
    (output/'stub-proof.json').write_text(json.dumps(proof,indent=2))
    print(proof)


if __name__=='__main__':prune(*map(Path,sys.argv[1:]))
