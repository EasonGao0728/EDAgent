"""Case-bound main-Agent tool for the bp_multi short analysis and isolated repair."""
import fcntl
import os
import resource
from bp_short_study import *
from macro_agent.remote_platform import is_worker_account
from bp_short_hotspot import get_scan,trial
def view():
    d=read(WORK/'diagnosis.json')
    result=dict(case='bp_multi',parent=HASH,layers=d['layers'],hotspots=d['tiles'][:5],status='diagnosis_available')
    for file,field in [('attribution','raw_control'),('forest-attribution','attribution'),('geometry-sample','geometry'),('trial-result','trial')]:
        if (WORK/(file+'.json')).is_file():result[field]=read(WORK/(file+'.json'))
    if (WORK/'proposal.json').is_file():
        p=read(WORK/'proposal.json')
        result.update(status='proposal_ready',proposal_id=digest(WORK/'proposal.json'),proposal={k:p[k] for k in ('name','original','replacement','region_um','net_terminal_count','ranked_score')})
    if 'trial' in result:result['status']=result['trial']['status']
    if (WORK/'delivery/manifest.json').is_file() and result.get('status')=='accepted':
        manifest=read(WORK/'delivery/manifest.json')
        if manifest['parent']!=HASH or manifest['candidate_sha256']!=result['trial']['candidate_sha256']:
            raise ValueError('Unbound local candidate publication')
        result['manifest']=manifest
    return result
def worker(action):
    os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:4])
    resource.setrlimit(resource.RLIMIT_AS,(8<<30,8<<30))
    if action=='diagnose':get_scan()
    else:trial()
def command(action,proposal):
    if not is_worker_account() or not (WORK/'diagnosis.json').is_file():raise ValueError('Unqualified server context')
    with (WORK/'main-agent.lock').open('a+') as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        state=view()
        running=WORK/'active.json'
        if running.exists():
            job=read(running);log=WORK/(job['action']+'-worker.log')
            from macro_agent.remote_native import identity
            if identity(job['pid'])==job['start'] and Path('/proc',str(job['pid']),'stat').read_text().rsplit(')',1)[1].strip()[0]!='Z':
                state.update(status='running',active_action=job['action']);return state
            done=(WORK/('proposal.json' if job['action']=='diagnose' else 'trial-result.json')).exists()
            if not done:
                state.update(status='failed',active_action=job['action'],detail=log.read_text(errors='replace')[-800:])
                if action!='status' and job['implementation']!=impl():running.rename(WORK/(job['action']+'-old-attempt-'+str(job['pid'])+'.json'))
                else:return state
            else:running.rename(WORK/(job['action']+'-completed-'+str(job['pid'])+'.json'))
        if action=='status' or (action=='diagnose' and 'proposal_id' in state) or (action=='repair' and 'trial' in state):return state
        if action=='repair' and (not proposal or proposal!=state.get('proposal_id')):raise ValueError('Current proposal hash required')
        if action not in ('diagnose','repair'):raise ValueError('Unknown action')
        if digest(ORIGINAL)!=HASH:raise ValueError('Parent changed')
        from macro_agent.remote_native import identity
        with (WORK/(action+'-worker.log')).open('a') as log:
            p=subprocess.Popen([sys.executable,'-B',__file__,'worker',action],cwd=WORK,stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)
        save(running,dict(action=action,pid=p.pid,start=identity(p.pid),implementation=impl()))
        state.update(status='running',active_action=action);return state
def impl():
    return [digest(Path(__file__).with_name(n)) for n in ('bp_short_agent.py','bp_short_hotspot.py','bp_short_study.py')]
if __name__=='__main__':
    if sys.argv[1]=='worker':worker(sys.argv[2])
    else:print(json.dumps(command(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else None)))
