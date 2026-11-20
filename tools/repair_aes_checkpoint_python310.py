"""One explicit, audited repair of the Core launcher before any native tail ran."""
import base64,hashlib,json,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'runs/aes-p1-20261108'
def main():
    original=json.loads((OUT/'v5d-deployment.json').read_text())
    name='tools/resume_aes_storage_checkpoint.py';data=(ROOT/name).read_bytes()
    new_hash=hashlib.sha256(data).hexdigest();old_hash=original['files'][name]
    if new_hash==old_hash:raise ValueError('No source repair to deploy')
    updated=json.loads(json.dumps(original));updated['files'][name]=new_hash
    archive=json.loads((OUT/'v5c-server-core-01-archive-receipt.json').read_text())
    code=f'''import os,pathlib,json,hashlib,base64,subprocess,shlex,time
assert os.getuid()==1015
root=pathlib.Path({original['remote_root']!r});assert root.resolve()==root
assert not (root/'runs/server-core-02').exists()
assert not list(root.glob('core-checkpoint-*'))
for p in root.parent.glob('aes-p1-20261108*/runs/*/run.json'):
 assert json.loads(p.read_text())['status']!='running',str(p)
d=json.loads((root/'deployment.json').read_text());assert d=={original!r}
for rel,h in d['files'].items():assert hashlib.sha256((root/rel).read_bytes()).hexdigest()==h,rel
log=root/'server-core-02.console.log';failure=log.read_text()
assert "AttributeError: module 'hashlib' has no attribute 'file_digest'" in failure and 'RUN gds_export' not in failure
parent=root/'core-parent.tar.gz';assert parent.resolve()==parent and hashlib.sha256(parent.read_bytes()).hexdigest()=={archive['archive_sha256']!r}
receipt=root/'python310-launcher-repair';receipt.mkdir(exist_ok=False)
(receipt/'original-deployment.json').write_bytes((root/'deployment.json').read_bytes())
(receipt/'original-driver.py').write_bytes((root/{name!r}).read_bytes())
log.rename(receipt/'failed-before-native.console.log')
payload=base64.b64decode({base64.b64encode(data).decode()!r})
assert hashlib.sha256(payload).hexdigest()=={new_hash!r}
(root/{name!r}).write_bytes(payload)
(root/'deployment.json').write_text(json.dumps({updated!r},indent=2))
test="import io,hashlib; from tools.resume_aes_storage_checkpoint import sha256_file_digest_compat; data=bytes(range(256))*8193; assert hashlib.file_digest(io.BytesIO(data),'sha256').hexdigest()==hashlib.sha256(data).hexdigest(); print('Python3.10 streamed SHA256 verified')"
smoke=subprocess.run(['python3','-B','-c',test],cwd=root,capture_output=True,text=True);assert smoke.returncode==0,smoke.stderr
argv=['env','PYTHONPATH='+str(root.parent/'python')+':'+str(root),'PYTHONUNBUFFERED=1','python3','-B',{name!r},'--parent-archive',str(parent),'--archive-sha256',{archive['archive_sha256']!r},'--output','runs/server-core-02','--runtime',str(root.parent/'portable-runtime-v1')]
command=shlex.join(argv)+' > server-core-02.console.log 2>&1'
result=subprocess.run(['tmux','new-session','-d','-s','aes-p1-v5d-core-compat','-c',str(root),command],capture_output=True,text=True);assert result.returncode==0,result.stderr
audit={{'old_driver_sha256':{old_hash!r},'new_driver_sha256':{new_hash!r},'native_stages_previously_started':False,'native_commands_changed':False,'scope':'Missing Python3.10 SHA256 file_digest API only','smoke':smoke.stdout.strip(),'created_at':time.time(),'session':'aes-p1-v5d-core-compat','p1_accepted':False}}
(receipt/'audit.json').write_text(json.dumps(audit,indent=2));print(json.dumps(audit))
'''
    p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','eda-backup','python3 -B -'],input=code,capture_output=True,text=True,encoding='utf-8',timeout=90)
    if p.returncode:raise RuntimeError(p.stderr)
    audit=json.loads(p.stdout)
    (OUT/'v5d-deployment-before-python310.json').write_text(json.dumps(original,indent=2))
    (OUT/'v5d-deployment.json').write_text(json.dumps(updated,indent=2))
    (OUT/'v5d-python310-repair.json').write_text(json.dumps(audit,indent=2));print(json.dumps(audit))
if __name__=='__main__':main()
