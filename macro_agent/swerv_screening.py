"""Frozen SWERV pre-route study; no routing, production promotion or tool making.

Standalone durable research job shares the production scheduler lock. Inputs
remain read-only; only new candidate directories can be written.
"""
from pathlib import Path
import json, os, re, shutil, subprocess, sys, time, signal

ROOT = Path(__file__).resolve().parents[1]
PARENT = 'remote-ba81f7bdbfebcf944da30462'
JOB = 'swerv-screening-20261115-v2'
OUT = ROOT/'runs'/JOB
TERMINAL = {'completed', 'failed', 'cancelled', 'lost'}


def save(value):
    p=OUT/'receipt.json';tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2));os.replace(tmp,p)


def active_jobs():
    return [p for p in (ROOT/'runs').glob('*/jobs/*.json')
            if json.loads(p.read_text()).get('status') not in TERMINAL]


def metrics(path, ref, m):
    from .def_validation import read_def, lef_cells, validate_placement
    d=read_def(path);cells={}
    for f in m['cell_lefs']:cells.update(lef_cells(ref/f,d['units']))
    points={}
    for n,c in d['components'].items():
        if not c['placement']:raise ValueError('Unplaced component '+n)
        _,x,y,o=c['placement'];w,h=cells[c['master']]['size']
        if o in ('E','W','FE','FW'):w,h=h,w
        points[n]=(x+w/2,y+h/2)
    for n,p in d['pins'].items():
        q=re.search(r'\+ (?:FIXED|PLACED|COVER) \( (-?\d+) (-?\d+) \)',p)
        if not q:raise ValueError('Unplaced IO '+n)
        points['PIN:'+n]=tuple(map(int,q.groups()))
    hpwl=0;multi=0
    for terms in d['nets'].values():
        if len(terms)<2:continue
        xy=[points['PIN:'+pin if inst=='PIN' else inst] for inst,pin in terms]
        hpwl+=max(x for x,y in xy)-min(x for x,y in xy)+max(y for x,y in xy)-min(y for x,y in xy);multi+=1
    geometry=validate_placement(d,d,d,[ref/f for f in m['cell_lefs']],m)
    return {'instances':len(d['components']),'nets':len(d['nets']),'multi_endpoint_nets':multi,
            'center_hpwl_um':hpwl/d['units'],'hpwl_scope':'cell-center / IO-anchor proxy, not pin HPWL or routed wirelength',
            'geometry':geometry,'macro_positions':{n:d['components'][n] for n in m['expected_macro_masters']}}


def historical_seed(source, dest, m):
    from .def_validation import read_def, lef_cells
    old=read_def(source);text=Path(source).read_text()
    positions={'gen_11599_':(420000,12200),'gen_11600_':(617840,12200),'gen_5613_':(5180,12200)}
    # Change exactly three macro placements; preserve current orientations.
    for name,(x,y) in positions.items():
        ori=old['components'][name]['placement'][3]
        pattern=r'(^\s*-\s+'+re.escape(name)+r'\s+\S+\s+\+ FIXED\s*\()\s*-?\d+\s+-?\d+\s*\)\s+\S+'
        text,n=re.subn(pattern,lambda a:a[1]+f' {x} {y} ) {ori}',text,flags=re.M)
        if n!=1:raise ValueError('Macro replacement mismatch: '+name)
    Path(dest).write_text(text);new=read_def(dest)
    for key in old:
        if key!='components' and old[key]!=new[key]:raise ValueError('Non-macro input changed')
    for name,c in old['components'].items():
        if name not in positions and c!=new['components'][name]:raise ValueError('Standard cell changed')
    cells={};ref=ROOT/'cases/ibench/swerv_nangate45'
    for f in m['cell_lefs']:cells.update(lef_cells(ref/f,old['units']))
    boxes=[]
    for name in positions:
        c=new['components'][name];_,x,y,o=c['placement'];w,h=cells[c['master']]['size']
        if o in ('E','W','FE','FW'):w,h=h,w
        box=(x,y,x+w,y+h)
        x0,y0,x1,y1=[round(v*old['units']) for v in m['core_area_microns']]
        if not(x0<=x and y0<=y and x+w<=x1 and y+h<=y1):raise ValueError('Macro outside core')
        for a,b,cx,dy in boxes:
            if min(cx,x+w)>max(a,x) and min(dy,y+h)>max(b,y):raise ValueError('Macro overlap')
        boxes.append(box)
    return {'changed_instances':list(positions),'other_parsed_fields_equal':True,'bounds_and_nonoverlap_passed':True,
            'scope':'Historical coordinates with current orientations/libraries; not a reproduction of historical pipeline'}


def run():
    from .remote_platform import install
    task=install()
    os.environ['AIEDA_NATIVE_HANDLES']=str(OUT/'native-handles')
    Path(os.environ['AIEDA_NATIVE_HANDLES']).mkdir(exist_ok=True)
    def interrupted(signum,frame):raise InterruptedError('Study interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    from . import swerv_backend as backend
    from .portable_ieda import BINARY_SHA256
    with task.locked(ROOT/'scheduler'):
        if active_jobs():raise ValueError('SERVER_BUSY')
        r=json.loads((OUT/'receipt.json').read_text())
        if r['status']!='queued':raise ValueError('Already attempted; inspect receipt')
        r.update(status='running',started_at=time.time(),pid=os.getpid());save(r)
        frozen={}
        try:
            parent=ROOT/'runs'/PARENT;s=json.loads((parent/'task.json').read_text())
            if s['status']!='target_met' or s['contract']['case_id']!='swerv_nangate45':raise ValueError('Parent mismatch')
            task.verify_refs(s['input_refs'])
            if backend.sha(parent/'final.def')!='58cdabe9055888ee9d795d6fd3ca4852bc3481b18aaf92fae37c850278845c13':raise ValueError('Parent DEF identity changed')
            ref=ROOT/'cases/ibench/swerv_nangate45';m=backend.manifest(ref)
            for p in [parent/'task.json',parent/'final.def',*[Path(s['results'][k]['artifact']) for k in ('to_drv','to_hold','legalization','macro_placement','placement')],*ref.rglob('*')]:
                if p.is_file():frozen[str(p)]=backend.sha(p)
            r.update(parent_sha256=frozen[str(parent/'final.def')],frozen_inputs=frozen,
                     study_source_sha256=backend.sha(Path(__file__)),
                     binary_sha256=BINARY_SHA256,budget={'cpu':4,'address_space_gib':8,'campaign_seconds':3600,'per_native_stage_seconds':600},
                     production_modified=False,routing_started=False,results={},native_stages=[]);save(r)
            def stage(label,w,action):
                if time.time()-r['started_at']>3000:raise TimeoutError('Screening budget exhausted')
                v=backend.execute(action,w,ref)
                r['native_stages'].append({'candidate':label,'stage':action,'seconds':v.get('seconds'),'evidence':str(w/(action+'-evidence.json'))});save(r)
                return v
            def prepared(label):
                w=OUT/label;w.mkdir();backend.setup(w,ref);return w
            def timing(label,w,source):
                # Same diagnostic STA for all hold arms; alias only in isolated work.
                shutil.copyfile(source,w/'result/filler.def');stage(label,w,'timing')
                return {'report':str(w/'result/timing'/f'{m["top"]}.rpt'),'parasitics':'No extracted SPEF; diagnostic only'}
            # Reuse accepted 20% layout; repeat only read-only STA, not placement.
            w=prepared('hold_20_reused');src=Path(s['results']['legalization']['artifact'])
            r['results']['hold_20']={'factor':0.2,'reused':True,'metrics':metrics(src,ref,m),
                'native_pass':s['results']['to_hold']['native_optimization']['passes'],
                'timing':timing('hold_20',w,src)};save(r)
            for label,cap in (('hold_05',0.05),('hold_10',0.10)):
                w=prepared(label);shutil.copyfile(s['results']['to_drv']['artifact'],w/'result/to_drv.def')
                p=w/'config/to_default_config_hold.json';cfg=json.loads(p.read_text());before=dict(cfg)
                cfg['max_insert_instance_percent']=cap;backend.write(p,cfg)
                if {k:v for k,v in cfg.items() if k!='max_insert_instance_percent'}!={k:v for k,v in before.items() if k!='max_insert_instance_percent'}:raise ValueError('Multiple factors changed')
                v=stage(label,w,'to_hold');stage(label,w,'legalization');src=w/'result/legalization.def'
                r['results'][label]={'factor':cap,'reused':False,'metrics':metrics(src,ref,m),
                    'native_pass':v['native_optimization']['passes'],'timing':timing(label,w,src),
                    'config_sha256':backend.sha(p),'input_sha256':backend.sha(w/'result/to_drv.def')};save(r)
            # Macro comparison stops before CTS/hold: both arms contain no hold insertion.
            src=Path(s['results']['placement']['artifact'])
            r['results']['macro_imp_reused']={'reused':True,'metrics':metrics(src,ref,m),
                'native_place_summary':json.loads((src.parent/'pl/report/place_summary.json').read_text())};save(r)
            w=prepared('macro_shelf');seed=historical_seed(s['results']['macro_placement']['artifact'],w/'result/macro_placement.def',m)
            stage('macro_shelf',w,'fanout');stage('macro_shelf',w,'placement')
            r['results']['macro_shelf']={'reused':False,'seed_check':seed,'metrics':metrics(w/'result/placement.def',ref,m),
                'native_place_summary':json.loads((w/'result/pl/report/place_summary.json').read_text())};save(r)
            changed=[p for p,h in frozen.items() if backend.sha(p)!=h]
            if changed:raise ValueError('Frozen source changed: '+str(changed))
            r.update(status='completed',finished_at=time.time(),frozen_inputs_unchanged=True,
                     promotion='none; screening only, no full-route DRC evidence')
        except BaseException as exc:
            r.update(status='failed',error=repr(exc),finished_at=time.time())
        save(r)


def dispatch(op):
    from .remote_platform import install
    task=install()
    if op=='status':
        if not (OUT/'receipt.json').exists():return {'job_id':JOB,'status':'not_started'}
        return json.loads((OUT/'receipt.json').read_text())
    if op!='start':raise ValueError('Only fixed study start/status are allowed')
    with task.locked(ROOT/'scheduler'):
        if (OUT/'receipt.json').exists():return dispatch('status')
        if active_jobs():raise ValueError('SERVER_BUSY')
        OUT.mkdir();r={'job_id':JOB,'status':'queued','created_at':time.time(),'parent_task':PARENT};save(r)
        command=f'cd {ROOT} && exec /usr/bin/timeout --kill-after=10 3600 python3 -B -m macro_agent.swerv_screening worker'
        p=subprocess.run(['tmux','new-session','-d','-s',JOB,command],capture_output=True,text=True,timeout=10)
        if p.returncode:r.update(status='failed',error=p.stderr);save(r)
        return r


if __name__=='__main__':
    if sys.argv[1:] == ['worker']:run()
    else:
        try:print(json.dumps({'ok':True,'value':dispatch(json.load(sys.stdin)['operation'])}))
        except Exception as exc:print(json.dumps({'ok':False,'error':str(exc)}));sys.exit(1)
