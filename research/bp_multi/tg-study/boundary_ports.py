"""Measure legal preferred-axis pin crossings and distance to the first mesh intersection."""
from collections import Counter
import re

from verify_pa import ROOT, RUNS, SOURCE, setup, read_def, save, transform


def nearest(value, spec):
    start,count,pitch = spec
    i=max(0,min((value-start)//pitch,count-1))
    return min({start+i*pitch,start+min(count-1,i+1)*pitch},key=lambda x:(abs(x-value),x))


def main():
    db=read_def(SOURCE);ref=setup()
    tech=(ref/'data/input2.lef').read_text()
    grids={}
    for row in db['physical']['TRACKS']:
        axis,start,_,count,_,pitch,_,layer=row.split()
        grids[layer,axis]=tuple(map(int,(start,count,pitch)))
    profiles=Counter();miss=[];examples={}
    for name,row in db['pins'].items():
        shape=re.search(r'\+ LAYER (\S+) \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \)',row)
        place=re.search(r'\+ PLACED \( (-?\d+) (-?\d+) \) (\w+)',row)
        if not (shape and place):raise ValueError(name)
        layer=shape[1];cx,cy=map(int,place.groups()[:2]);o=place[3]
        x1,y1=transform(int(shape[2]),int(shape[3]),0,0,o)
        x2,y2=transform(int(shape[4]),int(shape[5]),0,0,o)
        bx=sorted((cx+x1,cx+x2));by=sorted((cy+y1,cy+y2))
        block=re.search(r'^LAYER '+re.escape(layer)+r'\s*$(.*?)^END '+re.escape(layer)+r'\s*$',tech,re.S|re.M)[1]
        vertical=re.search(r'\bDIRECTION (\w+)',block)[1]=='VERTICAL'
        track_x=nearest(cx,grids[layer,'X']);track_y=nearest(cy,grids[layer,'Y'])
        on=bx[0]<=track_x<=bx[1] if vertical else by[0]<=track_y<=by[1]
        outside=max(0,by[0]-track_y,track_y-by[1]) if vertical else max(0,bx[0]-track_x,track_x-bx[1])
        profiles[(layer,on,outside>0)]+=1
        if not on:miss.append(name)
        if name=='clk_i':examples[name]=dict(center=[cx,cy],layer=layer,crossing=[track_x,track_y],
                longitudinal_gap_from_pin_edge_dbu=outside,preferred_track_intersects_pin=on)
    save(RUNS/'boundary-ports.json',{'denominator':len(db['pins']),'profiles':[dict(layer=k[0],preferred_track_crosses_pin=k[1],
         longitudinal_track_outside_pin=k[2],count=v) for k,v in sorted(profiles.items())],
         'missing_preferred_track':miss,'examples':examples,'units':db['units']})


if __name__=='__main__':main()
