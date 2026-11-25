"""Read native segment coordinates and count disconnected terminal groups per net."""
import argparse
from bisect import bisect_left, bisect_right
from collections import defaultdict
import json
import mmap
from pathlib import Path
import struct


def net_graph(wires, pins, return_vertices=False, edge_map=None):
    parent = {p: p for _, p in pins}
    def root(p):
        while p != parent[p]:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p
    def join(a, b):
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        parent[root(b)] = root(a)
    xs, ys = defaultdict(set), defaultdict(set)
    for _, (x, y, l) in pins:
        xs[l].add(x)
        ys[l].add(y)
    for x, y, l, a, b, m in wires:
        for k in range(min(l, m), max(l, m)+1):
            xs[k].update((x, a))
            ys[k].update((y, b))
    xs = {k: sorted(v) for k, v in xs.items()}
    ys = {k: sorted(v) for k, v in ys.items()}
    for idx,(x, y, l, a, b, m) in enumerate(wires):
        start = (x, y, l)
        points=[]
        if l != m:
            assert (x,y)==(a,b)
            points=[(x,y,k) for k in range(min(l,m), max(l,m)+1)]
        elif x != a:
            assert y == b
            v = xs[l]
            points=[(t,y,l) for t in v[bisect_left(v,min(x,a)):bisect_right(v,max(x,a))]]
        else:
            v = ys[l]
            points=[(x,t,l) for t in v[bisect_left(v,min(y,b)):bisect_right(v,max(y,b))]]
        for p in points:join(start,p)
        if edge_map is not None:
            for u,v in zip(points,points[1:]):edge_map[(u,v)].append(idx)
    groups = defaultdict(list)
    for name, p in pins: groups[root(p)].append((name,p))
    return (groups, {p:root(p) for p in parent}) if return_vertices else groups


def analyze(path, evidence, focus=None):
    with open(path,'rb') as file, mmap.mmap(file.fileno(),0,access=mmap.ACCESS_READ) as data:
        def ints(n=1): return struct.unpack('<'+'i'*n,data.read(4*n))
        def string(): return data.read(ints()[0]).decode()
        assert string()=='ieda-route-state-v1'
        stage, binding = string(), string()
        n, _, _ = ints(3)
        metas=[]
        for i in range(n):
            assert ints()[0]==i
            name=string()
            data.read(32)
            pins=[]
            for j in range(ints()[0]):
                assert ints()[0]==j
                pin=string()
                x,y,l,_,_=ints(5)
                pins.append((pin,(x,y,l)))
            metas.append((name,pins))
        failures=[]
        for i,(name,pins) in enumerate(metas):
            wires=list(struct.iter_unpack('<6i',data.read(24*ints()[0])))
            if focus is not None and i not in focus:
                continue
            groups=net_graph(wires,pins)
            if focus is not None or len(groups)>1:
                failures.append(dict(index=i,name=name,groups=list(groups.values()),wires=wires))
        result=dict(stage=stage,binding=binding,nets=n,disconnected=len(failures),failures=failures)
        evidence.write_text(json.dumps(result,separators=(',',':')))
        print({k:v for k,v in result.items() if k!='failures'},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('checkpoint',type=Path)
    parser.add_argument('result',type=Path)
    parser.add_argument('--focus',type=Path)
    args=parser.parse_args()
    focus=None if args.focus is None else {row['index'] for row in json.loads(args.focus.read_text())['failures']}
    analyze(args.checkpoint,args.result,focus)
