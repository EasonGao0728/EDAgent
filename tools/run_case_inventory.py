"""Stream a read-only SSH inventory to local JSONL; never deploy or run iEDA."""
from pathlib import Path
import subprocess,json,time
root=Path(__file__).resolve().parents[1];out=root/'runs/case-perception-20261115';out.mkdir(exist_ok=True)
p=subprocess.Popen(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','eda-worker','python3 -B -'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
p.stdin.write((root/'tools/inventory_case_features.py').read_text(encoding='utf-8'));p.stdin.close()
with (out/'case-features-raw.jsonl').open('w',encoding='utf-8') as f:
    for i,line in enumerate(p.stdout):
        v=json.loads(line);f.write(line);f.flush()
        if i%20==0 or v.get('record_type')=='summary':print(json.dumps({'rows':i+1,'case':v.get('case_id'),'summary':v if v.get('record_type')=='summary' else None}),flush=True)
stderr=p.stderr.read();code=p.wait();(out/'inventory-stderr.txt').write_text(stderr,encoding='utf-8')
if code:raise RuntimeError(f'Inventory exited {code}: {stderr}')
print('READ_ONLY_INVENTORY_COMPLETE',flush=True)
