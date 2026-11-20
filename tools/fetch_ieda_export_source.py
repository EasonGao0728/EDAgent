"""Fetch only the public iDB source slice, pinned to a Git commit.

Extract complete members from the interrupted codeload archive, then retrieve
missing files from raw.githubusercontent.com and verify every Git blob hash.
No private build tree is consulted.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
COMMIT='65c39fd28aa0dc0cdd56325df07f6e440069061b'
DEST=ROOT/'third_party/ieda-public-idb'
prefixes=('src/database/','src/utility/','src/third_party/lefdef/')
tree=subprocess.check_output(['git','-C',str(ROOT/'third_party/ieda-export-src'),'ls-tree','-r',COMMIT],text=True)
files={}
for line in tree.splitlines():
    head,name=line.split('\t',1)
    if name.startswith(prefixes) or name=='LICENSE':
        mode,kind,sha=head.split()
        if kind=='blob' and mode=='100644':files[name]=sha
DEST.mkdir(exist_ok=True)
archive=ROOT/'.cache/ieda-public-full.tar.gz'
if archive.exists():
    extracted=0
    try:
        with tarfile.open(archive,'r|gz') as t:
            for member in t:
                rel='/'.join(member.name.split('/')[1:])
                if rel not in files or not member.isfile():continue
                data=t.extractfile(member).read()
                if hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=files[rel]:continue
                p=DEST/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);extracted+=1
    except (tarfile.TarError,EOFError,OSError) as exc:
        print('Partial archive ended: '+type(exc).__name__,flush=True)
    print('Verified archive members: '+str(extracted),flush=True)
def fetch(item):
    rel,sha=item;p=DEST/rel
    def valid(data):return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==sha
    if p.exists() and valid(p.read_bytes()):return rel
    for attempt in range(4):
        try:
            with urllib.request.urlopen('https://raw.githubusercontent.com/OSCC-Project/iEDA/'+COMMIT+'/'+rel,timeout=35) as r:data=r.read()
            if not valid(data):raise ValueError('Git object digest mismatch: '+rel)
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return rel
        except Exception:
            if attempt==3:raise
            time.sleep(attempt+1)
with ThreadPoolExecutor(max_workers=4) as pool:
    for i,name in enumerate(pool.map(fetch,files.items()),1):
        if i%50==0:print(f'Checked {i}/{len(files)}',flush=True)
(DEST/'source-manifest.json').write_text(json.dumps({'source':'https://github.com/OSCC-Project/iEDA','commit':COMMIT,'git_blob_sha1':files},indent=2))
print('VERIFIED '+str(len(files)),flush=True)
