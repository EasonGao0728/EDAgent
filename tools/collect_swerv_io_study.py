"""Bounded read-only collection, after the fixed no-hold IO study completes."""
from pathlib import Path
import base64,hashlib,json,subprocess,zlib
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/swerv-no-hold-20261115/evidence'
CODE=r'''
from pathlib import Path
import base64,hashlib,json,os,zlib
assert os.getuid()==1015
root=Path('/srv/edagent/main-agent-remote-v1')
p=root/'runs/swerv-io-fixed-nohold-20261115-v3'
r=json.loads((p/'receipt.json').read_text());assert r['status']=='completed'
files={'io-receipt.json':p/'receipt.json'}
for label in ('imp_fixed','shelf_fixed'):
    w=p/label
    for name in ('result/placement.def','result/macro_placement.def','result/fanout.def','result/legalization.def','placement-summary-preserved.json','result/timing/swerv_wrapper.rpt','config/pl_default_config.json','config/no_default_config_fixfanout.json','config/to_default_config_drv.json','logs/placement.log'):
        files[label+'-'+name.replace('/','-')]=w/name
    for f in w.glob('*-io-compatibility.json'):
        files[label+'-'+f.name]=f
    for f in w.glob('*-evidence.json'):
        files[label+'-'+f.name]=f
q=root/'runs/swerv-no-hold-20261115-v1'
for name in ('receipt.json','candidate/result/legalization.def','candidate/result/timing/swerv_wrapper.rpt'):
    files['original_nohold-'+name.replace('/','-')]=q/name
items=[];total=0
for name,f in files.items():
    assert f.resolve().is_relative_to(root/'runs') and f.stat().st_size<12*1024**2
    data=f.read_bytes();total+=len(data);assert total<70*1024**2
    items.append({'name':name,'server_path':str(f),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'data':base64.b64encode(zlib.compress(data)).decode()})
print(json.dumps({'files':items,'server_study_bytes':sum(f.stat().st_size for f in p.rglob('*') if f.is_file())}))
'''
def main():
    p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','eda-worker','python3 -'],input=CODE,capture_output=True,text=True,encoding='utf-8',timeout=60)
    if p.returncode:raise RuntimeError(p.stderr[-1200:])
    v=json.loads(p.stdout);OUT.mkdir(parents=True,exist_ok=True)
    for item in v['files']:
        data=zlib.decompress(base64.b64decode(item.pop('data')))
        assert len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256']
        dest=OUT/item['name'];assert dest.parent==OUT
        if dest.exists() and dest.read_bytes()!=data:raise ValueError('Preserve existing evidence: '+str(dest))
        dest.write_bytes(data)
    (OUT/'manifest.json').write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'files':len(v['files']),'download_bytes':sum(f['bytes'] for f in v['files']),'server_study_bytes':v['server_study_bytes']}))
if __name__=='__main__':main()
