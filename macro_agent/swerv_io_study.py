"""Fixed server study: IO-coordinate proof and corrected no-hold macro arms."""
from pathlib import Path
import json,os,re,shutil,subprocess,sys,time
from .swerv_screening import ROOT,PARENT,active_jobs,metrics,historical_seed
from .def_io_compat import write_equivalent,equivalent,execute
JOB='swerv-io-fixed-nohold-20261115-v3';OUT=ROOT/'runs'/JOB
NETS=('ib2d_bit_1120','ib2d_bit_563','ib2d_bit_141','ib2d_bit_157','ib2d_bit_1353')

def save(r):
    p=OUT/'receipt.json';t=p.with_suffix('.tmp');t.write_text(json.dumps(r,indent=2));os.replace(t,p)

def report_probe(b,w,ref,m):
    from .portable_ieda import ENV,IMAGE
    script=b.script('export_def',m)
    # report_route crashes on the unrouted snapshot. Keep its failed evidence;
    # use the proven readback path here, and audit real placement HPWL below.
    (w/'probe.tcl').write_text(script)
    args=b.rt.docker()+['run','--rm','--pull=never','--name','aieda-io-proof-'+w.name.replace('_','-'),'--network','none','--cpus','4','--memory','8g','--pids-limit','256','--ulimit','core=0','--ulimit','fsize=1073741824',
        '--mount',f'type=bind,source={ref},target=/reference,readonly','--mount',f'type=bind,source={w},target=/work','--workdir','/work']
    for k,v in ENV.items():args+=['--env',k+'='+str(v)]
    args += [IMAGE,'timeout','--kill-after=5','90','iEDA','-script','/work/probe.tcl']
    t=time.time()
    with (w/'logs/probe.log').open('w') as log:p=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,timeout=105)
    if p.returncode:raise ValueError('Native IO probe failed: '+w.name)
    if not equivalent(w/'result/placement.def',w/'result/export_def.def'):raise ValueError('IO probe changed physical DEF')
    return {'seconds':time.time()-t,'geometry_unchanged':True,'routing_executed':False,
            'metric_probe_available':False,'note':'readback only; native metric agreement checked on new placement outputs'}

def run():
    from .remote_platform import install
    task=install()
    from . import swerv_backend as b
    os.environ['AIEDA_NATIVE_HANDLES']=str(OUT/'handles');(OUT/'handles').mkdir(exist_ok=True)
    with task.locked(ROOT/'scheduler'):
        r=json.loads((OUT/'receipt.json').read_text());r.update(status='running',started_at=time.time(),stages=[],results={});save(r)
        try:
            if active_jobs():raise ValueError('SERVER_BUSY')
            parent=ROOT/'runs'/PARENT;s=json.loads((parent/'task.json').read_text());task.verify_refs(s['input_refs'])
            ref=ROOT/'cases/ibench/swerv_nangate45';m=b.manifest(ref)
            frozen={str(p):b.sha(p) for p in [parent/'task.json',parent/'final.def',*[Path(s['results'][k]['artifact']) for k in ('placement','macro_placement','floorplan')],*ref.rglob('*')] if p.is_file()}
            r.update(frozen_inputs=frozen,production_modified=False,hold_executed=False,routing_executed=False,
                     budget={'cpu':4,'address_space_gib':8,'campaign_seconds':1800},adapter_sha256=b.sha(Path(__file__).with_name('def_io_compat.py')));save(r)
            def prepared(label):
                w=OUT/label;w.mkdir();b.setup(w,ref);return w
            for label,fix in [('proof_explicit_port',False),('proof_implicit_port',True)]:
                w=prepared(label);src=Path(s['results']['placement']['artifact'])
                if fix:write_equivalent(src,w/'result/placement.def')
                else:shutil.copyfile(src,w/'result/placement.def')
                r['results'][label]=report_probe(b,w,ref,m);save(r)
            r['io_syntax_readback_verified']=True;save(r)
            for label in ('imp_fixed','shelf_fixed'):
                w=prepared(label)
                if label=='imp_fixed':
                    shutil.copyfile(s['results']['floorplan']['artifact'],w/'result/floorplan.def')
                    stages=['macro_placement']
                else:
                    r['shelf_seed']=historical_seed(s['results']['macro_placement']['artifact'],w/'result/macro_placement.def',m)
                    stages=[]
                stages+=['fanout','placement','export_def','cts','to_drv','legalization','timing']
                for stage in stages:
                    if time.time()-r['started_at']>1600:raise TimeoutError('Campaign budget')
                    if stage=='legalization':shutil.copyfile(w/'result/to_drv.def',w/'result/to_hold.def')
                    if stage=='timing':shutil.copyfile(w/'result/legalization.def',w/'result/filler.def')
                    v=execute(stage,w,ref)
                    r['stages'].append({'candidate':label,'stage':stage,'seconds':v.get('seconds'),'passed':v.get('passed')});save(r)
                    if stage=='placement':
                        shutil.copyfile(w/'result/pl/report/place_summary.json',w/'placement-summary-preserved.json')
                r['results'][label]={'hold_insertions':0,'metrics':metrics(w/'result/legalization.def',ref,m),
                    'placement_metrics':metrics(w/'result/placement.def',ref,m),
                    'native_placement_summary':json.loads((w/'placement-summary-preserved.json').read_text()),
                    'timing_report':(w/'result/timing/swerv_wrapper.rpt').read_text(),
                    'stage_evidence':{stage:json.loads((w/(stage+'-evidence.json')).read_text()) for stage in stages}}
                save(r)
            if any(b.sha(Path(p))!=h for p,h in frozen.items()):raise ValueError('Parent/input changed')
            r.update(status='completed',finished_at=time.time(),frozen_inputs_unchanged=True)
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
        p=subprocess.run(['tmux','new-session','-d','-s',JOB,f'cd {ROOT} && exec /usr/bin/timeout --kill-after=5 1800 python3 -B -m macro_agent.swerv_io_study worker'],capture_output=True,text=True,timeout=10)
        if p.returncode:r.update(status='failed',error=p.stderr);save(r)
        return r

if __name__=='__main__':
    if sys.argv[1:]==['worker']:run()
    else:
        try:print(json.dumps({'ok':True,'value':dispatch(json.load(sys.stdin)['operation'])}))
        except Exception as exc:print(json.dumps({'ok':False,'error':str(exc)}));sys.exit(1)
