"""FIFO admission for the existing SSH task service. Native receipts remain authoritative."""
from contextlib import contextmanager, ExitStack
import hashlib
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import time

from . import remote_service as native


@contextmanager
def wait_for_controller():
    """Wait for the admission lock only. Never retry the operation it protects."""
    deadline = time.monotonic()+45
    with ExitStack() as stack:
        while True:
            try:
                stack.enter_context(native.task.locked(native.ROOT/'scheduler'))
                break
            except ValueError as exc:
                if not str(exc).startswith('TASK_BUSY:') or time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        yield


@contextmanager
def transaction():
    folder = native.ROOT / 'scheduler'
    folder.mkdir(exist_ok=True)
    db = sqlite3.connect(folder / 'fifo-v1.sqlite3', timeout=60, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS tickets (
            seq INTEGER PRIMARY KEY, jid TEXT UNIQUE NOT NULL, tid TEXT NOT NULL,
            payload TEXT NOT NULL, state TEXT NOT NULL, status TEXT NOT NULL, error TEXT)''')
        db.execute('CREATE INDEX IF NOT EXISTS fifo_pending ON tickets(status, seq)')
        yield db
        db.commit()
    finally:
        db.close()


def ensure_dispatcher():
    name = 'edagent-fifo-' + hashlib.sha256(str(native.ROOT).encode()).hexdigest()[:12]
    if subprocess.run(['tmux', 'has-session', '-t', '='+name], capture_output=True).returncode == 0:
        return
    command = 'cd '+shlex.quote(str(native.ROOT))+' && exec '+shlex.quote(sys.executable)+' -B -m macro_agent.fifo_service dispatch'
    result = subprocess.run(['tmux', 'new-session', '-d', '-s', name, command], capture_output=True, text=True)
    if result.returncode and 'duplicate session' not in result.stderr:
        raise RuntimeError('FIFO dispatcher unavailable: '+result.stderr.strip())


def native_record(tid, jid):
    return native.folder_for(tid) / 'jobs' / (native.valid_id(jid)+'.json')


def head(db):
    return db.execute("SELECT * FROM tickets WHERE status='waiting' ORDER BY seq LIMIT 1").fetchone()


def task_ticket(db, tid):
    return db.execute("SELECT * FROM tickets WHERE tid=? AND status='waiting' ORDER BY seq LIMIT 1", (tid,)).fetchone()


def decorate(db, row, view):
    job = dict(job_id=row['jid'], task_id=row['tid'], request=json.loads(row['payload']),
               execution_location='server', status=row['status'])
    if row['status'] == 'waiting':
        position = db.execute("SELECT COUNT(*) FROM tickets WHERE status='waiting' AND seq<=?", (row['seq'],)).fetchone()[0]
        job.update(status='queued', queue_position=position)
        view = dict(view, job=job, allowed_actions=[], phase='SERVER_JOB_QUEUED')
    elif row['error']:
        job['error'] = row['error']
    return {'job':job, 'task':view}


def lookup(db, tid, jid):
    return db.execute('SELECT * FROM tickets WHERE tid=? AND jid=?', (tid,jid)).fetchone()


def queueable(req, folder):
    op = req['operation']
    if op == 'decision_execute':
        from .main_decisions import selected
        _, plan = selected(native.task.load(folder/'task.json'), folder, req['plan_id'])
        return bool(plan['tool_card'].get('native_stage') or plan['tool_id']=='route_top_met3')
    return op in ('run','local_execute','feedback_continue','quality_execute') or (
        op=='act' and req.get('action') not in ('finish','stop','recover'))


def admission(db, req, folder):
    action_id = req.get('action_id')
    if not isinstance(action_id,str) or not action_id:
        raise ValueError('Idempotency key required')
    tid = folder.name
    jid = 'job-'+hashlib.sha256((tid+':'+action_id).encode()).hexdigest()[:24]
    payload = json.dumps({k:req[k] for k in ('task_id','operation','action_id','action','state_id','reason',
                         'plan_id','branch_id','evidence_id') if k in req}, sort_keys=True)
    row = lookup(db,tid,jid)
    if row and row['payload'] != payload:
        raise ValueError('JOB_IDENTITY_COLLISION')
    if native_record(tid,jid).exists():
        if not row:  # Action originally admitted by the previous entry point.
            return native.rpc(req)
        return native.rpc({'operation':'job_status','task_id':tid,'job_id':jid})
    view = native.snapshot(folder)
    if not view:
        raise ValueError('Unknown task')
    if row:
        return decorate(db,row,view)
    current = task_ticket(db,tid)
    if current or view.get('job'):
        raise ValueError('SERVER_JOB_ACTIVE: query the existing job '+(current['jid'] if current else view['job']['job_id']))
    if req.get('state_id') and req['operation']!='feedback_continue' and req['state_id']!=view['state_id']:
        raise ValueError('STALE_STATE')
    db.execute("INSERT INTO tickets(jid,tid,payload,state,status) VALUES(?,?,?,?,'waiting')",
               (jid,tid,payload,view['state_id']))
    return decorate(db,lookup(db,tid,jid),view)


def advance(db):
    row = head(db)
    if not row:
        return False
    tid,jid = row['tid'],row['jid']
    record = native_record(tid,jid)
    status,error = 'admitted',None
    if not record.exists():
        req = json.loads(row['payload'])
        folder = native.folder_for(tid)
        try:
            if native.task.state_id(native.task.load(folder/'task.json')) != row['state']:
                raise ValueError('STALE_STATE: queued inputs changed')
            value = native.rpc(req)
            if not record.exists():
                if value.get('replayed'):
                    status = 'completed'
                else:
                    raise RuntimeError('Expected durable native job receipt')
        except Exception as exc:
            if not record.exists():
                if str(exc).startswith('SERVER_BUSY:'):
                    reconcile_busy_job(str(exc).split()[1].rstrip(';'))
                    return False
                if str(exc).startswith('TASK_BUSY:'):
                    return False
                status,error = 'failed',str(exc)
    # After an interrupted transaction, adopt the existing native receipt.
    # Never issue a fresh action ID or re-run work to reconstruct a result.
    db.execute('UPDATE tickets SET status=?,error=? WHERE jid=?',(status,error,jid))
    return True


def reconcile_busy_job(jid):
    """Inspect an abandoned legacy receipt without restarting an uncertain job."""
    native.valid_id(jid)
    for path in (native.ROOT/'runs').glob('*/jobs/'+jid+'.json'):
        job = native.task.load(path)
        # A native child can outlive its worker. Keep the slot occupied while
        # the worker's process group still exists, even if the leader exited.
        if job.get('pid') and job['status']=='running':
            try:
                os.killpg(job['pid'],0)
                return
            except ProcessLookupError:
                pass
        try:
            native.status_job(path.parent.parent,jid)
        except ValueError as exc:
            if not str(exc).startswith('TASK_BUSY:'):
                raise


def dispatch_loop():
    while True:
        with transaction() as db:
            progressed = advance(db)
        time.sleep(0.1 if progressed else 2)


def rpc(req):
    op = req['operation']
    if op=='runtime_status':
        return native.rpc(req)
    tid = req['task_id']
    folder = native.folder_for(tid)
    if op in ('job_status','job_cancel'):
        jid = native.valid_id(req['job_id'])
        with transaction() as db:
            row = lookup(db,tid,jid)
            if row and not native_record(tid,jid).exists():
                if op=='job_cancel' and row['status']=='waiting':
                    db.execute("UPDATE tickets SET status='cancelled',error=? WHERE jid=?", (req.get('reason','cancelled'),jid))
                    row = lookup(db,tid,jid)
                if row['status']=='waiting':
                    ensure_dispatcher()
                return decorate(db,row,native.snapshot(folder))
        return native.rpc(req)
    last = None
    with transaction() as db:
        if queueable(req,folder):
            result = admission(db,req,folder)
            if result.get('job',{}).get('queue_position'):
                ensure_dispatcher()
            return result
        pending = task_ticket(db,tid)
        if pending and not native_record(tid,pending['jid']).exists():
            if op in ('context','observe'):
                ensure_dispatcher()
                return decorate(db,pending,native.snapshot(folder))['task']
            if op=='reserve_model':
                return {'reserved':False,'reason':'queued server job'}
            if op not in ('artifacts','download','query','retrieve','decision_inspect','feedback_inspect','feedback_status'):
                raise ValueError('SERVER_JOB_ACTIVE: query queued job '+pending['jid'])
        if op in ('context','observe'):
            last = db.execute('SELECT * FROM tickets WHERE tid=? ORDER BY seq DESC LIMIT 1',(tid,)).fetchone()
            if last and last['status'] in ('failed','cancelled','completed') and not native_record(tid,last['jid']).exists():
                view = native.snapshot(folder)
                return dict(view,job=decorate(db,last,view)['job'])
    view = native.rpc(req)
    if last and view and not view.get('job'):
        path = native_record(tid,last['jid'])
        if path.is_file():
            view = dict(view, job=native.task.load(path))
    return view


if __name__ == '__main__':
    native.init()
    native.gate = wait_for_controller
    if sys.argv[1:] == ['dispatch']:
        dispatch_loop()
    else:
        try:
            print(json.dumps({'ok':True,'value':rpc(json.load(sys.stdin))},ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False))
            sys.exit(1)
