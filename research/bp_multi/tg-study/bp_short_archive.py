"""Losslessly archive large experimental controls after the candidate has been delivered."""
from bp_short_study import *
def run():
    manifest=read(WORK/'delivery/manifest.json')
    if manifest['parent']!=digest(ORIGINAL):raise ValueError('Parent mismatch')
    ledger=[]
    for arm in ('pre','control','forest-pre','forest-post','trial'):
        folder=WORK/arm;receipt=read(folder/'receipt.json')
        files=[(folder/'result/report/violations.json',receipt['markers'])]
        if arm!='trial':files.append((folder/'input.def',receipt['input']))
        for path,expected in files:
            archived=path.with_name(path.name+'.gz')
            if path.exists():
                if digest(path)!=expected:raise ValueError('Input checksum mismatch')
                tmp=archived.with_suffix('.partial')
                with path.open('rb') as src,gzip.open(tmp,'wb',compresslevel=1) as out:shutil.copyfileobj(src,out)
                h=hashlib.sha256()
                with gzip.open(tmp,'rb') as f:
                    for b in iter(lambda:f.read(1<<20),b''):h.update(b)
                if h.hexdigest()!=expected:raise ValueError('Archive verification failed')
                tmp.replace(archived);size=path.stat().st_size;path.unlink()
                ledger.append(dict(path=str(path.relative_to(WORK)),sha256=expected,bytes=size,compressed=archived.stat().st_size))
    if ledger:save(WORK/'archive.json',ledger)
if __name__=='__main__':run()
