"""Read-only snapshot of the explicitly approved third SWERV routing job.

Never submits, resumes, cancels, or edits a server task. Persist evidence locally.
"""
from pathlib import Path
import datetime, json, subprocess, urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'runs/medium-macro-fullflow-20261114'
CODE = r'''
from pathlib import Path
import json, os, time
p=Path('/srv/edagent/main-agent-remote-v1/runs/remote-ba81f7bdbfebcf944da30462')
jid='job-f863e2f008543b31ebcfd294'
s=json.loads((p/'task.json').read_text())
j=json.loads((p/'jobs'/(jid+'.json')).read_text())
w=p/'attempts/15f45a6cc990'
def tail(path,limit):
    if not path.is_file():return ''
    with path.open('rb') as f:
        f.seek(max(0,path.stat().st_size-limit))
        return f.read().decode(errors='replace')
samples=[]
for line in tail(w/'logs/routing-progress.jsonl',20000).splitlines()[-3:]:
    try:samples.append(json.loads(line))
    except ValueError:pass
native=[]
if samples:
    for item in samples[-1]['processes']:
        proc=Path('/proc')/str(item['pid'])
        try:
            stat=(proc/'stat').read_text().rsplit(')',1)[1].split()
            if proc.stat().st_uid==os.getuid() and stat[19]==item['start_ticks']:
                native.append({**item,'identity_alive':True,'current_cpu_seconds':(int(stat[11])+int(stat[12]))/os.sysconf('SC_CLK_TCK')})
        except OSError:pass
result={'observed_at':time.time(),'job_id':jid,'job_status':j.get('status'),'job_started_at':j.get('started_at'),
 'job_elapsed_s':round(time.time()-j.get('started_at',time.time())),
 'server_status':s['status'],'pending':s.get('pending'),'completed':s['completed'],'counts':s.get('counts'),
 'failure_counts':s.get('failure_counts'),'accepted_work':s.get('accepted_work'),
 'route_tail':tail(w/'result/rt/rt.log',5000),'routing_def_exists':(w/'result/routing.def').is_file(),
 'samples':samples,'identity_matched_processes':native,
 'routing_evidence':json.loads((w/'routing-evidence.json').read_text()) if (w/'routing-evidence.json').is_file() else None}
print(json.dumps(result))
'''
connection_errors=[]
for host in ('eda-worker','eda-backup'):
    try:
        r = subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',host,'python3 -'],input=CODE,capture_output=True,text=True,encoding='utf-8',timeout=25)
        if not r.returncode:break
        connection_errors.append({'host':host,'error':r.stderr[:300]})
    except subprocess.TimeoutExpired:
        connection_errors.append({'host':host,'error':'Read-only query timed out after 25 seconds'})
else:
    raise RuntimeError('Read-only SSH snapshot unavailable: '+json.dumps(connection_errors))
v=json.loads(r.stdout)
v['observation_connection']={'host':host,'failed_queries':connection_errors}
sid=(OUT/'session-id.txt').read_text(encoding='utf-8-sig').strip()
try:
    with urllib.request.urlopen('http://127.0.0.1:4173/api/sessions/'+sid,timeout=10) as res:ui=json.load(res)
    v['workbench']={k:ui.get(k) for k in ('busy','status')}
    v['workbench']['phase']=(ui.get('task') or {}).get('phase')
except Exception as exc:v['workbench']={'observation_error':str(exc)}
(OUT/'live-route-snapshot.json').write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
with (OUT/'route-monitor.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(v,ensure_ascii=False)+'\n')
print(json.dumps({'at':datetime.datetime.fromtimestamp(v['observed_at']).isoformat(),'job_id':v['job_id'],
 'job_status':v['job_status'],'job_elapsed_min':round(v['job_elapsed_s']/60,1),'completed':len(v['completed']),
 'server_status':v['server_status'],'pending':(v.get('pending') or {}).get('action'),
 'last_native_line':v['route_tail'].strip().splitlines()[-1:],
 'identity_matched_processes':len(v['identity_matched_processes']),'routing_def_exists':v['routing_def_exists'],
 'workbench':v['workbench']},ensure_ascii=False))
