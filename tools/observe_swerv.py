"""Read-only workbench/task monitor; never submits or resumes a native stage."""
from pathlib import Path
import json,urllib.request,subprocess,shlex
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'runs/medium-macro-fullflow-20261114'
sid=(OUT/'session-id.txt').read_text(encoding='utf-8-sig').strip()
with urllib.request.urlopen('http://127.0.0.1:4173/api/sessions/'+sid,timeout=10) as r:s=json.load(r)
(OUT/'session-progress.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
t=s.get('task') or {};events=s.get('events',[])
print(json.dumps({'busy':s.get('busy'),'status':s.get('status'),'phase':t.get('phase'),'counts':t.get('counts'),'completed':sum(x['status']=='validated' for x in t.get('plan',[])),'latest_tools':[{'name':x.get('name'),'error':x.get('error')} for x in events if x['type'] in ('tool_end','tool_error')][-3:]},ensure_ascii=False))
tid=t.get('server_task_id')
if tid:
 code='''import pathlib,json,time
p=pathlib.Path('/srv/edagent/main-agent-remote-v1/runs')/'''+repr(tid)+'''
s=json.loads((p/'task.json').read_text());pending=s.get('pending') or {};w=pathlib.Path(pending.get('work') or s.get('accepted_work') or p)
log=w/'logs'/(str(pending.get('action'))+'.log');rt=w/'result/rt/rt.log'
v={'server_status':s['status'],'completed':s['completed'],'pending':pending.get('action'),'elapsed_s':round(time.time()-s['created_at']),'last_event':s['events'][-1] if s['events'] else None}
if rt.exists():v['route_tail']=rt.read_text(errors='replace')[-1600:]
elif log.exists():v['log_tail']=log.read_text(errors='replace')[-600:]
print(json.dumps(v))
'''
 p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','eda-worker','python3 -c '+shlex.quote(code)],capture_output=True,text=True,encoding='utf-8',timeout=20)
 if p.returncode:print('Server read unavailable:',p.stderr[:150])
 else:
  result=json.loads(p.stdout);(OUT/'server-progress.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
  brief={k:v for k,v in result.items() if k not in ('completed','last_event','route_tail','log_tail')}
  brief['completed_count']=len(result['completed'])
  brief['latest_native_line']=(result.get('route_tail') or result.get('log_tail') or '').strip().splitlines()[-1:]
  print(json.dumps(brief,ensure_ascii=False))
