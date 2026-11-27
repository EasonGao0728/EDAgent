"""Idempotent launcher for the frozen bp_multi branch, independent of the SSH connection."""
import fcntl
import os
import json
from pathlib import Path
import re
import subprocess
import sys

from verify_pa import RUNS, sha, save
from macro_agent.remote_native import identity
from qualify_route_state import DR_SHA


def detailed_checkpoint(work, binding):
    path=work/'DR-batch.bin'
    if not path.is_file():
        return None
    # The writer replaces this file atomically. Read just the three small header fields.
    with path.open('rb') as stream:
        def field():
            length=int.from_bytes(stream.read(4),'little')
            return stream.read(length).decode('ascii') if 0<length<=64 else ''
        if field()!='ieda-route-state-v1':return None
        cursor=re.fullmatch(r'D12_([1-9][0-9]*)',field())
        if not cursor or field()!=binding:return None
        return int(cursor[1])


def status(root):
    family = RUNS / ('full-lazy-' + DR_SHA[:12])
    amendment=root/'budget-amendment-3h.json'
    budget=None
    if amendment.is_file() and sha(amendment)=='fd4c3af89ca15e5650732b12532d35d17d54a13269a9f2ddd61543a7ebbd4666':
        grant=json.loads(amendment.read_bytes())
        budget={'original_result':grant['original_result'],'expires_at':grant['expires_at']}
    if (root/'budget-open.json').is_file():
        from resume_space import open_budget
        open_budget()
        budget={'original_result':'deadline_exceeded','unlimited':True}
    revision=next((v for v in (17,16,14,13,12) if (root/f'repair-v{v}/launch.json').is_file()),None)
    recovery=root/f'repair-v{revision}'
    index=0
    if revision==17:
        for candidate in root.glob('repair-v17-r*/launch.json'):
            m=re.fullmatch(r'repair-v17-r([1-9][0-9]*)',candidate.parent.name)
            if m and int(m[1])>index:index=int(m[1]); recovery=candidate.parent
    is_recovery=revision is not None
    if is_recovery:
        root=recovery
    work = family/recovery.name.replace('repair-','recovery-',1) if is_recovery else family
    if budget and (work/'active.json').is_file():
        native=json.loads((work/'active.json').read_bytes())
        if 'started' in native and native.get('timeout_s'):
            budget['native_deadline']=int(native['started']+native['timeout_s'])
    record = json.loads((root/'launch.json').read_bytes()) if (root/'launch.json').exists() else {}
    receipt = json.loads((work/'receipt.json').read_bytes()) if (work/'receipt.json').exists() else {}
    protocol = json.loads((family/'state-contract.json').read_bytes()) if (family/'state-contract.json').is_file() else {}
    next_step=json.loads((root/'continuation.json').read_bytes()) if (root/'continuation.json').is_file() else {}
    backend=json.loads((family/'backend/current.json').read_bytes()) if (family/'backend/current.json').is_file() else {}
    manifest=family/'backend/delivery/manifest.json'
    active = bool(record.get('start_ticks') and identity(record['pid']) == record['start_ticks'])
    phase = ('completed' if receipt.get('returncode')==0 and receipt.get('stage_marker') else 'failed') if receipt else (
        'running' if active else 'interrupted' if record or work.exists() else 'ready')
    log = work/'result/rt/rt.log'
    lines = []
    iteration=None
    if log.exists():
        with log.open('rb') as f:
            f.seek(max(0,log.stat().st_size-262144))
            lines=f.read().decode(errors='replace').splitlines()
        current=re.search(r' (\w+)\.cpp:\d+',lines[-1]) if lines else None
        if current:
            start=re.compile(re.escape(current[1])+r'\.cpp:\d+ Info \w+\] \*+ Begin iteration (\d+)/(\d+)')
            for line in reversed(lines):
                if m:=start.search(line):
                    iteration={'module':current[1],'round':int(m[1]),'total':int(m[2])}
                    break
    cause=None
    if receipt.get('returncode') and (work/'stdout.log').is_file():
        with (work/'stdout.log').open('rb') as stream:
            stream.seek(max(0,(work/'stdout.log').stat().st_size-4096))
            tail=stream.read().decode(errors='replace')
        if 'std::bad_alloc' in tail:
            cause='std::bad_alloc · virtual memory peak {:.2f} GiB / {} GiB'.format(
                receipt['peak_vm_bytes']/1024**3,receipt['address_space_gib'])
        elif 'corrupted size vs. prev_size' in tail:
            cause='glibc detected heap corruption. See the original native log and the saved DR batch.'
        elif receipt['returncode']==124:
            cause=f"服务器单次布线时限 {receipt['timeout_s']:,} 秒已到（退出码 124）。"
            last=next((m for line in reversed(lines)
                       if (m:=re.search(r'DR boxes committed (\d+)/(\d+)',line))),None)
            if last:cause+=f"最后记录 {int(last[1]):,}／{int(last[2]):,} 个已提交分区。"
            if not receipt.get('output_sha256'):cause+="本次未交付布线 DEF，最终 DRC 尚无实测值。"
        elif lines and re.search(r'(Error|Fatal) ',lines[-1]):
            cause=lines[-1].split('] ',1)[-1][:400]
    resume=None
    if not is_recovery and receipt.get('returncode')==134:
        from resume_space import SAMPLE, V12
        sample=SAMPLE/'downstream-v12/sample-acceptance.json'
        if sample.is_file() and json.loads(sample.read_bytes()).get('passed'):
            resume={'action':'start','revision':12,'restores':'LA','checkpoint':receipt['checkpoints']['LA'],
                    'binary_sha256':V12,'replays_upstream':False}
    if revision==12 and receipt and receipt['returncode'] and (work/'boundary-leads.json').exists():
        from resume_space import V13, EDGE_TABLE
        edges=json.loads((work/'boundary-leads.json').read_bytes())
        if edges['ports']==1431 and edges['table']==EDGE_TABLE and receipt['states'].get('SR')==edges['sr']:
            resume={'action':'start','revision':13,'restores':'SR','checkpoint':{'sha256':edges['sr']},
                    'ports':edges['ports'],'binary_sha256':V13,'replays_upstream':False}
    if revision==13 and receipt.get('returncode')==134 and receipt.get('accepted_boundary_leads'):
        from resume_space import V14,SAMPLE
        canary=SAMPLE/'downstream-v14/sample-acceptance.json'
        if canary.is_file():
            accepted=json.loads(canary.read_bytes())
            if accepted['passed'] and accepted['binary']==V14 and receipt['states'].get('TA'):
                resume={'action':'start','revision':14,'restores':'TA','checkpoint':{'sha256':receipt['states']['TA']},
                        'ports':1431,'binary_sha256':V14,'replays_upstream':False}
    if revision==14 and receipt.get('returncode')==124 and budget and budget.get('unlimited'):
        from resume_space import SAMPLE,V16,open_budget
        canary=SAMPLE/'downstream-v16-replay/sample-acceptance.json'
        if canary.is_file():
            check=json.loads(canary.read_bytes())
            if check['passed'] and check['same_reference_per_net_paths'] and check['binary']==V16:
                resume={'action':'start','revision':16,'binary_sha256':V16,'restores':'TA',
                        'replays_upstream':False,'checkpoint':{'sha256':open_budget()['ta_sha256']}}
    if revision==16 and receipt.get('returncode')==134 and budget and budget.get('unlimited'):
        from resume_space import SAMPLE,V17
        check_path=SAMPLE/'downstream-v17/sample-acceptance.json'
        batch=receipt.get('states',{}).get('DR-batch')
        if check_path.exists() and batch=='f5b85018e4e87cb5e7dec86c9db0f72dc0af7803c07dcc34f0f2b52f63601959':
            check=json.loads(check_path.read_bytes())
            if check['passed'] and check['binary']==V17 and check['same_reference_per_net_paths']:
                resume={'action':'start','revision':17,'binary_sha256':V17,'restores':'D12_128',
                        'replays_upstream':False,'checkpoint':{'sha256':batch}}
    durable=None
    if revision in (16,17):
        durable=detailed_checkpoint(work,protocol.get('sha256'))
        if durable is None and revision==17:
            prior=family/(('recovery-v17'+(f'-r{index-1}' if index>1 else '')) if index else 'recovery-v16')
            durable=detailed_checkpoint(prior,protocol.get('sha256'))
    if (revision==17 and receipt.get('returncode') and cause and 'std::bad_alloc' in cause
            and durable and durable>int(receipt.get('restored_level','D12_128')[4:])
            and receipt.get('states',{}).get('DR-batch')):
        resume=dict(action='start',revision=17,retry=index+1,binary_sha256=receipt['binary_sha256'],
                    restores=f'D12_{durable}',checkpoint={'sha256':receipt['states']['DR-batch']},
                    replays_upstream=False)
    if (revision==17 and index==1 and durable==4761 and receipt.get('returncode') and cause
            and 'key points unreachable' in cause and (family/'terminal-eco/terminal-eco-proof.json').is_file()):
        from resume_space import qualified_terminal_eco
        _,proof=qualified_terminal_eco(work)
        resume=dict(action='start',revision=17,retry=2,binary_sha256=receipt['binary_sha256'],
                    restores='D12_4761',checkpoint={'sha256':proof['derived']},
                    repaired_nets=proof['repaired_nets'],original_sha256=proof['original'],replays_upstream=False)
    return {'run':family.name,'attempt':work.name,'phase':phase,'saved_dr_boxes':durable,'native_failure':cause,'resume_available':resume,'continuation':next_step,'backend':backend,'pid':record.get('pid'),'progress':lines[-1:] or [],
            'delivery':json.loads(manifest.read_bytes()) if manifest.exists() and next_step.get('phase')=='delivery' else None,
            'binary_sha256':record.get('binary_sha256') or protocol.get('contract',{}).get('binary'),
            'legalization_def_sha256':protocol.get('contract',{}).get('legalized_def'),
            'state_binding':protocol.get('sha256'),'iteration':iteration,'native_log_timezone':'UTC','budget':budget,
            'pa_verified':(family/'pa-accepted.json').is_file(),'states':[s for s in ('TG','LA','SR','TA') if any((p/(s+'.bin')).is_file() for p in (family,family/'recovery-v12',family/'recovery-v13',work))],
            'receipt':receipt or None}


def dispatch(op):
    if op not in ('start','status'): raise ValueError('Unknown routing operation')
    root=RUNS/'dispatch-v11'
    root.mkdir(exist_ok=True)
    with (root/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        current=status(root)
        if op=='start' and current['phase']=='failed' and current['resume_available']:
            resume=current['resume_available']
            revision=resume['revision']
            index=resume.get('retry',0)
            target=root/(f'repair-v{revision}'+(f'-r{index}' if index else ''))
            target.mkdir(exist_ok=True)
            with (target/'launcher.log').open('xb') as log:
                p=subprocess.Popen([sys.executable,'-u','continue_space.py',str(revision)],cwd=Path(__file__).resolve().parent,env=dict(os.environ,BP_MULTI_RETRY=str(index)),
                                   stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                save(target/'launch.json',{'pid':p.pid,'start_ticks':identity(p.pid),'binary_sha256':resume['binary_sha256']})
            return status(root)
        if op=='start' and current['phase']=='ready':
            binary=Path('/srv/edagent/bp-multi-official-build-v1')/('frozen-'+DR_SHA[:16])/'iEDA'
            if sha(binary)!=DR_SHA:raise ValueError('Unverified router')
            with (root/'launcher.log').open('xb') as log:
                p=subprocess.Popen([sys.executable,'-u','verify_pa_v11.py','run','--case','full','--mode','lazy',
                                    '--binary',str(binary),'--sha',DR_SHA],cwd=Path(__file__).resolve().parent,
                                   stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                save(root/'launch.json',{'pid':p.pid,'start_ticks':identity(p.pid)})
            current=status(root)
        if op=='start' and current['phase'] in ('running','completed') and not (root/'continuation.json').exists():
            with (root/'continuation.log').open('ab') as log:
                subprocess.Popen([sys.executable,'-u','continue_dispatch.py'],cwd=Path(__file__).resolve().parent,
                                 stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        return current


if __name__=='__main__':
    print(json.dumps(dispatch(sys.argv[1])))
