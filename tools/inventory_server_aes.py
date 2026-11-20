"""Read only shared iBench AES metadata; never execute the shared flow."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'runs/aes-p1-20261108'
CODE = r'''
import json, hashlib, re
from pathlib import Path
b=Path('/srv/benchmarks/iBench/benchmarks')
rows=[]
for p in sorted((b/'designs').glob('*aes*/design.json')):
 d=json.loads(p.read_text()); prep=d.get('input_preparation',{}); stats=prep.get('statistics',{})
 n=p.parent/d.get('inputs',{}).get('netlist','MISSING')
 row={'directory':p.parent.name,'name':d.get('name'),'top':d.get('top'),'pdk':d.get('pdk'),
 'scale':d.get('scale'),'role':d.get('role'),'cells':stats.get('cell_count'),'macros':stats.get('macros'),
 'pins':stats.get('top_pin_bits'),'inputs':d.get('inputs'),'floorplan':d.get('floorplan'),
 'netlist_exists':n.is_file(),'netlist_bytes':n.stat().st_size if n.is_file() else None,
 'netlist_sha256':hashlib.sha256(n.read_bytes()).hexdigest() if n.is_file() else None}
 rows.append(row)
print(json.dumps({'root':str(b),'cases':rows},ensure_ascii=False))
'''

if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','eda-worker','python3 -B -'],
                       input=CODE,text=True,encoding='utf-8',capture_output=True,timeout=45,check=True)
    data=json.loads(p.stdout)
    (OUT/'server-inventory.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    for r in data['cases']:
        print(json.dumps({k:r[k] for k in ('directory','top','pdk','scale','cells','macros','pins','netlist_bytes')},ensure_ascii=False))
