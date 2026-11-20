"""Download, verify, then optionally prune only a completed personal AES run."""
import argparse,hashlib,json,subprocess,tarfile,shutil,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'runs/aes-p1-20261108'
HOST='eda-worker'
def ssh(code):
    p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15',HOST,'python3 -B -'],input=code,text=True,encoding='utf-8',capture_output=True,timeout=60)
    if p.returncode:raise RuntimeError(p.stderr)
    return json.loads(p.stdout)
def main():
    global HOST
    ap=argparse.ArgumentParser();ap.add_argument('--profile',choices=['v1','v3','v4','v5','v5b','v5c','v5d'],required=True);ap.add_argument('--run',choices=['server-cipher-02','server-cipher-01','server-legacy-01','server-legacy-02','server-core-01','server-core-02'],required=True);ap.add_argument('--cleanup',action='store_true');ap.add_argument('--host',choices=['eda-worker','eda-backup'],default='eda-worker');a=ap.parse_args();HOST=a.host
    project='/srv/edagent/aes-p1-20261108'+('-'+a.profile if a.profile!='v1' else '')
    remote=project+'/runs/'+a.run
    snapshot='''import pathlib,json,hashlib
p=pathlib.Path(REMOTE)
assert p.resolve()==p and p.is_relative_to(pathlib.Path(PROJECT)/'runs') and not p.is_symlink()
assert not (p/'archive-receipt.json').exists(),'Already archived'
r=json.loads((p/'run.json').read_text());assert r['status'] in ('failed','passed'),r['status']
files={}
for f in sorted(p.rglob('*')):
    assert not f.is_symlink(),str(f)
    if f.is_file():files[f.relative_to(p).as_posix()]=hashlib.sha256(f.read_bytes()).hexdigest()
'''.replace('REMOTE',repr(remote)).replace('PROJECT',repr(project))
    meta=ssh(snapshot+"print(json.dumps({'files':files,'status':r['status'],'bytes':sum(f.stat().st_size for f in p.rglob('*') if f.is_file())}))")
    name=a.profile+'-'+a.run;archive=OUT/(name+'.tar.gz');partial=archive.with_suffix('.partial')
    if archive.exists():raise ValueError('Refuse archive overwrite: '+str(archive))
    with partial.open('wb') as f:
        p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15',HOST,'tar','czf','-','-C',project+'/runs',a.run],stdout=f,stderr=subprocess.PIPE,timeout=900)
    if p.returncode:raise RuntimeError(p.stderr.decode(errors='replace'))
    files={};destination=OUT/'downloaded'/a.profile
    with tarfile.open(partial) as t:
        for member in t.getmembers():
            target=(destination/member.name).resolve()
            assert target.is_relative_to(destination.resolve()) and (member.isdir() or member.isfile()),member.name
            if member.isfile():
                rel=Path(member.name).relative_to(a.run).as_posix()
                with t.extractfile(member) as stream:
                    files[rel]=hashlib.file_digest(stream,'sha256').hexdigest()
        assert files==meta['files'],'Downloaded archive differs from server snapshot'
        assert not (destination/a.run).exists(),'Refuse extraction overwrite'
        # Bound temporary disk use: independently extract and hash each file,
        # then losslessly compress large files before extracting the next one.
        # Never hardlink a completed evidence archive to a writable task.
        import sys
        sys.path.insert(0,str(ROOT))
        from macro_agent.main_task import compact_verified
        for member in t.getmembers():
            target=destination/member.name
            if member.isdir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            if shutil.disk_usage(destination).free<member.size+256*1024**2:
                raise OSError('Insufficient disk space for verified archive extraction')
            with t.extractfile(member) as source,target.open('xb') as output:
                shutil.copyfileobj(source,output,1024*1024)
            with target.open('rb') as stream:
                assert hashlib.file_digest(stream,'sha256').hexdigest()==files[Path(member.name).relative_to(a.run).as_posix()]
            compact_verified(target)
            os.utime(target,(member.mtime,member.mtime))
    partial.replace(archive)
    receipt={'remote':remote,'archive':str(archive),'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'verified_files':len(files),'source_bytes':meta['bytes'],'status':meta['status'],'cleanup':False}
    if a.cleanup:
        code=snapshot+f'''assert files=={meta['files']!r},'Server run changed after download'
import shutil
saved=(p/'run.json').read_bytes()
shutil.rmtree(p)
p.mkdir();(p/'run.json').write_bytes(saved)
receipt={receipt!r};receipt['cleanup']=True
(p/'archive-receipt.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps({{'cleanup':True,'remaining_bytes':sum(f.stat().st_size for f in p.iterdir() if f.is_file())}}))
'''
        receipt.update(ssh(code))
    (OUT/(name+'-archive-receipt.json')).write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt))
if __name__=='__main__':main()
