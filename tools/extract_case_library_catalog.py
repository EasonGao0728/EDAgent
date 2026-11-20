"""Read only authorized reference libraries for inventory classification."""
from pathlib import Path
import json,hashlib,re,os,resource
ROOT=Path('/srv/edagent/main-agent-remote-v1')
SHARED=Path('/srv/benchmarks/iBench/benchmarks')

def lef_cells(t):
    cells={}
    for a in re.finditer(r'^\s*MACRO\s+(\S+)[^\S\r\n]*$(.*?)^\s*END\s+\1[^\S\r\n]*$',t,re.M|re.S):
        sz=re.search(r'\bSIZE\s+([\d.eE+-]+)\s+BY\s+([\d.eE+-]+)',a[2])
        cells[a[1]]={'area_um2':float(sz[1])*float(sz[2]) if sz else None,'macro':bool(re.search(r'CLASS\s+BLOCK\b',a[2]))}
    return cells

def main():
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3))
    rows=[];seen=set();inputs=[]
    for mf in sorted((ROOT/'cases').rglob('manifest.json')):
        m=json.loads(mf.read_text())
        base=ROOT/'third_party/ieda-reference' if m.get('case_id')=='sky130_gcd' else mf.parent
        inputs.extend((base/p,{'case_id':m.get('case_id')}) for p in m.get('cell_lefs',[])+m.get('libs',[]))
    inputs.extend((p,{'pdk':p.parent.parent.name}) for p in sorted((SHARED/'common/2d_pdk').glob('*/lef/*.lef')))
    for p,meta in inputs:
        p=p.resolve()
        if not any(r==p or r in p.parents for r in (ROOT,SHARED)):
            rows.append({**meta,'path':str(p),'status':'outside_authorized_roots'});continue
        if str(p) in seen:continue
        seen.add(str(p))
        if not p.is_file():rows.append({**meta,'path':str(p),'status':'missing'});continue
        data=p.read_bytes();t=data.decode();cells={}
        if p.suffix=='.lef':
            cells=lef_cells(t)
        elif p.suffix=='.lib':
            starts=list(re.finditer(r'\bcell\s*\(\s*"?([^\s"()]+)"?\s*\)\s*\{',t))
            for i,a in enumerate(starts):
                block=t[a.end():starts[i+1].start() if i+1<len(starts) else len(t)]
                cells[a[1]]={'sequential':bool(re.search(r'\b(?:ff|latch)\s*\(',block)),
                            'ff':bool(re.search(r'\bff\s*\(',block)),'latch':bool(re.search(r'\blatch\s*\(',block))}
        unit=re.search(r'\btime_unit\s*:\s*"([^"]+)"',t) if p.suffix=='.lib' else None
        rows.append({**meta,'path':str(p),'sha256':hashlib.sha256(data).hexdigest(),'cells':cells,'status':'read','library_time_unit':unit[1] if unit else None})
    print(json.dumps(rows))

if __name__=='__main__':main()
