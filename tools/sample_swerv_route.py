"""Ten-second user-space sampling of the verified owned router, never EDA restart."""
from pathlib import Path
import json,subprocess,shlex,sys,re
ROOT=Path(__file__).resolve().parents[1]
CODE=r'''
import pathlib,json,os,subprocess,time,resource,sys,re
assert os.getuid()==1015
folder=pathlib.Path('/srv/edagent/main-agent-remote-v1/runs/remote-ba81f7bdbfebcf944da30462')
s=json.loads((folder/'task.json').read_text());assert s['pending']['action']=='routing'
w=pathlib.Path(s['pending']['work']);assert w.is_relative_to(folder/'attempts')
last=json.loads((w/'logs/routing-progress.jsonl').read_text().splitlines()[-1]);assert time.time()-last['time']<65
candidate=[p for p in last['processes'] if p['name']=='ld-linux-x86-64'];assert len(candidate)==1
p=candidate[0];proc=pathlib.Path('/proc')/str(p['pid']);assert proc.stat().st_uid==os.getuid()
assert (proc/'stat').read_text().rsplit(')',1)[1].split()[19]==p['start_ticks']
assert b'/router/iEDA' in (proc/'cmdline').read_bytes()
label=sys.argv[1];assert re.fullmatch('[a-z]{1,16}',label)
out=folder/'diagnostics'/('perf-'+w.name+'-'+label);out.mkdir(parents=True,exist_ok=False)
os.sched_setaffinity(0,os.sched_getaffinity(p['pid']))
resource.setrlimit(resource.RLIMIT_FSIZE,(64*1024**2,64*1024**2))
command=['perf','record','-e','cpu-clock:u','-F','49','--call-graph','dwarf,4096','-p',str(p['pid']),'-o',str(out/'perf.data'),'--','sleep','10']
started=time.time()
result=subprocess.run(command,capture_output=True,text=True,timeout=25)
(out/'record-stderr.txt').write_text(result.stderr)
record={'pid':p['pid'],'start_ticks':p['start_ticks'],'started_at':started,'seconds':time.time()-started,
    'returncode':result.returncode,'stderr':result.stderr,'native_stage_restarted':False,
    'frequency_hz':49,'sample_seconds':10,'user_space_only':True,'router_unchanged':True}
if result.returncode==0:
 report=subprocess.run(['perf','report','--stdio','--no-children','--percent-limit','1','-i',str(out/'perf.data')],capture_output=True,text=True,timeout=25)
 (out/'report.txt').write_text(report.stdout);(out/'report-stderr.txt').write_text(report.stderr)
 record['report_returncode']=report.returncode;record['report_tail']=report.stdout[-14000:]
(out/'receipt.json').write_text(json.dumps(record,indent=2));print(json.dumps(record))
'''
if __name__=='__main__':
    label=sys.argv[1] if len(sys.argv)>1 else 'initial'
    if not re.fullmatch('[a-z]{1,16}',label):raise ValueError('Invalid diagnostic label')
    p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','eda-worker','python3 -B -c '+shlex.quote(CODE)+' '+shlex.quote(label)],capture_output=True,text=True,encoding='utf-8',timeout=60)
    if p.returncode:raise RuntimeError(p.stderr or p.stdout)
    r=json.loads(p.stdout);(ROOT/('runs/medium-macro-fullflow-20261114/retry-perf-sample-'+label+'.json')).write_text(json.dumps(r,indent=2),encoding='utf-8')
    print(json.dumps(r,ensure_ascii=False))
