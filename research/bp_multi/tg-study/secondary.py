"""Test the two observed bottlenecks without replaying placement."""
import json,re
from full_v2 import BASE,STUDY,SOURCE,read_def,section,sha,save,run,setup,remote_service,active_jobs
remote_service.init()
with remote_service.gate():
    if active_jobs():raise RuntimeError('Server busy')
    ref=setup()
    failed=json.loads((STUDY/'full-subdivision-12-r1/receipt.json').read_bytes())
    assert failed['exit']==139 and failed['tg_complete'] is False
    # Native allocator settings only, same snapshot/input/physical algorithm/cap.
    run(ref,'full','subdivision',12,allocator_trial=True)
    db=read_def(SOURCE);rows=section(SOURCE.read_text(),'NETS')
    macros=json.loads((BASE/'manifest.json').read_bytes())['expected_macro_masters']
    pool=[]
    for name,pins in db['nets'].items():
        if len(pins)!=2 or any(n=='PIN' or n in macros for n,_ in pins):continue
        a,b=[db['components'][n]['placement'][1:3] for n,pin in pins]
        dx=abs(a[0]-b[0]);dy=abs(a[1]-b[1])
        if dx and dy:pool.append((dx*dy,name))
    pool.sort()
    for label,lower,upper in [('tail48',.95,1.),('control48',.05,.75)]:
        names={pool[round((len(pool)-1)*(lower+(upper-lower)*t/47))][1] for t in range(48)}
        assert len(names)==48
        subset=[r for r in rows if r.split()[0] in names]
        text=SOURCE.read_text()
        text=re.sub(r'^NETS\s+\d+\s*;.*?^END NETS\s*$',lambda _:'NETS 48 ;\n'+''.join('- '+r+' ;\n' for r in subset)+'END NETS',text,flags=re.M|re.S)
        text=re.sub(r'^PINS\s+\d+\s*;.*?^END PINS\s*$','PINS 0 ;\nEND PINS',text,flags=re.M|re.S)
        p=STUDY/(label+'.def')
        if not p.exists():p.write_text(text)
        d=read_def(p)
        assert d['physical']==db['physical'] and d['components']==db['components'] and d['nets']=={n:db['nets'][n] for n in names}
        save(STUDY/(label+'.json'),{'source':sha(SOURCE),'input':sha(p),'nets':sorted(names),'quantiles':[lower,upper]})
        for variant,span in [('original',0),('subdivision',0),('subdivision',12)]:
            r=run(ref,label,variant,span)
            if not r['tg_complete'] and r['exit']!=124:raise RuntimeError('Missing cohort receipt')
