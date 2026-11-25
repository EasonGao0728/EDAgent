"""Measure identical-master SRAM peer contacts, track-centred fixed-via options and historical actual endpoints."""
from collections import Counter
from decimal import Decimal
from pathlib import Path
import csv
import gzip
import json
import re

from sram_escape_geometry import overlap
from sram_escape_check import *
from def_conductors import rectangles

def main():
    db=read_def(SOURCE);ref=setup()
    tech=ref/'data/input2.lef';lefs=sorted((ref/'data').glob('input[3-9].lef'))
    lib=PhysicalLibrary(tech,lefs,db['units'])
    grid=int(Decimal(re.search(r'MANUFACTURINGGRID (\S+) ;',tech.read_text())[1])*db['units'])
    master='fakeram45_32x64'
    macro=next(a[2] for lef in lefs for a in re.finditer(r'^MACRO (\S+)\s*$(.*?)^END \1\s*$',lef.read_text(),re.M|re.S) if a[1]==master)
    obs=rectangles(re.search(r'^\s*OBS\s*$(.*?)^\s*END\s*$',macro,re.M|re.S)[1],lambda v:int(Decimal(v)*db['units']))
    tracks={r.split()[-1]:list(map(int,(r.split()[1],r.split()[3],r.split()[5]))) for r in db['physical']['TRACKS'] if r.startswith('X ')}
    wf=ROOT/'runs/bp-multi-official-pa-v1/macro-io-lazy-ade7f7d2df62/pa.tsv'
    witness=list(csv.DictReader(wf.open(),delimiter='\t'))
    historical=Path('/srv/benchmarks/iBench/benchmarks/results/full_2d_20261021/bp_multi/routing.def.gz')
    history={};locations={};target=None
    with gzip.open(historical,'rt') as stream:
        for line in stream:
            m=re.match(r'^\s*- (gen_13983[45]_) fakeram45_32x64\s+\+ FIXED \( (\d+) (\d+) \) (\w+)',line)
            if m: locations[m[1]]=[int(m[2]),int(m[3]),m[4]]
            n=re.match(r'^- (ib2d_bit_(?:1575|1523)) ',line)
            if n:target=n[1];history[target]=[]
            elif target and line.strip()==';':target=None
            elif target and re.search(r'\b(?:NEW|ROUTED)\s+metal3\b',line):history[target].append(line.strip())
    out={}
    for inst,net in [('gen_139834_','ib2d_bit_1523'),('gen_139835_','ib2d_bit_1575')]:
        _,cx,cy,o=db['components'][inst]['placement']
        assert o=='N'
        x1,y1,x2,y2=[v//2 for v in lib.pin(db,inst,'ce_in')[0][1:]]
        rows=[];local={l:[(cx+a,cy+b,cx+c,cy+d) for layer,a,b,c,d in obs if l==layer] for l in ['metal2','metal3','metal4']}
        for target in ('metal2','metal4'):
            start,count,step=tracks[target]
            hits=[start+i*step for i in range(count) if x1-400<=start+i*step<=x2+400]
            viatypes=[(n,ss) for n,ss in lib.vias.items() if {s[0] for s in ss}=={'metal3',target}]
            points=Counter()
            for x in hits:
                for y in range((y1-400)//grid*grid,y2+401,grid):
                    for name,shapes in viatypes:
                        pads={l:(x+a,y+b,x+c,y+d) for l,a,b,c,d in shapes}
                        if not overlap(pads['metal3'],(x1,y1,x2,y2)):continue
                        points['contact_pin']+=1
                        a=any(overlap(pads['metal3'],r) for r in local['metal3'])
                        b=any(overlap(pads[target],r) for r in local[target])
                        points['clear_m3_owner_obs']+=not a
                        points['clear_adjacent_owner_obs']+=not b
                        points['clear_both']+=not(a or b)
            rows.append(dict(layer=target,x_near=hits,x_through_pin=[x for x in hits if x1<=x<=x2],via_masters=[n for n,_ in viatypes],counts=points))
        hx,hy,ho=locations[inst]
        assert ho=='N'
        hb=[v+offset for v,offset in zip([x1,y1,x2,y2],[hx-cx,hy-cy,hx-cx,hy-cy])]
        out[inst]=dict(ce_in_pin=[x1,y1,x2,y2],canary_witness=[r for r in witness if r['pin'].startswith(inst+':')],
                       via_grid_screen=rows,historical_instance=locations[inst],historical_bbox_if_current_lef=hb,
                       historical_net=net,historical_m3_records=history[net])
    save(WORK/'peer-eligibility.json',dict(source=sha(SOURCE),witness_sha256=sha(wf),history_archive_sha256=sha(historical),
         manufacturing_grid=grid,results=out,scope='Positive or boundary contact, explicit fixed LEF vias, centers on adjacent preferred X and manufactured Y; all participating rectangles measured against own macro OBS.'))
    print(json.dumps(out))
if __name__=='__main__':main()
