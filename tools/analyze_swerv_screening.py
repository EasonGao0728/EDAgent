"""Offline analysis of verified study outputs; never executes EDA."""
from pathlib import Path
import json,re,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from macro_agent.def_validation import read_def,section
E=ROOT/'runs/swerv-screening-20261115-v2/evidence'


def library(pin_reference='bbox_center', units=2000):
    cells={}
    for p in (ROOT/'cases/ibench/swerv_nangate45/pdk/lef').glob('*.lef'):
        text=p.read_text()
        for a in re.finditer(r'^MACRO (\S+)\s*$(.*?)^END \1\s*$',text,re.M|re.S):
            size=re.search(r'SIZE ([\d.]+) BY ([\d.]+)',a[2]);pins={}
            if not size:raise ValueError('No size')
            for b in re.finditer(r'^\s*PIN (\S+)\s*$(.*?)^\s*END \1\s*$',a[2],re.M|re.S):
                if re.search(r'\b(POLYGON|PATH|VIA)\b',b[2]):raise ValueError('Unsupported pin geometry')
                rects=[list(map(float,x)) for x in re.findall(r'RECT\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s*;',b[2])]
                if not rects:raise ValueError('No pin rect: '+a[1]+'/'+b[1])
                pins[b[1]]=((min(x[0] for x in rects)+max(x[2] for x in rects))/2,(min(x[1] for x in rects)+max(x[3] for x in rects))/2)
                if pin_reference=='idb_rect_mean':
                    dbu=[[round(v*units) for v in rect] for rect in rects]
                    pins[b[1]]=(int(sum(v[0]+v[2] for v in dbu)/(2*len(dbu)))/units,int(sum(v[1]+v[3] for v in dbu)/(2*len(dbu)))/units)
                elif pin_reference!='bbox_center':raise ValueError('Unsupported pin reference')
            cells[a[1]]={'size':tuple(map(float,size.groups())),'pins':pins}
    return cells


def transform(x,y,w,h,o):
    return {'N':(x,y),'S':(w-x,h-y),'FN':(w-x,y),'FS':(x,h-y),
            'W':(h-y,x),'E':(y,w-x),'FW':(h-y,w-x),'FE':(y,x)}[o]


def pin_hpwl(path,cells,io_override_dbu=None):
    d=read_def(path);u=d['units'];rows={x.split()[0]:x for x in section(path.read_text(),'NETS')};results={};by={}
    for net,terms in d['nets'].items():
        pts=[];hasmacro=False
        for inst,pin in terms:
            if inst=='PIN':
                q=re.search(r'\+ (?:FIXED|PLACED|COVER) \( (-?\d+) (-?\d+) \) (\S+)',d['pins'][pin]);x,y=int(q[1])/u,int(q[2])/u
                # Registered IO rectangle is centered on its anchor; reject otherwise.
                rects=re.findall(r'\+ LAYER \S+ \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \)',d['pins'][pin])
                if not rects or any(int(a)+int(c)!=0 or int(b)+int(e)!=0 for a,b,c,e in rects):raise ValueError('Non-centered IO')
                if io_override_dbu is not None:x,y=(v/u for v in io_override_dbu)
            else:
                c=d['components'][inst];cell=cells[c['master']];hasmacro|=c['master'].startswith('fakeram')
                _,ix,iy,o=c['placement'];px,py=cell['pins'][pin];w,h=cell['size'];px,py=transform(px,py,w,h,o);x,y=ix/u+px,iy/u+py
            pts.append((x,y))
        value=(max(x for x,y in pts)-min(x for x,y in pts)+max(y for x,y in pts)-min(y for x,y in pts)) if pts else 0
        use=(re.search(r'\+ USE (\w+)',rows[net]) or [None,'SIGNAL'])[1]
        results[net]={'um':value,'degree':len(terms),'use':use,'macro':hasmacro,'io':any(a=='PIN' for a,b in terms)}
        by[use]=by.get(use,0)+value
    return {'all_um':sum(x['um'] for x in results.values()),'degree_le_100_um':sum(x['um'] for x in results.values() if x['degree']<=100),
            'signal_degree_le_100_um':sum(x['um'] for x in results.values() if x['degree']<=100 and x['use']=='SIGNAL'),
            'by_use_um':by,'net_count':len(results),'rows':results}


def sta(path):
    out={};slacks={'min':[],'max':[]}
    for line in path.read_text().splitlines():
        values=[x.strip() for x in line.split('|')[1:-1]]
        if len(values)==8 and values[2] in slacks:slacks[values[2]].append(float(values[6]))
        if len(values)==3 and values[0]=='core_clock' and values[1] in slacks:out[values[1]+'_tns_ns']=float(values[2])
    for k,v in slacks.items():
        if not v:raise ValueError('Missing STA paths')
        out[k+'_worst_reported_slack_ns']=min(v)
    return out


def main():
    r=json.loads((E/'receipt.json').read_text(encoding='utf-8'));cells=library();out={'job_id':r['job_id'],'status':r['status'],'study_seconds':r['finished_at']-r['started_at'],'hold':{},'macro':{},'scope':'pre-route screening, no SPEF/signoff/DRC or routing-time improvement established'}
    for key,label in [('hold_20','hold_20_reused'),('hold_05','hold_05'),('hold_10','hold_10')]:
        v=r['results'][key];p=v['native_pass'][0]
        out['hold'][key]={'cap':v['factor'],'inserted_buffers':p['accepted'],
            **{k:v['metrics'][k] for k in ('instances','nets','center_hpwl_um')},
            'geometry_passed':v['metrics']['geometry']['passed'],'inline_hold_metrics':p['timing_quality_after']['wns_tns'],
            'fresh_sta':sta(E/(label+'-timing.rpt'))}
    for key,label in [('macro_imp_reused','macro_imp'),('macro_shelf','macro_shelf')]:
        v=r['results'][key];p=v['native_place_summary'];ind=pin_hpwl(E/(label+'-result-placement.def'),cells)
        (E/(label+'-independent-net-hpwl.json')).write_text(json.dumps(ind['rows'],indent=2),encoding='utf-8');ind.pop('rows')
        out['macro'][label]={'center_hpwl_um':v['metrics']['center_hpwl_um'],'native_hpwl_dbu':p['detail_placement']['hpwl'],'native_hpwl_um':p['detail_placement']['hpwl']/2000,
            'config_hash':p['effective_config_hash'],'geometry_passed':v['metrics']['geometry']['passed'],'independent_pin_bbox_hpwl':ind}
    (E.parent/'analysis.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(out,ensure_ascii=False))

if __name__=='__main__':main()
