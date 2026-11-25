"""Qualify straight boundary IO leads and retain their original terminal coordinates."""
from bisect import bisect_right
import json
from pathlib import Path
import sys
from check_sr_boundary import boundaries, tracks, valid
from resume_space import FAMILY, SOURCE, setup, sha
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'bp_multi_official'))
from verify_route_v7 import PhysicalLibrary, read_def


def main():
    work=FAMILY/'recovery-v12'
    study=json.loads((work/'sr-guide-boundary.json').read_bytes())
    assert study['same_guide_pin_nets'] and study['anchor_exceptions']==0 and len(study['anchors'])==1431
    grid_bounds=[]
    for axis in (0,1):
        available=[[i for i in range(len(boundaries[axis])-1) if valid[l,axis,i]] for l in range(1,6)]
        assert all(v==available[0] for v in available)
        grid_bounds.extend([min(available[0]),max(available[0])])
        assert len(available[0])==grid_bounds[-1]-grid_bounds[-2]+1
    db=read_def(SOURCE)
    ref=setup()/'data'
    lib=PhysicalLibrary(ref/'input2.lef',[ref/f'input{i}.lef' for i in range(3,10)],db['units'])
    assert not db['physical']['SPECIALNETS'] and not db['physical']['BLOCKAGES']
    io={k:lib.pin(db,'PIN',k) for k in db['pins']}
    output=[' '.join(map(str,grid_bounds))]
    boxes={}
    # Doubled DBU. The lead spans the full wire width and square end caps.
    def gap(a,b):
        return max(b[0]-a[2],a[0]-b[2],0),max(b[1]-a[3],a[1]-b[3],0)
    collisions=[]
    for net,pin,l,x,y,ax,ay in study['anchors']:
        assert ('PIN',pin) in db['nets'][net] and not any(ch.isspace() for ch in net+pin)
        layer=f'metal{l+1}';w=lib.width[layer]
        assert any(ly==layer and a<=2*x<=c and b<=2*y<=d for ly,a,b,c,d in io[pin])
        assert ax in tracks[l,0] and ay in tracks[l,1] and ((x!=ax) != (y!=ay))
        assert (l==4 and y==ay) or (l==5 and x==ax)
        for i,v in enumerate((ax,ay)):
            idx=bisect_right(boundaries[i],v)-1
            original=bisect_right(boundaries[i],(x,y)[i])-1
            assert idx==max(grid_bounds[2*i],min(original,grid_bounds[2*i+1]))
        rect=(2*min(x,ax)-w,2*min(y,ay)-w,2*max(x,ax)+w,2*max(y,ay)+w)
        for other,geos in io.items():
            if other==pin:continue
            for ly,*r in geos:
                if ly==layer and gap(rect,r)==(0,0):collisions.append([net,other,'pin'])
        for nn,r in boxes.setdefault(layer,[]):
            if nn!=net and gap(rect,r)==(0,0):collisions.append([net,nn,'lead'])
        boxes[layer].append((net,rect))
        output.append(' '.join(map(str,(net,pin,l,x,y,ax,ay))))
    assert not collisions,collisions[:8]
    path=work/'boundary-leads.tsv'
    payload='\n'.join(output)+'\n'
    if path.exists():assert path.read_text()==payload
    else:path.write_text(payload)
    record=dict(source=sha(SOURCE),sr=study['checkpoint'],table=sha(path),ports=len(output)-1,
                zero_length=0,cross_net_lead_and_io_overlaps=len(collisions),legal_gcell_bounds=grid_bounds,
                scope='IO metal and proposed lead hard overlaps; final full-chip native DRC required')
    (work/'boundary-leads.json').write_text(json.dumps(record,indent=2))
    print(record)


if __name__=='__main__':main()
