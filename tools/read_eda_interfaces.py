from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from urllib.request import Request,urlopen
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')
root=Path('D:/aiEDA/notes/2026-10-11/sources')
selected={
 'iEDA':['src/operation/iPL/api/PLAPI.cc','src/interface/python/py_ipl/py_ipl.cpp','src/interface/python/py_ipl/py_register_ipl.h'],
 'AiEDA':['aieda/ai/design_parameter_optimization/dse_facade.py','aieda/flows/ieda.py'],
 'iChipAgent':['src/extension.ts'],
}
def read(item):
    name,path=item
    info=json.loads((root/name/'inspection.json').read_text(encoding='utf-8'))
    # Pin the content to the tree SHA observed in the previous inspection.
    url='https://raw.githubusercontent.com/OSCC-Project/'+name+'/'+info['tree_sha']+'/'+path
    try:
        with urlopen(Request(url,headers={'User-Agent':'Undergraduate-project-research'}),timeout=30) as r:raw=r.read()
        out=root/name/path;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(raw)
        return {'repo':name,'path':path,'bytes':len(raw),'source':url}
    except Exception as e:return {'repo':name,'path':path,'error':repr(e)}
results=[]
with ThreadPoolExecutor(max_workers=4) as pool:
    for f in as_completed([pool.submit(read,(n,p)) for n,paths in selected.items() for p in paths]):
        result=f.result();results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
(root/'selected_sources.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
