"""Keep the unaffected parts of a displaced original wire, using the native wire/via footprint."""
from collections import defaultdict
import struct
from pathlib import Path
import sys
from refine_terminal_tasks import read_bridges


def preserve(folder,delta,paths,output):
    removed={tuple(map(int,line.split())) for line in delta.read_text().splitlines()}
    info=(folder/'tasks.txt').read_text().splitlines()[:29]
    width=list(map(int,info[13].split()))
    vias=[list(map(int,row.split())) for row in info[14:]]
    by_layer=defaultdict(list)
    for net,wires in read_bridges(paths).items():
        for x,y,l,a,b,m in wires:
            if l==m:
                h=width[l]//2
                by_layer[l].append((net,min(x,a)-h,min(y,b)-h,max(x,a)+h,max(y,b)+h))
            else:
                z=min(l,m)
                for j,k in enumerate((z,z+1)):
                    u,v,s,t=vias[3*z+j]
                    by_layer[k].append((net,x+u,y+v,x+s,y+t))
    original={}
    with (folder/'geometry.bin').open('rb') as g,(folder/'geometry-sources.bin').open('rb') as ids:
        while raw:=g.read(24*32768):
            for (net,l,x,y,a,b),(seg,) in zip(struct.iter_unpack('<6i',raw),struct.iter_unpack('<i',ids.read(len(raw)//6))):
                if (net,seg) in removed:
                    original[(net,seg)]=(l,x,y,a,b)
    assert original.keys()==removed
    with output.open('w') as dest:
        for (net,seg),(l,x,y,a,b) in sorted(original.items()):
            h=width[l]//2
            axis=int((b-y)>(a-x))
            start=(x,y)[axis]+h;end=(a,b)[axis]-h
            fixed=(x,y)[1-axis]+h
            if end<=start:continue
            cut=[]
            for owner,u,v,s,t in by_layer[l]:
                if owner==net or u>a or x>s or v>b or y>t:continue
                cut.append((max(start,(u,v)[axis]-h-800),min(end,(s,t)[axis]+h+800)))
            def write(lo,hi):
                if hi-lo<width[l]:return
                a1=(fixed,lo,l) if axis else (lo,fixed,l)
                b1=(fixed,hi,l) if axis else (hi,fixed,l)
                print(net,*a1,*b1,2,file=dest)
            cursor=start
            for lo,hi in sorted(cut):
                if lo>cursor:write(cursor,lo)
                cursor=max(cursor,hi)
            if end>cursor:write(cursor,end)
    print('displaced source segments',len(removed),'preserved stems',len(output.read_text().splitlines()))


if __name__=='__main__':preserve(*map(Path,sys.argv[1:]))
