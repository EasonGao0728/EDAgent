"""Read-only, bounded download of fixed SWERV study evidence."""
from pathlib import Path
import base64,hashlib,json,subprocess,zlib
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/swerv-screening-20261115-v2/evidence'
CODE=r'''
from pathlib import Path
import base64,hashlib,json,os,zlib
assert os.getuid()==1015
root=Path('/srv/edagent/main-agent-remote-v1');p=root/'runs/swerv-screening-20261115-v2'
r=json.loads((p/'receipt.json').read_text());assert r['status']=='completed'
parent=root/'runs/remote-ba81f7bdbfebcf944da30462';s=json.loads((parent/'task.json').read_text())
files={'receipt.json':p/'receipt.json'}
for label in ('hold_20_reused','hold_05','hold_10'):
    w=p/label
    files[label+'-timing.rpt']=w/'result/timing/swerv_wrapper.rpt'
    files[label+'-timing-evidence.json']=w/'timing-evidence.json'
    if label!='hold_20_reused':
        for name in ('to_hold-evidence.json','legalization-evidence.json','config/to_default_config_hold.json','result/legalization.def','logs/to_hold.log'):
            files[label+'-'+name.replace('/','-')]=w/name
files['hold_20-legalization.def']=Path(s['results']['legalization']['artifact'])
files['hold_20-native.log']=Path(s['results']['to_hold']['log'])
for label,w in [('macro_imp',Path(s['results']['placement']['artifact']).parents[1]),('macro_shelf',p/'macro_shelf')]:
    for name in ('result/placement.def','result/pl/report/summary_report.txt','result/pl/report/place_summary.json','config/pl_default_config.json','logs/placement.log','result/fanout.def'):
        files[label+'-'+name.replace('/','-')]=w/name
items=[];total=0
for name,f in files.items():
    assert f.resolve().is_relative_to(root/'runs') and f.stat().st_size<12*1024**2
    data=f.read_bytes();total+=len(data);assert total<40*1024**2
    items.append({'name':name,'server_path':str(f),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'data':base64.b64encode(zlib.compress(data)).decode()})
print(json.dumps({'files':items,'server_study_bytes':sum(f.stat().st_size for f in p.rglob('*') if f.is_file())}))
'''
p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','eda-worker','python3 -'],input=CODE,capture_output=True,text=True,encoding='utf-8',timeout=60)
if p.returncode:raise RuntimeError(p.stderr[-1000:])
v=json.loads(p.stdout);OUT.mkdir(parents=True,exist_ok=True)
for item in v['files']:
    data=zlib.decompress(base64.b64decode(item.pop('data')));assert len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256']
    dest=OUT/item['name'];assert dest.parent==OUT;dest.write_bytes(data)
(OUT/'manifest.json').write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'files':len(v['files']),'download_bytes':sum(f['bytes'] for f in v['files']),'server_study_bytes':v['server_study_bytes']}))
