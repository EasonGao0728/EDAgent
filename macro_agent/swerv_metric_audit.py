"""Read-only native wirelength audit of two preserved placement DEFs."""
from pathlib import Path
import json,os,subprocess,sys,time
from .swerv_screening import ROOT,PARENT,active_jobs
JOB='swerv-metric-audit-20261115-v3'
OUT=ROOT/'runs'/JOB


def save(r):
    p=OUT/'receipt.json';t=p.with_suffix('.tmp');t.write_text(json.dumps(r,indent=2));os.replace(t,p)


def run():
    from .remote_platform import install
    task=install()
    from . import swerv_backend as b
    from .portable_ieda import ENV,IMAGE
    from .def_validation import read_def
    os.environ['AIEDA_NATIVE_HANDLES']=str(OUT/'handles');Path(os.environ['AIEDA_NATIVE_HANDLES']).mkdir(exist_ok=True)
    with task.locked(ROOT/'scheduler'):
        r=json.loads((OUT/'receipt.json').read_text());r.update(status='running',started_at=time.time(),results={});save(r)
        try:
            if active_jobs():raise ValueError('SERVER_BUSY')
            p=ROOT/'runs'/PARENT;s=json.loads((p/'task.json').read_text());task.verify_refs(s['input_refs'])
            ref=ROOT/'cases/ibench/swerv_nangate45';m=b.manifest(ref)
            sources={'imp':Path(s['results']['placement']['artifact']),
                     'shelf':ROOT/'runs/swerv-screening-20261115-v2/macro_shelf/result/placement.def'}
            frozen={str(f):b.sha(f) for f in [p/'task.json',p/'final.def',*sources.values()]}
            for label,src in sources.items():
                w=OUT/label;w.mkdir();b.setup(w,ref)
                import shutil
                shutil.copyfile(src,w/'result/placement.def')
                script=b.script('export_def',m)
                script=script.replace('def_save -path /work/result/export_def.def','init_pl -config /work/config/pl_default_config.json\nplacer_report\ndestroy_pl\ndef_save -path /work/result/export_def.def')
                (w/'audit.tcl').write_text(script)
                args=b.rt.docker()+['run','--rm','--pull=never','--name','aieda-metric-audit-'+label,'--network','none','--cpus','4','--memory','8g','--pids-limit','256','--ulimit','core=0','--ulimit','fsize=1073741824',
                    '--mount',f'type=bind,source={ref},target=/reference,readonly','--mount',f'type=bind,source={w},target=/work','--workdir','/work']
                for key,value in ENV.items():args+=['--env',key+'='+str(value)]
                args += [IMAGE,'timeout','--kill-after=5','90','iEDA','-script','/work/audit.tcl']
                start=time.time()
                with (w/'audit.log').open('w') as log:proc=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,timeout=105)
                if proc.returncode:raise ValueError('Native audit failed: '+label)
                report=w/'result/pl/report/summary_report.txt'
                if not report.is_file():raise ValueError('AUDIT_REPORT_MISSING: command exit success is insufficient')
                if read_def(src)!=read_def(w/'result/export_def.def'):raise ValueError('Audit did not preserve DEF')
                r['results'][label]={'source':str(src),'source_sha256':b.sha(src),'seconds':time.time()-start,'report':report.read_text(),'def_semantics_unchanged':True};save(r)
            if any(b.sha(Path(p))!=h for p,h in frozen.items()):raise ValueError('Input changed')
            r.update(status='completed',finished_at=time.time(),inputs_unchanged=True,frozen_inputs=frozen)
        except BaseException as exc:r.update(status='failed',finished_at=time.time(),error=repr(exc))
        save(r)


def dispatch(op):
    from .remote_platform import install
    task=install()
    if op=='status':return json.loads((OUT/'receipt.json').read_text()) if (OUT/'receipt.json').exists() else {'status':'not_started','job_id':JOB}
    if op!='start':raise ValueError('Unsupported audit operation')
    with task.locked(ROOT/'scheduler'):
        if (OUT/'receipt.json').exists():return dispatch('status')
        if active_jobs():raise ValueError('SERVER_BUSY')
        OUT.mkdir();r={'job_id':JOB,'status':'queued','created_at':time.time()};save(r)
        q=subprocess.run(['tmux','new-session','-d','-s',JOB,f'cd {ROOT} && exec /usr/bin/timeout --kill-after=5 300 python3 -B -m macro_agent.swerv_metric_audit worker'],capture_output=True,text=True,timeout=10)
        if q.returncode:r.update(status='failed',error=q.stderr);save(r)
        return r


if __name__=='__main__':
    if sys.argv[1:]==['worker']:run()
    else:
        try:print(json.dumps({'ok':True,'value':dispatch(json.load(sys.stdin)['operation'])}))
        except Exception as exc:print(json.dumps({'ok':False,'error':str(exc)}));sys.exit(1)
