"""Frozen no-hold control: reuse iMP/CTS/DRV, no routing or production mutation."""
from pathlib import Path
import json,os,shutil,subprocess,sys,time
from .swerv_screening import ROOT,PARENT,active_jobs,metrics
JOB='swerv-no-hold-20261115-v1';OUT=ROOT/'runs'/JOB

def save(r):
    p=OUT/'receipt.json';t=p.with_suffix('.tmp');t.write_text(json.dumps(r,indent=2));os.replace(t,p)

def run():
    from .remote_platform import install
    task=install()
    from . import swerv_backend as b
    os.environ['AIEDA_NATIVE_HANDLES']=str(OUT/'handles');(OUT/'handles').mkdir(exist_ok=True)
    with task.locked(ROOT/'scheduler'):
        r=json.loads((OUT/'receipt.json').read_text());r.update(status='running',started_at=time.time(),native_stages=[]);save(r)
        try:
            if active_jobs():raise ValueError('SERVER_BUSY')
            parent=ROOT/'runs'/PARENT;s=json.loads((parent/'task.json').read_text());task.verify_refs(s['input_refs'])
            src=Path(s['results']['to_drv']['artifact']);ref=ROOT/'cases/ibench/swerv_nangate45';m=b.manifest(ref)
            frozen={str(p):b.sha(p) for p in (src,parent/'task.json',parent/'final.def')}
            w=OUT/'candidate';w.mkdir();b.setup(w,ref)
            # Dependency alias in a NEW candidate only, not a claim that hold ran.
            shutil.copyfile(src,w/'result/to_hold.def')
            r.update(frozen_inputs=frozen,source_sha256=b.sha(src),hold_executed=False,inserted_hold_buffers=0,
                factor='skip_hold_optimization',upstream_reused_through='to_drv',routing_executed=False,production_modified=False,
                baseline_geometry=metrics(src,ref,m),budget={'cpu':4,'address_space_gib':8,'wall_seconds':600});save(r)
            for stage in ('legalization','timing'):
                if stage=='timing':shutil.copyfile(w/'result/legalization.def',w/'result/filler.def')
                v=b.execute(stage,w,ref);r['native_stages'].append({'stage':stage,'seconds':v['seconds'],'evidence':v});save(r)
            r.update(metrics=metrics(w/'result/legalization.def',ref,m),
                timing_report=(w/'result/timing/swerv_wrapper.rpt').read_text(),
                result_def={'path':str(w/'result/legalization.def'),'sha256':b.sha(w/'result/legalization.def')},
                status='completed',finished_at=time.time(),frozen_inputs_unchanged=all(b.sha(Path(p))==h for p,h in frozen.items()))
            if not r['frozen_inputs_unchanged']:raise ValueError('Original artifact changed')
        except BaseException as exc:r.update(status='failed',error=repr(exc),finished_at=time.time())
        save(r)

def dispatch(op):
    from .remote_platform import install
    task=install()
    if op=='status':return json.loads((OUT/'receipt.json').read_text()) if (OUT/'receipt.json').exists() else {'status':'not_started','job_id':JOB}
    if op!='start':raise ValueError('Unsupported operation')
    with task.locked(ROOT/'scheduler'):
        if (OUT/'receipt.json').exists():return dispatch('status')
        if active_jobs():raise ValueError('SERVER_BUSY')
        OUT.mkdir();r={'job_id':JOB,'status':'queued','created_at':time.time()};save(r)
        p=subprocess.run(['tmux','new-session','-d','-s',JOB,f'cd {ROOT} && exec /usr/bin/timeout --kill-after=5 600 python3 -B -m macro_agent.swerv_no_hold worker'],capture_output=True,text=True,timeout=10)
        if p.returncode:r.update(status='failed',error=p.stderr);save(r)
        return r

if __name__=='__main__':
    if sys.argv[1:]==['worker']:run()
    else:
        try:print(json.dumps({'ok':True,'value':dispatch(json.load(sys.stdin)['operation'])}))
        except Exception as exc:print(json.dumps({'ok':False,'error':str(exc)}));sys.exit(1)
