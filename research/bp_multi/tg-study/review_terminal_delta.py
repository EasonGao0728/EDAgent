"""Recompute terminal components after a proposed local negotiation, before accepting it."""
from collections import defaultdict
import json
from pathlib import Path
import struct
import sys
from analyze_dr_components import net_graph
from refine_terminal_tasks import read_bridges


def review(checkpoint,bridges,displaced,output):
    extras=read_bridges(bridges)
    drop=defaultdict(set)
    for line in displaced.read_text().splitlines():
        net,j=map(int,line.split());drop[net].add(j)
    failures=[]
    original=checkpoint.resolve().parents[2]/'recovery-v17-r1/terminal-components.json'
    originally_open={r['index'] for r in json.loads(original.read_bytes())['failures']}
    with checkpoint.open('rb') as src:
        def num():return struct.unpack('<i',src.read(4))[0]
        def name():return src.read(num()).decode()
        name();level=name();binding=name();n=num();src.read(8)
        indexed={}
        for i in range(n):
            assert num()==i
            netname=name();src.read(32)
            pins=[]
            for j in range(num()):
                assert num()==j
                pin=name();x,y,l,_,_=struct.unpack('<5i',src.read(20));pins.append((pin,(x,y,l)))
            if i in extras or i in drop or i in originally_open:indexed[i]=(netname,pins)
        for i in range(n):
            ct=num()
            if i not in indexed:src.seek(24*ct,1);continue
            wire=[s for j,s in enumerate(struct.iter_unpack('<6i',src.read(24*ct))) if j not in drop[i]]+extras.get(i,[])
            netname,pins=indexed[i];groups=net_graph(wire,pins)
            if len(groups)>1:failures.append(dict(index=i,name=netname,groups=list(groups.values()),wires=wire))
    output.mkdir(exist_ok=True)
    row=dict(stage=level,binding=binding,nets=n,disconnected=len(failures),failures=failures)
    (output/'terminal-components.json').write_text(json.dumps(row,separators=(',',':')))
    print('modified nets',len(indexed),'still disconnected among them',len(failures),'missing connections',sum(len(r['groups'])-1 for r in failures))


if __name__=='__main__':review(*map(Path,sys.argv[1:]))
