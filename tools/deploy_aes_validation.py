"""Deploy a frozen, personal AES validation checkout; no shared writes."""
import argparse,hashlib,json,subprocess,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/aes-p1-20261108'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def deploy(profile='v5b',refresh=False):
    remote='/srv/edagent/aes-p1-20261108-'+profile
    archive=OUT/(profile+'-launch.tar.gz')
    if profile in ('v5c','v5d') and archive.exists():raise ValueError('Refuse frozen source archive overwrite')
    selected=list((ROOT/'macro_agent').glob('*.py'))+[ROOT/'tools/run_aes_baseline.py']
    for case in ('aes_sky130_t','aes_legacy','aes_core_sky130_t'):
        selected+=list((ROOT/'cases/ibench'/case).rglob('*'))
    selected += [ROOT/'environments/ieda-export/bin/ieda-idb-export',ROOT/'environments/ieda-export/runtime-manifest.json',ROOT/'environments/ieda-aes-router/manifest.json']
    selected=sorted(set(p for p in selected if p.is_file()))
    sources={p.relative_to(ROOT).as_posix():p for p in selected}
    if profile=='v5d':
        for name in ('resume_aes_storage_checkpoint.py','resume_aes_gds_checkpoint.py'):
            sources['tools/'+name]=ROOT/'tools'/name
    if profile=='v5c':
        from resume_aes_gds_checkpoint import CHECKER,OLD,NEW
        candidate=ROOT/'.cache/gds-validator-candidate/native_gds.py'
        if sha(ROOT/CHECKER)!=OLD or sha(candidate)!=NEW:raise ValueError('Unreviewed GDS checker candidate')
        sources[CHECKER]=candidate
        sources['tools/resume_aes_gds_checkpoint.py']=ROOT/'tools/resume_aes_gds_checkpoint.py'
    hashes={rel:sha(p) for rel,p in sources.items()}
    manifest=OUT/(profile+'-deployment.json')
    manifest.write_text(json.dumps({'remote_root':remote,'files':hashes,'profile':profile,
        'validation_override':{'file':CHECKER,'old':OLD,'new':NEW} if profile=='v5c' else None},indent=2),encoding='utf-8')
    with tarfile.open(archive,'w:gz') as t:
        for rel,p in sources.items():t.add(p,arcname=rel,recursive=False)
        t.add(manifest,arcname='deployment.json')
    upload='aes-'+profile+'-upload.tar.gz'
    subprocess.run(['scp','-q','-o','BatchMode=yes','-o','ConnectTimeout=15',str(archive),'eda-worker:/srv/edagent/'+upload],check=True,timeout=180)
    code=f'''import hashlib,json,tarfile,pathlib,subprocess,os
assert os.getuid()==1015
root=pathlib.Path({remote!r});archive=root.parent/{upload!r}
assert hashlib.sha256(archive.read_bytes()).hexdigest()=={sha(archive)!r}
refresh={refresh!r}
if root.exists():
    assert refresh and not (root/'runs').exists(), 'Refuse to overwrite any started deployment'
    old=json.loads((root/'deployment.json').read_text())
    for rel,h in old['files'].items():assert hashlib.sha256((root/rel).read_bytes()).hexdigest()==h,rel
else:root.mkdir()
with tarfile.open(archive) as t:
    for m in t.getmembers():
        p=(root/m.name).resolve()
        assert p.is_relative_to(root) and m.isfile(), 'Unsafe archive member'
    t.extractall(root)
d=json.loads((root/'deployment.json').read_text())
for rel,h in d['files'].items():assert hashlib.sha256((root/rel).read_bytes()).hexdigest()==h,rel
binary=pathlib.Path('/srv/benchmarks/iBench/benchmarks/tools/runtime_snapshots_v2/iEDA-a4f0682fd0fd7c19/iEDA')
assert hashlib.sha256(binary.read_bytes()).hexdigest()=='9f6c91ac6a58a00feaa63ba5eef37cfd240a4b60dd1fedba0654439763a3a6f8'
link=root/'environments/ieda-aes-router/iEDA'
if link.exists():assert link.is_symlink() and link.resolve()==binary
else:link.symlink_to(binary)
(root/'environments/ieda-export/bin/ieda-idb-export').chmod(0o755)
archive.unlink()
print(json.dumps({{'root':str(root),'files_verified':len(d['files']),'uploaded_archive_removed':True,'router_shared_readonly':str(binary)}}))
'''
    p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','eda-worker','python3 -B -'],input=code,text=True,encoding='utf-8',capture_output=True,timeout=60,check=True)
    print(p.stdout);(OUT/(profile+'-deploy-receipt.json')).write_text(p.stdout,encoding='utf-8')
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--profile',choices=['v5b','v5c','v5d'],default='v5b');ap.add_argument('--refresh-unstarted',action='store_true');args=ap.parse_args()
    deploy(args.profile,args.refresh_unstarted)
