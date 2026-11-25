"""Compare frozen full bp_multi placement and one M3 terminal route, using native standalone iDRC."""
import argparse
from collections import Counter
import csv
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT=Path('/srv/edagent/main-agent-remote-v1')
sys.path.insert(0,str(ROOT/'qualification-evidence/catalog-v1/tg-study'))
from full_v2 import BASE, SOURCE, STUDY, RT, DEF_HASH, sha, save, read_def, section, limits, remote_service, active_jobs, setup
from macro_agent.drc_counts import AUDITED_BINARY, marker_stream, reconcile
from def_conductors import PhysicalLibrary

WORK=ROOT/'runs/bp-multi-sram-ce-escape-drc-v1'
NET='ib2d_bit_1575'
PIN=('gen_139835_','ce_in')
WIRE=' + ROUTED metal3 ( 1308180 295910 ) ( 1307790 * )\n   NEW metal3 ( 1307790 295910 ) ( * 295820 )'
BOX=(1304600,292600,1311400,299200)


def check_one(kind,input_path,ref):
    work=WORK/kind
    if (work/'receipt.json').is_file():
        r=json.loads((work/'receipt.json').read_bytes())
        if r['def_sha256']!=sha(input_path):raise ValueError('changed input')
        return r
    work.mkdir()
    shutil.copytree(BASE/'config',work/'config')
    for sub in ('result/drc','result/report','logs'):(work/sub).mkdir(parents=True)
    script=(BASE/'routing.tcl').read_text().split('init_rt ')[0].replace('/work/result/legalization.def','/input.def')
    script+='run_drc -config /work/config/drc_default_config.json -path /work/result/report/drc.rpt\nputs CE_NATIVE_DRC_OK\n} message]} {puts stderr $message; exit 1}\nflow_exit\n'
    (work/'check.tcl').write_text(script)
    cmd=['bwrap','--die-with-parent','--unshare-user','--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts']
    for p in ('/usr','/bin','/lib','/lib64'):cmd+=['--ro-bind',p,p]
    for p,d in [(RT,'/rt'),(ref,'/reference'),(input_path,'/input.def')]:cmd+=['--ro-bind',str(p),d]
    cmd+=['--proc','/proc','--dev','/dev','--tmpfs','/tmp','--bind',str(work),'/work','--chdir','/work','--clearenv']
    for k,v in dict(PATH='/usr/bin:/bin',HOME='/tmp',TCL_LIBRARY='/rt/tcl8.6',LC_ALL='C',OMP_NUM_THREADS='4',
                    OMP_THREAD_LIMIT='4',OPENBLAS_NUM_THREADS='1',RESULT_DIR='/work/result',CONFIG_DIR='/work/config').items():
        cmd+=['--setenv',k,v]
    cmd+=['/usr/bin/timeout','--foreground','--kill-after=5','240','/rt/ld-linux-x86-64.so.2','--library-path','/rt/lib','/rt/iEDA','-script','/work/check.tcl']
    start=time.monotonic()
    with (work/'logs/drc.log').open('wb') as out:
        proc=subprocess.run(cmd,stdout=out,stderr=subprocess.STDOUT,preexec_fn=limits)
    rec=dict(kind=kind,returncode=proc.returncode,def_sha256=sha(input_path),checker=AUDITED_BINARY,
             seconds=round(time.monotonic()-start,3),script_sha256=sha(work/'check.tcl'))
    report=work/'result/report'
    if proc.returncode==0 and 'CE_NATIVE_DRC_OK' in (work/'logs/drc.log').read_text(errors='replace'):
        summary=json.loads((report/'drc_summary.json').read_bytes())
        rec.update(reconciliation=reconcile(summary,report,AUDITED_BINARY),checked=summary.get('checked'),skipped=summary.get('skipped'),
                   refused=summary.get('refused'),unsupported=summary.get('unsupported'),checked_summary=summary.get('status'),
                   marker_file_sha256=sha(report/'violations.json'))
    save(work/'receipt.json',rec)
    return rec


def marker_multiset(path):
    near=Counter();far=Counter();types=Counter()
    for kind,m in marker_stream(path):
        if kind!='marker':continue
        units=m['units']['dbu_per_micron']
        b=m['bbox']
        if units!=2000 or len(b)!=4:raise ValueError('unexpected marker coordinates')
        key=m['canonical_key']
        local=b[0]<=BOX[2] and b[2]>=BOX[0] and b[1]<=BOX[3] and b[3]>=BOX[1]
        (near if local else far)[key]+=1
        if local:types[m['type']]+=1
    return near,far,types


def run():
    assert sha(SOURCE)==DEF_HASH and sha(RT/'iEDA')==AUDITED_BINARY
    ref=setup()
    WORK.mkdir(exist_ok=True)
    text=SOURCE.read_text()
    orig=next(r for r in section(text,'NETS') if r.split()[0]==NET)
    assert 'ROUTED' not in orig and text.count(orig)==1
    dst=WORK/'only-ce-in-metal3.def'
    after=text.replace(orig,orig+WIRE)
    if not dst.exists():dst.write_text(after)
    assert dst.read_text()==after and after.replace(orig+WIRE,orig)==text and read_def(SOURCE)==read_def(dst)
    pair=[check_one('before',SOURCE,ref),check_one('after',dst,ref)]
    result=dict(checkpoint=DEF_HASH,wire=WIRE,region_dbu=BOX,reports=pair,net=NET,pin=PIN,accepted=False)
    if all(r.get('reconciliation',{}).get('passed') and r.get('checked') and not r.get('skipped') and not r.get('refused') for r in pair):
        if any(pair[0].get(k)!=pair[1].get(k) for k in ('checked','unsupported','checker')):raise ValueError('coverage changed')
        a,outside1,by1=marker_multiset(WORK/'before/result/report/violations.json')
        b,outside2,by2=marker_multiset(WORK/'after/result/report/violations.json')
        result.update(new_markers_local=dict(b-a),removed_markers_local=dict(a-b),new_outside=sum((outside2-outside1).values()),
                      removed_outside=sum((outside1-outside2).values()),before_local=dict(by1),after_local=dict(by2))
        result['no_added_reported_markers']=not(b-a) and outside1==outside2
    save(WORK/'comparison.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='reports'}))
    print([{k:v for k,v in r.items() if k not in ('unsupported','reconciliation')} for r in pair])


def controlled():
    """A distant explicit macro-OBS positive control makes both checker arms exercise native rules."""
    assert sha(SOURCE)==DEF_HASH and sha(RT/'iEDA')==AUDITED_BINARY
    ref=setup(); text=SOURCE.read_text()
    records={r.split()[0]:r for r in section(text,'NETS')}
    source=records['ib2d_bit_45033']
    control=WIRE.replace('295910','257270').replace('295820','257180')
    base=text.replace(source,source+control)
    raw=records[NET]
    trials={'flank-control':'','flank-control-pab':WIRE,
            'flank-control-flush':WIRE.replace('1308180 295910 )','1308180 295910 0 )',1)}
    out={}
    for kind,wire in trials.items():
        contents=base.replace(raw,raw+wire)
        path=WORK/(kind+'.def')
        if not path.exists():path.write_text(contents)
        assert text.count(source)==text.count(raw)==1 and path.read_text()==contents and read_def(path)==read_def(SOURCE)
        out[kind]=check_one(kind,path,ref)
    res={'control':control,'control_net':'ib2d_bit_45033','units':2000,'source':DEF_HASH,'anchor':PIN,'trial':{}}
    baseline=out['flank-control']
    a,oa,ta=marker_multiset(WORK/'flank-control/result/report/violations.json')
    if not oa:raise ValueError('positive control failed; no outside marker')
    for name,r in out.items():
        if not(r.get('reconciliation',{}).get('passed') and r['checked'] and not r['skipped'] and not r['refused']):
            raise ValueError('incomplete DRC '+name+': '+str(r.get('reconciliation',{}).get('errors')))
        if any(r.get(k)!=baseline.get(k) for k in ('checked','unsupported','checker','script_sha256')):raise ValueError('changed checking conditions')
        b,ob,tb=marker_multiset(WORK/name/'result/report/violations.json')
        res['trial'][name]={'def_sha256':r['def_sha256'],'marker_sha256':r['marker_file_sha256'],
            'checked':r['checked'],'unsupported':r['unsupported'],'source_total':r['reconciliation']['final_violation_count'],
            'added_nearby':dict(b-a),'removed_nearby':dict(a-b),'added_outside':dict(ob-oa),'removed_outside':dict(oa-ob),
            'qualifies_for_supported_rules_only':not(b-a) and oa==ob}
    save(WORK/'controlled-comparison.json',res)
    print(json.dumps(res))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--controlled',action='store_true')
    args=p.parse_args()
    remote_service.init()
    with remote_service.gate():
        if active_jobs():raise RuntimeError('Other native job active')
        if args.controlled: controlled()
        else: run()
