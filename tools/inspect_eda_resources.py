from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from urllib.request import Request,urlopen
from urllib.parse import quote
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')
root=Path('D:/aiEDA/notes/2026-10-11/sources')
root.mkdir(parents=True,exist_ok=True)
def get(url):
    with urlopen(Request(url,headers={'User-Agent':'Undergraduate-project-research'}),timeout=30) as r:
        return r.read()
def inspect(name):
    repo='OSCC-Project/'+name
    folder=root/name;folder.mkdir(exist_ok=True)
    try:
        meta=json.loads(get('https://api.github.com/repos/'+repo))
        branch=meta['default_branch']
        tree=json.loads(get('https://api.github.com/repos/'+repo+'/git/trees/'+quote(branch,safe='')+'?recursive=1'))
        paths=[p['path'] for p in tree['tree'] if p['type']=='blob']
        (folder/'tree.json').write_text(json.dumps(tree,ensure_ascii=False),encoding='utf-8')
        info={'repository':repo,'branch':branch,'tree_sha':tree['sha'],'tree_truncated':tree.get('truncated'),
              'source_url':'https://github.com/'+repo,'files':len(paths),'read_files':[]}
        for p in ['README.md','README-CN.md','README.zh-CN.md']:
            if p in paths:
                raw=get('https://raw.githubusercontent.com/'+repo+'/'+quote(branch,safe='')+'/'+p)
                (folder/p).write_bytes(raw);info['read_files'].append(p)
        (folder/'inspection.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
        interesting=[p for p in paths if any(s in p.lower() for s in ['macro','mcp','floorplan','/ifp/','ieda_python_api','/ieda/','ieda_api','run_ieda','agent','server.py'])]
        return {'name':name,'info':info,'interesting_paths':interesting[:70]}
    except Exception as e:return {'name':name,'error':repr(e)}
with ThreadPoolExecutor(max_workers=4) as pool:
    for future in as_completed([pool.submit(inspect,n) for n in ['iEDA','AiEDA','iMCP','iChipAgent']]):
        print(json.dumps(future.result(),ensure_ascii=False),flush=True)
