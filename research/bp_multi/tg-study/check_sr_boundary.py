"""Inspect every saved global guide and access point against native GCells and DEF tracks."""
from bisect import bisect_left
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import struct
from resume_space import BINDING, FAMILY, sha

w=FAMILY/'recovery-v12'
path=w/'SR.bin'
assert sha(path)==json.loads((w/'receipt.json').read_bytes())['states']['SR']
log=(w/'result/rt/rt.log').read_text(errors='replace')
boundaries=[[],[]]
axis=None
tracks={}
gcell=False
for line in log.splitlines():
    if m:=re.search(r'EDA_DEF_TRACK layer=metal(\d+) axis=([XY]) start=(\d+) count=(\d+) pitch=(\d+)',line):
        layer=int(m[1])-1
        tracks[layer,'XY'.index(m[2])]=range(int(m[3]),int(m[3])+int(m[4])*int(m[5]),int(m[5]))
    if 'Info printDatabase]' not in line:continue
    if re.search(r'\]   gcell_axis$',line):gcell=True
    elif re.search(r'\]   \S',line):gcell=False
    if not gcell:continue
    if m:=re.search(r'\] +([xy])_grid_list$',line):axis='xy'.index(m[1])
    elif axis is not None and (m:=re.search(r'start:(\d+) step_length:(\d+) step_num:(\d+) end:(\d+)',line)):
        start,step,n,end=map(int,m.groups())
        if not boundaries[axis]:boundaries[axis].append(start)
        assert boundaries[axis][-1]==start and start+n*step==end
        boundaries[axis].extend(range(start+step,end+step,step))
    elif axis is not None:axis=None
assert [len(a)-1 for a in boundaries]==[823,827]
valid={}
for (l,d),grid in tracks.items():
    edges=boundaries[d]
    for k,(a,b) in enumerate(zip(edges,edges[1:])):
        i=bisect_left(grid,a)
        valid[l,d,k]= i<len(grid) and grid[i]<=b


def check():
    counts=Counter()
    samples=defaultdict(list)
    offenders=set()
    pins=[]
    with path.open('rb') as f:
        def ints(n):return struct.unpack('<'+'i'*n,f.read(4*n))
        def name():return f.read(ints(1)[0]).decode()
        assert name()=='ieda-route-state-v1' and name()=='SR' and name()==BINDING
        n,x,y=ints(3);assert (x,y)==(823,827)
        names=[]
        for i in range(n):
            assert ints(1)==(i,)
            net=name();names.append(net);ints(8)
            for j in range(ints(1)[0]):
                assert ints(1)==(j,)
                pin=name();rx,ry,l,gx,gy=ints(5)
                if not valid[l,0,gx] or not valid[l,1,gy]:pins.append([net,pin,rx,ry,l,gx,gy])
        for net in names:
            size=ints(1)[0]
            f.seek(24*size,1)
        for net in names:
            size=ints(1)[0]
            for a,b,l,c,d,h in struct.iter_unpack('<6i',f.read(24*size)):
                counts['segments']+=1
                invalid=[(g,j,i) for g,j,i in [(l,0,a),(l,1,b),(h,0,c),(h,1,d)] if not valid[g,j,i]]
                if not invalid:continue
                offenders.add(net)
                kind='via' if l!=h else 'horizontal' if b==d else 'vertical'
                counts[kind]+=1
                for g,j,i in set(invalid):
                    label=f'metal{g+1} {("X","Y")[j]} GCell {i}'
                    counts[label]+=1
                example=[net,[a,b,l],[c,d,h],invalid]
                if len(samples[kind])<8:samples[kind].append(example)
                if net=='ib2d_bit_1391':samples[net].append(example)
    anchors=[]
    exceptions=[]
    for net,pin,rx,ry,l,gx,gy in pins:
        xgrid,ygrid=tracks[l,0],tracks[l,1]
        x=max(xgrid[0],min(rx,xgrid[-1]))
        y=max(ygrid[0],min(ry,ygrid[-1]))
        if (x!=rx)+(y!=ry)!=1 or x not in xgrid or y not in ygrid or l not in (4,5) or (x!=rx)!=(l==4):
            exceptions.append([net,pin,rx,ry,l,x,y])
        else:anchors.append([net,pin,l,rx,ry,x,y])
    return dict(checkpoint=sha(path),affected_nets=len(offenders),affected_access_points=len(pins),
                affected_pin_nets=len({p[0] for p in pins}),same_guide_pin_nets=offenders=={p[0] for p in pins},
                straight_anchors=len(anchors),anchor_exceptions=len(exceptions),exception_examples=exceptions[:8],
                anchors=anchors,
                affected_pin_examples=pins[:10],counts=dict(counts),examples=dict(samples),
                bounds={f'metal{l+1}/{"XY"[j]}':[v[0],v[-1]] for (l,j),v in tracks.items()})


if __name__=='__main__':
    report=check()
    (w/'sr-guide-boundary.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ('affected_nets','affected_access_points','counts','straight_anchors','exception_examples','same_guide_pin_nets')}))
