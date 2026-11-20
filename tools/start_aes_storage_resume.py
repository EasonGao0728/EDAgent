"""Upload the verified Core archive once, then launch an owned serial tmux tail."""
import argparse,hashlib,json,shlex,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'runs/aes-p1-20261108'
REMOTE='/srv/edagent/aes-p1-20261108-v5d'
HOST='eda-worker'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def ssh(code,timeout=90):
    p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15',HOST,'python3 -B -'],input=code,text=True,encoding='utf-8',capture_output=True,timeout=timeout,check=True)
    return json.loads(p.stdout)
def main():
    global HOST
    ap=argparse.ArgumentParser();ap.add_argument('--resume-upload',action='store_true');ap.add_argument('--host',choices=('eda-worker','eda-backup'),default='eda-worker');args=ap.parse_args();HOST=args.host
    archive=OUT/'v5c-server-core-01.tar.gz';receipt=json.loads((OUT/'v5c-server-core-01-archive-receipt.json').read_text());deployment=json.loads((OUT/'v5d-deployment.json').read_text())
    if sha(archive)!=receipt['archive_sha256']:raise ValueError('Archive changed')
    guard=f'''import pathlib,json,hashlib,os,shutil
assert os.getuid()==1015
root=pathlib.Path({REMOTE!r});assert root.resolve()==root
assert not (root/'runs/server-core-02').exists()
for p in root.parent.glob('aes-p1-20261108*/runs/*/run.json'):
    assert json.loads(p.read_text())['status']!='running',str(p)
d=json.loads((root/'deployment.json').read_text());assert d=={deployment!r}
for rel,h in d['files'].items():assert hashlib.sha256((root/rel).read_bytes()).hexdigest()==h,rel
assert shutil.disk_usage(root).free>{receipt['source_bytes']}+{archive.stat().st_size}+512*1024**2,'Not enough server space'
'''
    preflight=ssh(guard+"print(json.dumps({'preflight':True,'files_verified':len(d['files'])}))")
    print(json.dumps(preflight),flush=True)
    upload=REMOTE+'/core-parent.partial'
    state=ssh(f"import pathlib,json,hashlib; p=pathlib.Path({upload!r}); q=p.with_name('core-parent.tar.gz'); assert p.resolve()==p; print(json.dumps({{'partial_exists':p.exists(),'complete_exists':q.exists(),'offset':p.stat().st_size if p.exists() else 0,'sha256':hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None}}))")
    if state['complete_exists']:raise ValueError('Completed upload already exists; inspect instead of relaunching')
    if state['partial_exists']:
        if not args.resume_upload:raise ValueError('Upload already exists; inspect instead of overwriting')
        offset=state['offset']
        if not 0<offset<=archive.stat().st_size:raise ValueError('Invalid partial upload size')
        h=hashlib.sha256();remaining=offset
        with archive.open('rb') as f:
            while remaining:
                block=f.read(min(1024*1024,remaining));h.update(block);remaining-=len(block)
        if h.hexdigest()!=state['sha256']:raise ValueError('Partial upload differs from local archive')
        code=f'''import pathlib,sys,hashlib,os
assert os.getuid()==1015
p=pathlib.Path({upload!r});assert p.resolve()==p and p.stat().st_size=={offset}
assert hashlib.sha256(p.read_bytes()).hexdigest()=={state['sha256']!r}
count={offset}
with p.open('ab') as f:
 while True:
  data=sys.stdin.buffer.read(1024*1024)
  if not data:break
  count+=len(data);assert count<={archive.stat().st_size};f.write(data)
assert count=={archive.stat().st_size}
assert hashlib.sha256(p.read_bytes()).hexdigest()=={receipt['archive_sha256']!r}
'''
        with archive.open('rb') as incoming:
            incoming.seek(offset)
            subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15',HOST,'python3 -B -c '+shlex.quote(code)],stdin=incoming,capture_output=True,timeout=3600,check=True)
    else:
        subprocess.run(['scp','-q','-o','BatchMode=yes','-o','ConnectTimeout=15',str(archive),HOST+':'+upload],check=True,timeout=3600)
    code=guard+f'''
import subprocess,shlex,time
p=root/'core-parent.partial';a=root/'core-parent.tar.gz'
assert p.resolve()==p and not a.exists() and p.stat().st_size=={archive.stat().st_size}
assert hashlib.sha256(p.read_bytes()).hexdigest()=={receipt['archive_sha256']!r}
p.rename(a)
argv=['env','PYTHONPATH='+str(root.parent/'python')+':'+str(root),'PYTHONUNBUFFERED=1','python3','-B','tools/resume_aes_storage_checkpoint.py','--parent-archive',str(a),'--archive-sha256',{receipt['archive_sha256']!r},'--output','runs/server-core-02','--runtime',str(root.parent/'portable-runtime-v1')]
command=shlex.join(argv)+' > server-core-02.console.log 2>&1'
p=subprocess.run(['tmux','new-session','-d','-s','aes-p1-v5d-core','-c',str(root),command],capture_output=True,text=True);assert p.returncode==0,p.stderr
print(json.dumps({{'created_at':time.time(),'session':'aes-p1-v5d-core','archive_sha256':{receipt['archive_sha256']!r},'native_tail_pending':True,'p1_accepted':False}}))
'''
    result=ssh(code);(OUT/'v5d-core-start.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
if __name__=='__main__':main()
