"""Extend legal attachment sites along the existing copper for remaining opens."""
from collections import defaultdict
from itertools import combinations
import json
from pathlib import Path
import sys
from analyze_dr_components import net_graph


def read_bridges(file):
    added=defaultdict(list)
    for row in file.read_text().splitlines():
        net,*segment,_grade=map(int,row.split())
        assert len(segment)==6
        added[net].append(segment)
    return added


def refine(out, parent, reserved, target, pin_access=False):
    header=(out/'tasks.txt').read_text().splitlines()[:29]
    grids=[[tuple(map(int,header[1+2*l+d].split())) for d in range(2)] for l in range(6)]
    extra=read_bridges(reserved)
    rows=json.loads((parent/'terminal-components.json').read_text())['failures']
    with target.open('w') as stream:
        print(*header,sep='\n',file=stream)
        total=0
        for row in rows:
            wires=row['wires']+extra[row['index']]
            pins=[(p,tuple(q)) for group in row['groups'] for p,q in group]
            groups,labels=net_graph(wires,pins,True)
            if len(groups)==1:continue
            parts={r:{p for p,k in labels.items() if r==k and int(not pin_access)<=p[2]<=5} for r in groups}
            links=[]
            for r,s in combinations(parts,2):
                gap,u,v=min((abs(a[0]-b[0])+abs(a[1]-b[1])+280*abs(a[2]-b[2]),a,b) for a in parts[r] for b in parts[s])
                links.append((gap,r,s,u,v))
            joined=[{r} for r in parts]
            for _,r,s,u,v in sorted(links):
                aa=next(x for x in joined if r in x);bb=next(x for x in joined if s in x)
                if aa is bb:continue
                aa.update(bb);joined.remove(bb)
                sites={k:set(parts[k]) for k in (r,s)}
                for x,y,l,a,b,m in wires:
                    k=labels.get((x,y,l))
                    if k not in sites or l!=m or not 1<=l<=5 or (x==a and y==b):continue
                    axis=int(x==a)
                    lo,hi=sorted((y,b) if axis else (x,a))
                    lo=max(lo,min(u[axis],v[axis])-80000)
                    hi=min(hi,max(u[axis],v[axis])+80000)
                    if lo>hi:continue
                    for layer in range(1,6):
                        start,count,pitch=grids[layer][axis]
                        first=max(0,(lo-start+pitch-1)//pitch)
                        for i in range(first,min(count,(hi-start)//pitch+1)):
                            c=start+i*pitch
                            sites[k].add((x,c,l) if axis else (c,y,l))
                print(row['index'],*u,*v,len(sites[r]),len(sites[s]),file=stream)
                for k in (r,s):
                    for point in sorted(sites[k]):print(*point,file=stream)
                total+=1
    print('remaining terminal connections',total)


if __name__=='__main__':
    refine(*map(Path,sys.argv[1:5]),pin_access='--pin-access' in sys.argv[5:])
