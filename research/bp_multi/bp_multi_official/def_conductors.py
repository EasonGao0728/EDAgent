"""Offline same-layer rectangle contact graph for the rectangular Nangate45 LEF/DEF profile."""
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
import re

from macro_agent.def_validation import section
from macro_agent.pin_metrics import transform


def rectangles(block, convert):
    if re.search(r'\b(?:POLYGON|PATH|ITERATE|MASK|VIARULE)\b',block):
        raise ValueError('unsupported LEF conductor geometry')
    shapes=[]
    layer=None
    for item in re.finditer(r'\b(LAYER|RECT)\s+([^;]+);',block):
        fields=item[2].split()
        if item[1]=='LAYER':
            if len(fields)!=1:raise ValueError('unsupported LEF layer qualifiers')
            layer=fields[0]
        else:
            if not layer or len(fields)!=4:raise ValueError('invalid LEF RECT')
            shapes.append((layer,*map(convert,fields)))
    if not shapes:raise ValueError('no LEF rectangles')
    return shapes


class PhysicalLibrary:
    def __init__(self, tech, lefs, units):
        def dbu(s):
            d=Decimal(s)*units
            if d!=d.to_integral_value():raise ValueError('nonintegral LEF coordinate')
            return int(d)
        text=Path(tech).read_text()
        self.width={}
        for m in re.finditer(r'^LAYER (\S+)\s*$(.*?)^END \1\s*$',text,re.M|re.S):
            if re.search(r'\bTYPE ROUTING\s*;',m[2]):
                self.width[m[1]]=dbu(re.search(r'\bWIDTH (\S+)\s*;',m[2])[1])
        self.vias={}
        for m in re.finditer(r'^VIA (\S+)(?: DEFAULT)?\s*$(.*?)^END \1\s*$',text,re.S|re.M):
            shapes=rectangles(m[2],dbu)
            metal=[r for r in shapes if r[0] in self.width]
            cuts=[r for r in shapes if r[0] not in self.width]
            if len(metal)!=2 or metal[0][0]==metal[1][0] or not cuts:
                continue
            if all(all(b[1]<=c[1]<=c[3]<=b[3] and b[2]<=c[2]<=c[4]<=b[4] for b in metal) for c in cuts):
                self.vias[m[1]]=metal
        self.cells={}
        for file in lefs:
            for m in re.finditer(r'^MACRO (\S+)\s*$(.*?)^END \1\s*$',Path(file).read_text(),re.M|re.S):
                name,body=m[1],m[2]
                origin=re.search(r'\bORIGIN (\S+) (\S+)\s*;',body)
                if name in self.cells or (origin and any(dbu(c) for c in origin.groups())):
                    raise ValueError('unsupported duplicate/nonzero-origin LEF macro '+name)
                w,h=map(dbu,re.search(r'\bSIZE (\S+) BY (\S+)\s*;',body).groups())
                pins={}
                for p in re.finditer(r'^\s*PIN (\S+)\s*$(.*?)^\s*END \1\s*$',body,re.M|re.S):
                    pins[p[1]]=rectangles(p[2],dbu)
                self.cells[name]=(w,h,pins)

    def pin(self, db, inst, pin):
        if inst=='PIN':
            row=db['pins'][pin]
            if row.count('+ PORT')>1:raise ValueError('unsupported multi-port IO')
            m=re.search(r'\+ (?:FIXED|PLACED) \( (-?\d+) (-?\d+) \) (\S+)',row)
            x,y=int(m[1]),int(m[2]);orientation=m[3]
            w=h=0
            rects=[(l,*map(int,p)) for l,*p in re.findall(r'\+ LAYER (\S+) \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \)',row)]
        else:
            c=db['components'][inst]
            _,x,y,orientation=c['placement']
            w,h,pins=self.cells[c['master']]
            rects=pins[pin.replace('\\[','[').replace('\\]',']')]
        if not rects:raise ValueError('no pin geometry: '+pin)
        out=[]
        for layer,x1,y1,x2,y2 in rects:
            if layer not in self.width:raise ValueError('pin geometry on unsupported layer')
            a,b=transform(x1,y1,w,h,orientation);c,d=transform(x2,y2,w,h,orientation)
            out.append((layer,2*(min(a,c)+x),2*(min(b,d)+y),2*(max(a,c)+x),2*(max(b,d)+y)))
        return out


def touch_groups(groups):
    """A pin or a named via is one conductor. Metal only contacts within its layer."""
    roots=list(range(len(groups)))
    def root(i):
        while roots[i]!=i:
            roots[i]=roots[roots[i]]
            i=roots[i]
        return i
    layers=defaultdict(list)
    for group_id,rects in enumerate(groups):
        if not rects:raise ValueError('empty conductor')
        for layer,x1,y1,x2,y2 in rects:
            if x2<=x1 or y2<=y1:raise ValueError('degenerate conductor')
            layers[layer].append((x1,x2,y1,y2,group_id))
    for boxes in layers.values():
        active=[]
        for x1,x2,y1,y2,group in sorted(boxes):
            active=[r for r in active if r[0]>=x1]
            for _,yy1,yy2,other in active:
                if y1<=yy2 and yy1<=y2:
                    a,b=root(group),root(other)
                    if a!=b:roots[a]=b
            active.append((x2,y1,y2,group))
    return [root(i) for i in range(len(groups))]


def analyze_net(row, db, lib, terminal_list):
    """Coordinates doubled to represent half-width ends exactly (including odd DBU widths)."""
    groups=[lib.pin(db,*pin) for pin in terminal_list]
    pin_count=len(groups)
    parts=re.split(r'\+\s+(?:ROUTED|FIXED|COVER)\s+',row)[1:]
    paths=Counter()
    point=r'\(\s*([*]|-?\d+)\s+([*]|-?\d+)(?:\s+(-?\d+))?\s*\)'
    for part in parts:
        for path in re.split(r'\bNEW\s+',part):
            layer,body=path.strip().split(None,1)
            width=lib.width[layer]
            x=y=extension=None
            while (m:=re.match(point,body)):
                nx=x if m[1]=='*' else int(m[1])*2
                ny=y if m[2]=='*' else int(m[2])*2
                end=width if m[3] is None else int(m[3])*2
                if nx is None or ny is None or end<0:raise ValueError('invalid coordinate/extension')
                if x is not None and (nx,ny)!=(x,y):
                    if y==ny:
                        left,right=sorted(((x,extension),(nx,end)))
                        groups.append([(layer,left[0]-left[1],y-width,right[0]+right[1],y+width)])
                    elif x==nx:
                        low,high=sorted(((y,extension),(ny,end)))
                        groups.append([(layer,x-width,low[0]-low[1],x+width,high[0]+high[1])])
                    else:raise ValueError('non-Manhattan wire')
                    paths['wire']+=1
                x,y,extension=nx,ny,end
                body=body[m.end():].strip()
            if x is None:raise ValueError('missing point')
            if body in lib.vias:
                shapes=lib.vias[body]
                if layer not in {r[0] for r in shapes}:raise ValueError('via on wrong layer '+body)
                groups.append([(l,x+2*a,y+2*b,x+2*c,y+2*d) for l,a,b,c,d in shapes])
                paths['via']+=1
            elif (m:=re.fullmatch(r'RECT\s+\(\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*\)',body)):
                a,b,c,d=map(int,m.groups())
                groups.append([(layer,x+2*a,y+2*b,x+2*c,y+2*d)])
                paths['patch']+=1
            elif body:raise ValueError('unsupported via/route clause '+body[:80])
    labels=touch_groups(groups)
    pin_roots=set(labels[:pin_count])
    floating=sum(label not in pin_roots for label in labels[pin_count:])
    return len(pin_roots)==1, floating, paths


def independent_graph(text, db, expected, lib):
    totals=Counter()
    bad=[]
    names=set()
    for row in section(text,'NETS'):
        name=row.split(None,1)[0]
        if name not in expected:continue
        if name in names:raise ValueError('duplicate net: '+name)
        names.add(name)
        connected,floating,counts=analyze_net(row,db,lib,expected[name])
        totals.update(counts)
        totals.update({'pins':len(expected[name]), 'disconnected_nets':int(not connected),'floating_primitives':floating})
        if (not connected or floating) and len(bad)<12:bad.append(name)
    return dict(passed=names==set(expected) and not bad, net_count=len(names), **totals,
                failed_net_examples=bad, model='Intra-net closed-contact rectangles with explicit LEF via metal enclosures and transformed pin ports; excludes inter-net shorts and signoff DRC.')
