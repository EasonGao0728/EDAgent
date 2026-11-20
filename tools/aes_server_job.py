"""Launch or inspect only this task's personal, bounded tmux AES jobs."""
import argparse,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CASES={'aes_sky130_t':'cipher','aes_legacy':'legacy','aes_core_sky130_t':'core'}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['start','status']);ap.add_argument('--case',choices=CASES,default='aes_sky130_t');ap.add_argument('--compact',action='store_true');ap.add_argument('--profile',choices=['v5b','v5c'],default='v5b');ap.add_argument('--host',choices=['eda-worker','eda-backup']);a=ap.parse_args()
    host=a.host or ('eda-backup' if a.profile=='v5c' else 'eda-worker')
    short=CASES[a.case]
    run_name='server-'+short+('-02' if a.profile=='v5c' and short=='legacy' else '-01')
    if a.action=='start' and a.profile=='v5c' and short=='legacy':raise ValueError('Use the reviewed checkpoint launcher for legacy v5c')
    code=f'''import pathlib,json,hashlib,subprocess,shlex,time,re,os
assert os.getuid()==1015
base=pathlib.Path('/srv/edagent');root=base/('aes-p1-20261108-'+{a.profile!r})
case={a.case!r};short={short!r};action={a.action!r};run_name={run_name!r};session='aes-p1-'+{a.profile!r}+'-'+short
if action=='start':
    old=json.loads((base/'aes-p1-20261108/runs/server-cipher-02/run.json').read_text())
    assert old['status']!='running','Prior bounded run is still running; no overlap'
    for p in (base/'aes-p1-20261108-v3/runs').glob('*/run.json'):
        assert json.loads(p.read_text())['status']!='running','Prior v3 run is still running'
    for p in (base/'aes-p1-20261108-v4/runs').glob('*/run.json'):
        assert json.loads(p.read_text())['status']!='running','Prior v4 run is still running'
    for p in (base/'aes-p1-20261108-v5/runs').glob('*/run.json'):
        assert json.loads(p.read_text())['status']!='running','Prior v5 run is still running'
    for profile in ('v5b','v5c'):
        for p in (base/('aes-p1-20261108-'+profile)/'runs').glob('*/run.json'):
            assert json.loads(p.read_text())['status']!='running','Another case is running: '+str(p)
    d=json.loads((root/'deployment.json').read_text())
    for rel,h in d['files'].items():assert hashlib.sha256((root/rel).read_bytes()).hexdigest()==h,rel
    assert not (root/'runs'/run_name).exists()
    argv=['env','PYTHONPATH='+str(base/'python')+':'+str(root),'PYTHONUNBUFFERED=1','python3','-B','tools/run_aes_baseline.py','--case',case,'--output','runs/'+run_name,'--runtime',str(base/'portable-runtime-v1')]
    command=shlex.join(argv)+' > '+run_name+'.console.log 2>&1'
    r=subprocess.run(['tmux','new-session','-d','-s',session,'-c',str(root),command],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    receipt={{'root':str(root),'session':session,'case':case,'created_at':time.time(),'files_verified':len(d['files']),'router_sha256':hashlib.sha256((root/'environments/ieda-aes-router/iEDA').read_bytes()).hexdigest(),'policy':'4 CPU / 8 GiB / routing 21600 s / other stages 1800 s / task 32400 s; serial cases'}}
    (root/('launch-'+short+'.json')).write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
else:
    p=root/'runs'/run_name;r=json.loads((p/'run.json').read_text())
    last=r['stages'][-1] if r['status']!='running' and r['stages'] else None
    if last and {a.compact!r}:last={{k:last.get(k) for k in ('stage','passed','returncode','timed_out','seconds')}}
    print(json.dumps({{'case':case,'status':r['status'],'completed':[s['stage'] for s in r['stages'] if s.get('passed')],'last':last,'error':r.get('error'),'bytes':sum(f.stat().st_size for f in p.rglob('*') if f.is_file()),'checked_at':time.time()}}))
    logs=sorted((p/'logs').glob('*.log'),key=lambda f:f.stat().st_mtime)
    if logs and logs[-1].name=='routing.log' and (p/'result/rt/rt.log').is_file():logs[-1]=p/'result/rt/rt.log'
    if logs:
        text=logs[-1].read_text(errors='replace')
        if {a.compact!r}:
            lines=re.sub(r'\\x1b\\[[0-9;]*m','',text).splitlines()[:-1]
            lines=[line for line in lines if re.search(r'Starting|Completed|Begin iteration|End iteration|Routed [0-9]',line)]
            print(logs[-1].name+'\\n'+'\\n'.join(lines[-2:]))
        else:print(logs[-1].name+'\\n'+text[-1500:])
    print(subprocess.run(['tmux','list-panes','-t',session,'-F','#{{pane_pid}} #{{pane_dead}}'],capture_output=True,text=True).stdout)
'''
    p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15',host,'python3 -B -'],input=code,text=True,encoding='utf-8',capture_output=True,timeout=45)
    output=p.stdout+p.stderr;print(output)
    folder=ROOT/'runs/aes-p1-20261108'
    (folder/(a.profile+'-'+short+'-'+a.action+'.txt')).write_text(output,encoding='utf-8')
    if p.returncode:raise SystemExit(p.returncode)
if __name__=='__main__':main()
