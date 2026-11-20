from pathlib import Path
from urllib.request import Request,urlopen
import json
root=Path('D:/aiEDA/notes/2026-10-11/plan-sources')
root.mkdir(parents=True,exist_ok=True)
repo='The-OpenROAD-Project/OpenROAD-flow-scripts'
sha='5a76f84edc02baf49b75ccbd1a3a9e6a458a8d90'
paths=['flow/util/docker_shell','flow/Makefile','flow/scripts/macro_place.tcl','flow/scripts/variables.yaml','flow/designs/nangate45/tinyRocket/config.mk','flow/designs/nangate45/gcd/config.mk','flow/designs/nangate45/swerv_wrapper/config.mk','flow/designs/nangate45/tinyRocket/freechips.rocketchip.system.TinyConfig.v']
out=[]
for path in paths:
    url='https://raw.githubusercontent.com/'+repo+'/'+sha+'/'+path
    try:
        with urlopen(Request(url,headers={'User-Agent':'EDA-plan-research'}),timeout=30) as r:content=r.read()
        dest=root/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(content)
        out.append({'path':path,'source':url,'bytes':len(content)})
    except Exception as e:out.append({'path':path,'error':repr(e)})
(root/'manifest.json').write_text(json.dumps({'repo':repo,'commit':sha,'sources':out},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out))
