"""Read-only compact status for the active real DSH AES acceptance run."""
import argparse,json,re,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
status=json.loads((ROOT/'runs/aes-p1-20261108/status.json').read_text(encoding='utf-8'))
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--case',default='aes_sky130_t')
args=parser.parse_args()
tracked=next((case for case in status['cases'] if case['case_id']==args.case),None)
if not tracked or not tracked.get('dsh_run'):
    raise SystemExit('No tracked DSH task for case: '+args.case)
folder=Path(tracked['dsh_run'])
s=json.loads((folder/'task.json').read_text(encoding='utf-8'))
p=s.get('pending')
out={'time':time.strftime('%H:%M:%S'),'status':s['status'],'completed':s['completed'],
     'counts':s['counts'],'pending':p.get('action') if p else None,'failures':s['failure_counts']}
if p:
    work=Path(p['work']);logs=sorted((work/'logs').glob('*.log'),key=lambda f:f.stat().st_mtime)
    if p['action']=='routing' and (work/'result/rt/rt.log').is_file():logs=[work/'result/rt/rt.log']
    if logs:
        f=logs[-1]
        with f.open('rb') as h:
            h.seek(max(0,f.stat().st_size-4*1024*1024));tail=h.read(4*1024*1024).decode('utf-8',errors='replace')
        lines=re.sub(r'\x1b\[[0-9;]*m','',tail).splitlines()
        out['log_age_seconds']=round(time.time()-f.stat().st_mtime)
        out['log_bytes']=f.stat().st_size
        out['last_activity']=[line for line in lines if line.strip()][-1:]
        out['iteration']=[line for line in lines if 'Begin iteration' in line][-1:]
        out['progress']=[line for line in lines if re.search(r'Starting|Completed|Begin iteration|End iteration|Routed [0-9]',line)][-2:]
print(json.dumps(out,ensure_ascii=True),flush=True)
