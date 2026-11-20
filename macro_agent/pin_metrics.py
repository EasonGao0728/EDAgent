"""Independent integer-DBU HPWL for the reviewed rectangular Nangate IO profile.

Unsupported geometry fails closed. This is not routed length or congestion.
"""
from pathlib import Path
from decimal import Decimal,ROUND_HALF_UP
import hashlib,json,re
from .def_validation import read_def,section

VERSION='pin-hpwl-idb-rect-mean-v1'
def ref(p):
    p=Path(p);return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}

def library(paths,units):
    cv=lambda v:int((Decimal(v)*units).to_integral_value(rounding=ROUND_HALF_UP))
    cells={}
    for p in paths:
        text=Path(p).read_text()
        for a in re.finditer(r'^MACRO (\S+)\s*$(.*?)^END \1\s*$',text,re.M|re.S):
            size=re.search(r'SIZE ([\d.]+) BY ([\d.]+)',a[2]);pins={}
            if not size:raise ValueError('HPWL_UNSUPPORTED_CELL_SIZE')
            for b in re.finditer(r'^\s*PIN (\S+)\s*$(.*?)^\s*END \1\s*$',a[2],re.M|re.S):
                if re.search(r'\b(POLYGON|PATH|VIA)\b',b[2]):raise ValueError('HPWL_UNSUPPORTED_PIN_GEOMETRY')
                rects=[[cv(v) for v in x] for x in re.findall(r'RECT\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s*;',b[2])]
                if not rects:raise ValueError('HPWL_MISSING_PIN_RECT')
                pins[b[1]]=(int(sum(v[0]+v[2] for v in rects)/(2*len(rects))),int(sum(v[1]+v[3] for v in rects)/(2*len(rects))))
            cells[a[1]]={'size':tuple(cv(v) for v in size.groups()),'pins':pins,'macro':bool(re.search(r'CLASS\s+BLOCK\b',a[2]))}
    if not cells:raise ValueError('HPWL_EMPTY_LIBRARY')
    return cells

def transform(x,y,w,h,o):
    return {'N':(x,y),'S':(w-x,h-y),'FN':(w-x,y),'FS':(x,h-y),'W':(h-y,x),'E':(y,w-x),'FW':(h-y,w-x),'FE':(y,x)}[o]

def measure(path,lefs):
    path=Path(path);d=read_def(path);u=d['units'];cells=library(lefs,u);total=0;io_total=0;masters={}
    for c in d['components'].values():masters[c['master']]=masters.get(c['master'],0)+1
    for terminals in d['nets'].values():
        points=[];io=False
        for inst,pin in terminals:
            if inst=='PIN':
                row=d['pins'][pin]
                if len(re.findall(r'\+\s+PORT\b',row))>1:raise ValueError('HPWL_MULTIPORT_IO_UNSUPPORTED')
                q=re.search(r'\+\s+(?:FIXED|PLACED|COVER)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\S+)',row)
                rects=re.findall(r'\+\s+LAYER\s+\S+\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)',row)
                if not q or not rects or any(int(a)+int(c)!=0 or int(b)+int(e)!=0 for a,b,c,e in rects):raise ValueError('HPWL_NONCENTERED_OR_UNPLACED_IO')
                if re.search(r'\b(POLYGON|VIA|MASK)\b',row):raise ValueError('HPWL_IO_GEOMETRY_UNSUPPORTED')
                x,y=int(q[1]),int(q[2]);io=True
            else:
                c=d['components'][inst];cell=cells[c['master']]
                if not c['placement']:raise ValueError('HPWL_UNPLACED_INSTANCE')
                _,ix,iy,o=c['placement'];px,py=transform(*cell['pins'][pin],*cell['size'],o);x,y=ix+px,iy+py
            points.append((x,y))
        v=max((x for x,y in points),default=0)-min((x for x,y in points),default=0)+max((y for x,y in points),default=0)-min((y for x,y in points),default=0)
        total+=v
        if io:io_total+=v
    area=sum(cells[k]['size'][0]*cells[k]['size'][1]*n for k,n in masters.items() if not cells[k]['macro'])/u**2
    return {'schema_version':VERSION,'definition':'all DEF NETS; iDB integer rectangle-corner mean; transformed orientation; real centered IO anchors',
        'units':u,'hpwl_dbu':total,'hpwl_um':total/u,'io_net_hpwl_dbu':io_total,'instances':len(d['components']),
        'nets':len(d['nets']),'standard_cell_area_um2':area,'masters':masters,'sources':[ref(path),*[ref(p) for p in lefs]],
        'congestion':None,'drc':None,'routed_wirelength':None}

def audit(path,lefs,summary):
    m=measure(path,lefs);p=json.loads(Path(summary).read_text());native=p['detail_placement']['hpwl']
    if type(native)!=int:raise ValueError('HPWL_NATIVE_INTEGER_REQUIRED')
    return {'passed':native==m['hpwl_dbu'],'native_dbu':native,'independent_dbu':m['hpwl_dbu'],
            'difference_dbu':m['hpwl_dbu']-native,'measurement':m,'native_source':ref(summary),
            'tolerance_dbu':0,'scope':'placement report versus the exact placement DEF, not post-CTS or legalization'}
