"""Dispatch native DRC-aware local routing only for explicitly diagnosed residual gaps."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
from bind_terminal_eco import derive,PARENT
from resume_space import FAMILY,BUILD,SOURCE,RT,TABLE,BINDING,read,save,setup,sha,limits,remote_service,active_jobs
from refine_terminal_tasks import refine


def prepare(root,study):
    work=root/'native-probe'
    work.mkdir(exist_ok=False)
    prior=FAMILY/'recovery-v17-r1'
    assert sha(prior/'DR-batch.bin')==PARENT
    bounded=root/'native-clean'
    best=root/'trade01/base.tsv'
    shutil.copy2(best,work/'screened.tsv')
    stub=read(bounded/'stub-proof.json')
    assert stub['original']==PARENT and stub['derived']==sha(bounded/'pruned.bin')
    derive(bounded/'pruned.bin',work/'partial.bin',best,{},partial=True)
    refine(bounded,prior,best,work/'residual.txt')
    with (work/'residual.txt').open() as src,(work/'requests.txt').open('w') as out:
        header=[list(map(int,next(src).split())) for _ in range(29)]
        requests=0
        for row in src:
            net,x,y,l,a,b,m,n,k=map(int,row.split())
            groups=[[tuple(map(int,next(src).split())) for _ in range(ct)] for ct in (n,k)]
            def on_pref(p):
                axis=1-p[2]%2
                start,count,pitch=header[1+2*p[2]+axis]
                return start<=p[axis]<start+count*pitch and (p[axis]-start)%pitch==0
            groups=[[p for p in grp if on_pref(p)] for grp in groups]
            _,left,right=min((abs(u[0]-v[0])+abs(u[1]-v[1])+280*abs(u[2]-v[2]),u,v)
                             for u in groups[0] for v in groups[1])
            x1,y1=[max(header[0][i],min(left[i],right[i])-4000) for i in (0,1)]
            x2,y2=[min(header[0][i+2],max(left[i],right[i])+4000) for i in (0,1)]
            sites=[]
            for group,goal in zip(groups,(right,left)):
                opts=sorted((p for p in group if x1<=p[0]<=x2 and y1<=p[1]<=y2),key=lambda p:abs(p[0]-goal[0])+abs(p[1]-goal[1])+280*abs(p[2]-goal[2]))
                selected=[]
                for p in opts:
                    if all(p[2]!=v[2] or abs(p[0]-v[0])+abs(p[1]-v[1])>=560 for v in selected):selected.append(p)
                    if len(selected)==12:break
                assert selected
                sites.append(selected)
            print(net,x1,y1,x2,y2,*(len(g) for g in sites),file=out)
            for group in sites:
                for p in group:print(*p,file=out)
            requests+=1
        assert requests==20
    return work


def launch():
    remote_service.init()
    with remote_service.gate():
        assert not active_jobs()
        root=FAMILY/'terminal-eco'
        work=prepare(root,Path(__file__).resolve().parent)
        ref=setup()
        snapshot=read(BUILD/'candidate-v18.json')
        exe=BUILD/('frozen-'+snapshot['binary_sha256'][:16])/'iEDA'
        assert snapshot['binary_sha256']==sha(exe)
        shutil.copytree(FAMILY/'config',work/'config')
        (work/'result/rt').mkdir(parents=True);(work/'result/report').mkdir()
        shutil.copy2(FAMILY/'route.tcl',work/'route.tcl')
        args=['bwrap','--die-with-parent','--unshare-user','--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts']
        for p in ('/usr','/bin','/lib','/lib64'):args+=['--ro-bind',p,p]
        for path,dest in [(exe,'/official/iEDA'),(RT,'/runtime'),(ref,'/reference'),(SOURCE,'/frozen.def'),(work/'partial.bin','/restore.bin'),(TABLE,'/screened.tsv'),(FAMILY/'recovery-v12/boundary-leads.tsv','/boundary.tsv')]:
            args+=['--ro-bind',str(path),dest]
        args+=['--proc','/proc','--dev','/dev','--tmpfs','/tmp','--bind',str(work),'/work','--chdir','/work','--clearenv']
        env=dict(read(FAMILY/'state-contract.json')['contract']['route_environment'])
        for k in ('IEDA_RT_PA_GATE','IEDA_RT_PA_WITNESS'):env.pop(k)
        env.update(IEDA_RT_RESTORE_LEVEL='D12_4761',IEDA_RT_RESTORE_STATE='/restore.bin',IEDA_RT_STATE_BINDING=BINDING,
                   IEDA_RT_NATIVE_TERMINAL_ECO='/work/requests.txt',IEDA_RT_SAVE_DR_BATCH='/work/terminal-native.bin',
                   IEDA_RT_BOUNDARY_LEADS='/boundary.tsv',MALLOC_ARENA_MAX='2',MALLOC_TRIM_THRESHOLD_='131072')
        for k,v in env.items():args+=['--setenv',k,v]
        with (work/'stdout.log').open('xb') as log:
            proc=subprocess.run(args+['/official/iEDA','-script','/work/route.tcl'],preexec_fn=limits,stdout=log,stderr=subprocess.STDOUT)
        rt=(work/'result/rt/rt.log').read_text()
        rows=(work/'native-eco.tsv').read_text().splitlines() if (work/'native-eco.tsv').exists() else []
        ok=proc.returncode==0 and len(rows)==20 and 'ECO_CHECKPOINT_READY requests=20' in rt and 'Restored route checkpoint D12_4761' in rt and 'DR boxes committed' not in rt
        receipt=dict(passed=ok,returncode=proc.returncode,rows=rows,binary=sha(exe),original=PARENT,partial=sha(work/'partial.bin'),requests=sha(work/'requests.txt'),screened=sha(work/'screened.tsv'))
        if ok:receipt['produced']=sha(work/'terminal-native.bin')
        save(work/'receipt.json',receipt)
        if not ok:raise RuntimeError(receipt)


if __name__=='__main__':launch()
