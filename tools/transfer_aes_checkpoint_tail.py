"""Continue one verified partial upload; no retries or native job launch."""
import hashlib,json,shlex,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'runs/aes-p1-20261108'
archive=OUT/'v5b-server-legacy-01.tar.gz'
offset=123867136
prefix='7c3db36c13fa00cdb2da4cf32a44b15acba19b5a7a840ca4a358a851ad83a8c6'
expected='d80939d0a02721cf540b6a3a0a39c4d749911c67d31371403ec7b92226b3309c'
with archive.open('rb') as f:
    assert hashlib.sha256(f.read(offset)).hexdigest()==prefix
assert hashlib.sha256(archive.read_bytes()).hexdigest()==expected
code=f'''import pathlib,os,sys,hashlib,json
assert os.getuid()==1015
root=pathlib.Path('/srv/edagent/aes-p1-20261108-v5c');p=root/'checkpoint-parent.partial';target=root/'checkpoint-parent.tar.gz'
assert root.resolve()==root and not p.is_symlink() and not target.exists()
assert p.stat().st_size=={offset} and hashlib.sha256(p.read_bytes()).hexdigest()=={prefix!r}
count={offset}
with p.open('ab') as out:
    while True:
        data=sys.stdin.buffer.read(1024*1024)
        if not data:break
        count+=len(data);assert count<={archive.stat().st_size}
        out.write(data)
assert count=={archive.stat().st_size} and hashlib.sha256(p.read_bytes()).hexdigest()=={expected!r}
p.rename(target)
print(json.dumps({{'transfer_verified':True,'bytes':count,'archive_sha256':{expected!r},'continued_from':{offset},'native_job_started':False}}),flush=True)
'''
with archive.open('rb') as incoming:
    incoming.seek(offset)
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','eda-worker',
                           'python3 -B -c '+shlex.quote(code)],stdin=incoming,capture_output=True,
                          text=True,encoding='utf-8',timeout=1200,check=True)
record=json.loads(result.stdout);record['time']=time.time()
(OUT/'checkpoint-transfer-receipt.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps(record),flush=True)
