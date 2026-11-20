"""Validate the archived parent locally, then launch the bounded server tail."""
import argparse, hashlib, importlib.util, json, shlex, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.resume_aes_gds_checkpoint import review, CHECKER, NEW, sha

OUT = ROOT / 'runs/aes-p1-20261108'
REMOTE = '/srv/edagent/aes-p1-20261108-v5c'
HOST = 'eda-worker'


def ssh(code):
    p = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', HOST, 'python3 -B -'],
                       input=code, capture_output=True, text=True, encoding='utf-8', timeout=60, check=True)
    return json.loads(p.stdout)


def main():
    archive = OUT / 'v5b-server-legacy-01.tar.gz'
    receipt = json.loads((OUT / 'v5b-server-legacy-01-archive-receipt.json').read_text(encoding='utf-8'))
    if receipt['status'] != 'failed' or sha(archive) != receipt['archive_sha256']:
        raise ValueError('Verified current failed parent archive required')
    parent = OUT / 'downloaded/v5b/server-legacy-01'
    reference = ROOT / 'cases/ibench/aes_legacy'
    # The native continuation uses the frozen server snapshot, not the desktop
    # controller, which may independently gain storage/recovery support.
    deployment = json.loads((OUT / 'v5c-deployment.json').read_text(encoding='utf-8'))
    current = {k:v for k,v in deployment['files'].items()
               if k.startswith('macro_agent/') and k.endswith('.py')}
    if current.get(CHECKER) != NEW:
        raise ValueError('Frozen server does not contain the reviewed checker')
    review(parent, reference, current)
    candidate = ROOT / '.cache/gds-validator-candidate/native_gds.py'
    if sha(candidate) != NEW:
        raise ValueError('Unreviewed candidate')
    spec = importlib.util.spec_from_file_location('macro_agent.native_gds_candidate', candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = json.loads((reference / 'manifest.json').read_text(encoding='utf-8'))
    checked = module.validate(parent / 'result/final.gds', parent / 'result/filler.def',
                              reference / manifest['tech_lef'], [reference / p for p in manifest['cell_lefs']])
    audit = {'time': time.time(), 'candidate_sha256': NEW, 'native_rerun': False,
             'parent_archive_sha256': receipt['archive_sha256'], 'validation': checked}
    (OUT / 'gds-legacy-candidate-validation.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    if checked['passed'] is not True:
        raise ValueError('Candidate does not independently validate the actual parent GDS')
    guard = f'''import pathlib,json,hashlib,os
assert os.getuid()==1015
root=pathlib.Path({REMOTE!r});base=root.parent
assert root.resolve()==root and not (root/'runs/server-legacy-02').exists()
for p in base.glob('aes-p1-20261108*/runs/*/run.json'):
    assert json.loads(p.read_text())['status']!='running','Another owned native job remains running'
d=json.loads((root/'deployment.json').read_text())
for rel,h in d['files'].items():assert hashlib.sha256((root/rel).read_bytes()).hexdigest()==h,rel
assert d['files']['tools/resume_aes_gds_checkpoint.py']=={sha(ROOT/'tools/resume_aes_gds_checkpoint.py')!r}
assert d=={deployment!r},'Remote deployment differs from the reviewed snapshot'
archive=root/'checkpoint-parent.tar.gz'
assert archive.is_file() and archive.resolve()==archive,'Verified checkpoint upload required before launch'
assert archive.stat().st_size=={archive.stat().st_size}
assert hashlib.sha256(archive.read_bytes()).hexdigest()=={receipt['archive_sha256']!r}
'''
    preflight = ssh(guard + "print(json.dumps({'preflight':True,'files_verified':len(d['files'])}))")
    code = guard + f'''
import subprocess,shlex,time
archive=root/'checkpoint-parent.tar.gz'
assert hashlib.sha256(archive.read_bytes()).hexdigest()=={receipt['archive_sha256']!r}
argv=['env','PYTHONPATH='+str(base/'python')+':'+str(root),'PYTHONUNBUFFERED=1','python3','-B',
      'tools/resume_aes_gds_checkpoint.py','--parent-archive',str(archive),'--archive-sha256',{receipt['archive_sha256']!r},
      '--output','runs/server-legacy-02','--runtime',str(base/'portable-runtime-v1')]
command=shlex.join(argv)+' > server-legacy-02.console.log 2>&1'
p=subprocess.run(['tmux','new-session','-d','-s','aes-p1-v5c-legacy','-c',str(root),command],capture_output=True,text=True)
assert p.returncode==0,p.stderr
print(json.dumps({{'created_at':time.time(),'session':'aes-p1-v5c-legacy','root':str(root),'execution_mode':'resumed_after_validation_only_fix','parent_archive_sha256':{receipt['archive_sha256']!r},'native_tail_pending':True,'p1_accepted':False}}))
'''
    result = ssh(code)
    result['preflight'] = preflight
    (OUT / 'v5c-legacy-start.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', choices=('eda-worker','eda-backup'), default='eda-worker')
    HOST = parser.parse_args().host
    main()
