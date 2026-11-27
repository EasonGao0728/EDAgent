"""Screen edge escape metal against actual transformed SRAM obstruction geometry; no EDA execution."""
import csv
from collections import Counter
from decimal import Decimal
from pathlib import Path
import re

from sram_escape_check import ROOT,BASE,DEF_HASH,WORK,SOURCE,setup,read_def,PhysicalLibrary,sha,save
from def_conductors import rectangles
from macro_agent.pin_metrics import transform


def overlap(a,b):
    return max(a[0],b[0])<=min(a[2],b[2]) and max(a[1],b[1])<=min(a[3],b[3])

def main():
    assert sha(SOURCE)==DEF_HASH
    folder=ROOT/'runs/bp-multi-official-pa-v1/full-lazy-ade7f7d2df62'
    unresolved=folder/'pa.tsv.unresolved.tsv'
    sample=list(csv.DictReader(unresolved.open(),delimiter='\t'))
    assert len(sample)==179
    ref=setup();tech=ref/'data/input2.lef'
    lefs=sorted((ref/'data').glob('input[3-9].lef'))
    db=read_def(SOURCE);unit=db['units']
    lib=PhysicalLibrary(tech,lefs,unit)
    instance='gen_139835_'
    macro=db['components'][instance]
    size=lib.cells[macro['master']][:2]
    _,cx,cy,o=macro['placement']
    bodies=[a[2] for lef in lefs for a in re.finditer(r'^MACRO (\S+)\s*$(.*?)^END \1\s*$',lef.read_text(),re.M|re.S) if a[1]==macro['master']]
    assert len(bodies)==1 and o=='N'
    obs=rectangles(re.search(r'^\s*OBS\s*$(.*?)^\s*END\s*$',bodies[0],re.M|re.S)[1],lambda v:int(Decimal(v)*unit))
    block=[(x1+cx,y1+cy,x2+cx,y2+cy) for l,x1,y1,x2,y2 in obs if l=='metal3']
    grids={}
    for record in db['physical']['TRACKS']:
        axis,start,_,count,_,pitch,_,layer=record.split()
        if layer=='metal3': grids[axis]=[int(start)+int(pitch)*i for i in range(int(count))]
    width=lib.width['metal3']; assert width==140
    out=[]; counts=Counter()
    for row in sample:
        inst,pin=row['pin'].split(':',1)
        assert inst==instance and (inst,pin) in db['nets'][row['net']]
        rects=lib.pin(db,inst,pin)
        if len(rects)!=1 or rects[0][0]!='metal3':raise ValueError('unexpected shape')
        x1,y1,x2,y2=[v//2 for v in rects[0][1:]]
        assert x1==cx and (x2-x1)==(y2-y1)==width
        y=(y1+y2)//2
        a=max(x for x in grids['X'] if x<x1-width*2)
        b=min(grids['Y'],key=lambda v:(abs(v-y),v))
        first=(a-width//2,y1,x1+width//2,y2)
        second=(a-width//2,min(y,b)-width//2,a+width//2,max(y,b)+width//2)
        direct=[v for v in block if overlap(first,v)]
        flank=[v for v in block if overlap(second,v)]
        flush=[v for v in block if overlap((first[0],y1,x1,y2),v)]
        counts['first_signal_segment_hits_own_obs']+=bool(direct)
        counts['elbow_vertical_hits_own_obs']+=bool(flank)
        counts['flush_end_contacts_own_obs']+=bool(flush)
        counts['y_axis_hits_terminal']+=any(y1<=v<=y2 for v in grids['Y'])
        out.append(dict(net=row['net'],pin=pin,terminal=[x1,y1,x2,y2],P=[x1,y],A=[a,y],B=[a,b],
                        first_contacts=len(direct),second_contacts=len(flank),flush_contacts=len(flush),
                        contact_examples=direct[:2]))
    save(WORK/'sram-eligibility.json',dict(checkpoint=DEF_HASH,unresolved_report_sha256=sha(unresolved),master=macro['master'],
         placement=macro['placement'],units=unit,rows=len(sample),counts=dict(counts),pins=out,
         scope='Proposed outward M3 arm must clear the owner macro OBS. Exhaustive over the 179 unresolved terminals. A contact is sufficient to reject this shape; not an impossibility proof for other geometries.'))
    print(counts)
if __name__=='__main__': main()
