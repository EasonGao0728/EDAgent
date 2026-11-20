"""Deploy curated code/assets to the user's own server directory, hash verified.

No credentials or historical task folders are uploaded. Existing authorized
read-only case assets are reused by content hash, never by assumed equivalence.
"""
from pathlib import Path
import base64,gzip,hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from macro_agent.remote_client import config


def ssh(code,payload,timeout=180):
    import shlex
    command='python3 -B -c '+shlex.quote(code)
    p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12',config()['ssh_host'],command],
        input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=timeout)
    if p.returncode:raise RuntimeError(p.stderr[-3000:])
    return json.loads(p.stdout)


def files():
    from macro_agent.ieda_stages import REGISTERED_CASES,input_files
    paths=set(ROOT.joinpath('macro_agent').glob('*.py'))
    paths.update(ROOT.joinpath('dsh/knowledge').glob('*.md'))
    for k in REGISTERED_CASES:
        ref,_=REGISTERED_CASES[k];paths.update(input_files(k))
        for extra in ('design.json','benchmark_package.json'):
            if (ref/extra).exists():paths.add(ref/extra)
        if k=='sky130_sram_pair':paths.add(ref/'tools/hmetis2.0pre1') if (ref/'tools/hmetis2.0pre1').exists() else None
    paths.update([ROOT/'tools'/x for x in ('audit_aes_drivers.py','revalidate_aes_baseline.py','resume_aes_gds_checkpoint.py')])
    paths.update(ROOT.joinpath('environments/ieda-export').glob('*.json'))
    paths.update(ROOT.joinpath('environments/ieda-aes-router').glob('*.json'))
    paths.update([ROOT/'environments/remote-server.json',ROOT/'environments/ieda-aes-router/iEDA',ROOT/'environments/ieda-export/bin/ieda-idb-export'])
    data={p.relative_to(ROOT).as_posix():p.read_bytes() for p in paths}
    # Platform spelling only, exported binary identity remains unchanged.
    key='environments/ieda-export/runtime-manifest.json';m=json.loads(data[key]);m['executable']=m['executable'].replace('\\','/')
    data[key]=json.dumps(m,ensure_ascii=False,indent=2).encode()
    for p in (ROOT/'.cache/aes-qualification').glob('*.json'):
        r=json.loads(p.read_bytes());e=Path(r['evidence']['path']);rel='qualification-evidence/'+p.stem+'.json'
        for relative,expected in r['input_sha256'].items():
            source=ROOT/'cases/ibench'/p.stem/relative;payload=source.read_bytes()
            if hashlib.sha256(payload).hexdigest()!=expected:raise ValueError('Qualified case changed: '+str(source))
            data[source.relative_to(ROOT).as_posix()]=payload
        for relative,expected in r['implementation_sha256'].items():
            source=(ROOT/relative).resolve()
            if not source.is_relative_to(ROOT) or source.suffix!='.py' or source.relative_to(ROOT).parts[0] not in ('macro_agent','tools'):
                raise ValueError('Unreviewed qualification source')
            payload=source.read_bytes()
            if hashlib.sha256(payload).hexdigest()!=expected:raise ValueError('Qualified source changed: '+str(source))
            data[source.relative_to(ROOT).as_posix()]=payload
        data[rel]=e.read_bytes();r['evidence']['path']=config()['server_root']+'/'+rel
        data[p.relative_to(ROOT).as_posix()]=json.dumps(r,indent=2).encode()
    for p in (ROOT/'.cache/tool-verification').glob('ieda_*.json'):
        r=json.loads(p.read_bytes());e=Path(r['evidence']['path']);rel='qualification-evidence/tool-'+p.stem+'.json'
        data[rel]=e.read_bytes();r['evidence']['path']=config()['server_root']+'/'+rel
        r['source_scope']='Preserved algorithm/build evidence; remote transport acceptance recorded separately'
        data[p.relative_to(ROOT).as_posix()]=json.dumps(r,indent=2).encode()
    return data


PREPARE=r'''
import sys,json,pathlib,hashlib,os,shutil
r=json.load(sys.stdin);base=pathlib.Path('/srv/edagent');root=base/'main-agent-remote-v1'
assert os.getuid()==1015
root.mkdir(exist_ok=True)
for p in root.glob('runs/*/jobs/*.json'):
    if json.loads(p.read_text())['status'] not in ('completed','failed','cancelled','lost'):raise ValueError('Active remote job; deployment refused')
index={};wanted={(v['bytes'],pathlib.Path(k).name) for k,v in r.items()}
sources=[base/'aes-p1-20261108-v5c',base/'aes-p1-20261108-v5d',base/'portable-baseline-20261105']
sources += [pathlib.Path('/srv/benchmarks/iBench/benchmarks')]
def scan(top):
    for current,dirs,names in os.walk(top):
        dirs[:]=[d for d in dirs if d not in ('runs','.git','__pycache__','result','results','build')]
        for name in names:
            p=pathlib.Path(current)/name
            if p.is_symlink():continue
            if (p.stat().st_size,name) in wanted:
                h=hashlib.sha256(p.read_bytes()).hexdigest();index.setdefault(h,p)
missing=[];reused=0
for source in sources:
    if source.exists():scan(source)
for rel,ref in r.items():
    p=root/rel
    if not p.resolve().is_relative_to(root) or '..' in pathlib.Path(rel).parts:raise ValueError('Invalid deployment path')
    if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==ref['sha256']:continue
    if ref['sha256'] in index:
        p.parent.mkdir(parents=True,exist_ok=True)
        # Copy, never mutate/hardlink shared source data.
        shutil.copyfile(index[ref['sha256']],p);reused+=1
    else:missing.append(rel)
print(json.dumps({'missing':missing,'reused':reused}))
'''
WRITE=r'''
import sys,json,pathlib,hashlib,os,base64,gzip
assert os.getuid()==1015
root=pathlib.Path('/srv/edagent/main-agent-remote-v1');r=json.load(sys.stdin)
for rel,v in r.items():
    p=root/rel
    if not p.resolve().is_relative_to(root) or '..' in pathlib.Path(rel).parts:raise ValueError('Bad path')
    data=gzip.decompress(base64.b64decode(v['data']))
    if hashlib.sha256(data).hexdigest()!=v['sha256']:raise ValueError('Hash mismatch')
    p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.deploy');tmp.write_bytes(data);tmp.replace(p)
    if p.name in ('iEDA','ieda-idb-export','hmetis2.0pre1'):p.chmod(0o700)
print(json.dumps({'written':len(r)}))
'''
VERIFY=r'''
import sys,json,pathlib,hashlib,os
root=pathlib.Path('/srv/edagent/main-agent-remote-v1');refs=json.load(sys.stdin)
errors=[]
for rel,r in refs.items():
    p=root/rel
    if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=r['sha256']:errors.append(rel)
    elif p.name in ('iEDA','ieda-idb-export','hmetis2.0pre1'):p.chmod(0o700)
if errors:raise ValueError(str(errors))
(root/'deployment-manifest.json').write_text(json.dumps(refs,indent=2))
print(json.dumps({'verified_files':len(refs),'server_root':str(root),'uid':os.getuid()}))
'''


if __name__=='__main__':
    data=files();manifest={k:{'sha256':hashlib.sha256(v).hexdigest(),'bytes':len(v)} for k,v in data.items()}
    p=ssh(PREPARE,manifest,300);print(json.dumps({'reused':p['reused'],'missing':len(p['missing'])}),flush=True)
    batch={};size=0
    for name in p['missing']:
        compressed=base64.b64encode(gzip.compress(data[name])).decode()
        batch[name]={'data':compressed,'sha256':manifest[name]['sha256']};size+=len(compressed)
        if size>600000:
            print(ssh(WRITE,batch,300),flush=True);batch={};size=0
    if batch:print(ssh(WRITE,batch,300),flush=True)
    result=ssh(VERIFY,manifest,180);print(json.dumps(result),flush=True)
    out=ROOT/'runs/remote-migration-20261111';out.mkdir(exist_ok=True)
    (out/'deployment.json').write_text(json.dumps({'result':result,'files':manifest},indent=2),encoding='utf-8')
