"""Build a same-input physical obstacle index and open-net tasks from a sealed DR snapshot."""
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from itertools import combinations
import json
import mmap
import re
import struct
import sys
from analyze_dr_components import net_graph
from verify_pa import SOURCE, setup, sha
from macro_agent.def_validation import read_def
from macro_agent.pin_metrics import transform
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'bp_multi_official'))
from def_conductors import PhysicalLibrary, rectangles


def prepare(prior, out, exact=False, prune=False):
    checkpoint=prior/'DR-batch.bin'
    assert sha(checkpoint)=='dea12176e6bb0a2563a91ce56782ef537cc401731fb6d5b372477fe53e5a2734'
    if prune:
        proof=json.loads((out/'stub-proof.json').read_bytes())
        assert proof['original']==sha(checkpoint) and proof['indexed_deletions']==sha(out/'removed-stubs.json')
        checkpoint=out/'pruned.bin'
        assert proof['derived']==sha(checkpoint)
    db=read_def(SOURCE)
    assert not any(db['physical'][k] for k in ('SPECIALNETS','BLOCKAGES','VIAS'))
    ref=setup()/'data'
    tech=ref/'input2.lef'
    lefs=[ref/f'input{i}.lef' for i in range(3,10)]
    lib=PhysicalLibrary(tech,lefs,db['units'])
    def to_dbu(s):return int(Decimal(s)*db['units'])
    width=[lib.width['metal'+str(i)] for i in range(1,7)]
    def layer(name):
        m=re.fullmatch(r'(metal|via)([0-9]+)',name)
        assert m,name
        return int(m[2])-1+(10 if m[1]=='via' else 0)
    via=defaultdict(dict)
    if exact:
        rtlog=(prior/'result/rt/rt.log').read_text()
        preferred={m[2] for m in re.finditer(r'Info printDatabase\] +metal([1-5]): (via\d+_\d+)',rtlog)}
        assert preferred=={'via1_4','via2_5','via3_2','via4_0','via5_0'}
    for m in re.finditer(r'^VIA (\S+)(?: DEFAULT)?\s*$(.*?)^END \1\s*$',tech.read_text(),re.S|re.M):
        k=int(re.match(r'via(\d+)_',m[1])[1])-1
        if k>=5:continue
        if exact and m[1] not in preferred:continue
        for name,x,y,a,b in rectangles(m[2],to_dbu):
            l=layer(name)
            old=via[k].get(l,(0,0,0,0))
            via[k][l]=(min(old[0],x),min(old[1],y),max(old[2],a),max(old[3],b))
    fixed={}
    for path in lefs:
        for m in re.finditer(r'^MACRO (\S+)\s*$(.*?)^END \1\s*$',path.read_text(),re.M|re.S):
            obs=re.search(r'^\s*OBS\s*$(.*?)^\s*END\s*$',m[2],re.M|re.S)
            fixed[m[1]]=rectangles(obs[1],to_dbu) if obs else []
    with (prior/'terminal-components.json').open() as f:failures=json.load(f)['failures']
    assert len(failures)==423
    out.mkdir(exist_ok=True)
    fmt=struct.Struct('<6i')
    names={}
    protected={name for name,terms in db['nets'].items() if any(
        inst=='PIN' or max(lib.cells[db['components'][inst]['master']][:2])>50000 for inst,_ in terms)}
    with (out/'geometry.bin').open('wb') as dest,(out/'geometry-sources.bin').open('wb') as origins:
        def box(net,l,x,y,a,b,segment=-1):
            dest.write(fmt.pack(net,l,x,y,a,b));origins.write(struct.pack('<i',segment))
        with checkpoint.open('rb') as raw, mmap.mmap(raw.fileno(),0,access=mmap.ACCESS_READ) as data:
            def ints(n=1):return struct.unpack('<'+'i'*n,data.read(4*n))
            def string():return data.read(ints()[0]).decode()
            header=[string() for _ in range(3)]
            n,_,_=ints(3)
            for i in range(n):
                assert ints()[0]==i
                names[string()]=i
                data.read(32)
                for _ in range(ints()[0]):
                    ints();string();data.read(20)
            locked={names[name] for name in protected if name in names}
            for i in range(n):
                for seg,(x,y,l,a,b,m) in enumerate(struct.iter_unpack('<6i',data.read(24*ints()[0]))):
                    if l==m:
                        if l>=6:continue
                        h=width[l]//2
                        box(i,l,min(x,a)-h,min(y,b)-h,max(x,a)+h,max(y,b)+h,seg if 1<=l<=5 and i not in locked else -1)
                    else:
                        for z in range(min(l,m),min(max(l,m),5)):
                            for k,(u,v,s,t) in via[z].items():box(i,k,x+u,y+v,x+s,y+t)
            for _ in range(n):data.seek(24*ints()[0],1)
            for i in range(n):
                for x,y,a,b,_,_,_,_,l in struct.iter_unpack('<9i',data.read(36*ints()[0])):box(i,l,x,y,a,b)
        terminals={(inst,pin):names.get(name,-1) for name,pins in db['nets'].items() for inst,pin in pins}
        for inst,c in db['components'].items():
            _,cx,cy,o=c['placement']
            w,h,pins=lib.cells[c['master']]
            def add(net,r):
                lay,x,y,a,b=r
                l=layer(lay)
                if 6<=l<10 or l>=15:return
                x,y=transform(x,y,w,h,o)
                a,b=transform(a,b,w,h,o)
                box(net,l,cx+min(x,a),cy+min(y,b),cx+max(x,a),cy+max(y,b))
            for r in fixed[c['master']]:add(-1,r)
            for pin,rs in pins.items():
                net=terminals.get((inst,pin),-1)
                for r in rs:add(net,r)
        for pin in db['pins']:
            for lay,x,y,a,b in lib.pin(db,'PIN',pin):
                box(terminals.get(('PIN',pin),-1),layer(lay),x//2,y//2,a//2,b//2)
    with (out/'tasks.txt').open('w') as dest:
        def emit(*args):print(*args,file=dest)
        emit(*db['die'])
        for l in range(6):
            for axis in 'XY':
                row=next(r for r in db['physical']['TRACKS'] if r.startswith(axis+' ') and r.endswith(' LAYER metal'+str(l+1)))
                fields=row.split()
                emit(int(fields[1]),int(fields[3]),int(fields[5]))
        emit(*width)
        for z in range(5):
            for k in (z,z+1,10+z):emit(*via[z][k])
        for net in failures:
            pins=[(p,tuple(coord)) for g in net['groups'] for p,coord in g]
            groups,verts=net_graph(net['wires'],pins,True)
            parts=[[v for v,r in verts.items() if r==group and 1<=v[2]<=5] for group in groups]
            assert all(parts),net['name']
            edges=[]
            for i,j in combinations(range(len(parts)),2):
                distance,u,v=min((abs(a[0]-b[0])+abs(a[1]-b[1])+280*abs(a[2]-b[2]),a,b) for a in parts[i] for b in parts[j])
                edges.append((distance,i,j,u,v))
            connected=[{i} for i in range(len(parts))]
            for _,i,j,u,v in sorted(edges):
                aa=next(a for a in connected if i in a);bb=next(a for a in connected if j in a)
                if aa is bb:continue
                aa.update(bb);connected.remove(bb)
                emit(net['index'],*u,*v,len(parts[i]),len(parts[j]))
                for idx in (i,j):
                    for point in parts[idx]:emit(*point)
    print('prepared',n,'nets,',len(failures),'disconnected,', (out/'geometry.bin').stat().st_size,'geometry bytes',flush=True)


if __name__=='__main__':
    prepare(Path(sys.argv[1]),Path(sys.argv[2]),'--native-vias' in sys.argv[3:],'--prune' in sys.argv[3:])
