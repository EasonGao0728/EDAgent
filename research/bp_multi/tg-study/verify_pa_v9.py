"""Server-side independent PA admission against the frozen bp_multi DEF."""
import argparse
import csv
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path('/srv/edagent/main-agent-remote-v1')
sys.path.insert(0, str(ROOT/'qualification-evidence/catalog-v1/tg-study'))
from full_v2 import BASE, SOURCE, DEF_HASH, STUDY, RT, limits, setup, remote_service, active_jobs, sha, save, read_def, section
from macro_agent.pin_metrics import transform

RUNS = ROOT/'runs/bp-multi-official-pa-v1'


def prepare_cases():
    setup()
    RUNS.mkdir(exist_ok=True)
    db = read_def(SOURCE)
    macro_names = set(json.loads((BASE/'manifest.json').read_bytes())['expected_macro_masters'])
    nets = {k: pins for k, pins in db['nets'].items() if len(pins) >= 2}
    assert (len(nets), sum(map(len, nets.values()))) == (78493, 270267)
    chosen = set()
    touched = set()
    for name, pins in sorted(nets.items(), key=lambda item: (len(item[1]), item[0])):
        have = {inst for inst, pin in pins} & macro_names
        if have - touched:
            chosen.add(name)
            touched |= have
    assert touched == macro_names
    chosen.add('ib2d_bit_36271')
    ionets = [n for n,p in nets.items() if any(i=='PIN' for i,_ in p)]
    chosen.update(ionets[::max(1,len(ionets)//8)][:8])
    io = {pin for name in chosen for inst,pin in nets[name] if inst=='PIN'}
    text = SOURCE.read_text()
    for name, keys in [('NETS', chosen), ('PINS',io)]:
        records = [r for r in section(text,name) if r.split()[0] in keys]
        assert len(records) == len(keys)
        replacement = f'{name} {len(records)} ;\n'+''.join('- '+r+' ;\n' for r in records)+'END '+name
        text = re.sub(r'^'+name+r'\s+\d+\s*;.*?^END '+name+r'\s*$',lambda _: replacement,text,flags=re.S|re.M)
    path = RUNS/'macro-io-probe.def'
    if not path.exists():
        path.write_text(text)
    assert path.read_text()==text
    probe=read_def(path)
    assert probe['components']==db['components'] and probe['physical']==db['physical']
    assert probe['nets']=={k:nets[k] for k in chosen}
    single='cts_flow_clk_0_core_clock_hard_macro_cluster_sink_net_1'
    record=next(r for r in section(text,'NETS') if r.split()[0]==single)
    single_text=re.sub(r'^NETS\s+\d+\s*;.*?^END NETS\s*$',lambda _: 'NETS 1 ;\n- '+record+' ;\nEND NETS',text,flags=re.M|re.S)
    single_text=re.sub(r'^PINS\s+\d+\s*;.*?^END PINS\s*$','PINS 0 ;\nEND PINS',single_text,flags=re.M|re.S)
    pair=RUNS/'cts-pair.def'
    if not pair.exists():pair.write_text(single_text)
    assert pair.read_text()==single_text and read_def(pair)['nets']=={single:nets[single]}
    single='fanout_net_897'
    record=next(r for r in section(SOURCE.read_text(),'NETS') if r.split()[0]==single)
    assert not any(i=='PIN' for i,p in nets[single])
    fanout_text=re.sub(r'^NETS\s+\d+\s*;.*?^END NETS\s*$',lambda _: 'NETS 1 ;\n- '+record+' ;\nEND NETS',single_text,flags=re.M|re.S)
    fanout=RUNS/'fanout.def'
    if not fanout.exists():fanout.write_text(fanout_text)
    assert fanout.read_text()==fanout_text and read_def(fanout)['nets']=={single:nets[single]}
    result={'checkpoint':sha(SOURCE),'full_routable_nets':len(nets),'full_endpoints':sum(map(len,nets.values())),
            'probe_def':sha(path),'probe_nets':len(chosen),'probe_pins':sum(len(nets[k]) for k in chosen),
            'probe_top_ports':len(io),'probe_macro_instances':len(touched)}
    save(RUNS/'inputs.json',result)
    print(json.dumps(result),flush=True)


def pin_geometry(db,ref):
    layers={}
    units=db['units']
    dbu=lambda x:int(Decimal(x)*units)
    for path in sorted((ref/'data').glob('*.lef')):
        for master in re.finditer(r'^MACRO (\S+)\s*$(.*?)^END \1\s*$',path.read_text(),re.M|re.S):
            body=master[2]
            orig=re.search(r'\bORIGIN\s+([-\d.]+)\s+([-\d.]+)',body)
            if orig and any(dbu(n) for n in orig.groups()):raise ValueError('Nonzero LEF origin')
            size=tuple(map(dbu,re.search(r'\bSIZE\s+([\d.]+) BY ([\d.]+)',body).groups()))
            pins={}
            for pin in re.finditer(r'^\s*PIN (\S+)\s*$(.*?)^\s*END \1\s*$',body,re.M|re.S):
                if re.search(r'\b(POLYGON|PATH|ITERATE|MASK|VIA)\b',pin[2]): raise ValueError('Unsupported pin geometry')
                rects={}
                for block in re.finditer(r'\bLAYER (\S+)\s*;(.*?)(?=\bLAYER |\Z)',pin[2],re.S):
                    for row in re.finditer(r'\bRECT\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*;',block[2]):
                        rects.setdefault(block[1],[]).append(tuple(map(dbu,row.groups())))
                pins[pin[1]]=rects
            layers[master[1]]=(size,pins)
    ports={}
    for name,row in db['pins'].items():
        q=re.search(r'\+\s+(?:FIXED|PLACED)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\S+)',row)
        if not q or row.count('+ PORT')>1:raise ValueError('Unsupported IO placement')
        rects={}
        for match in re.finditer(r'\+ LAYER (\S+)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)',row):
            rects.setdefault(match[1],[]).append(tuple(map(int,match.groups()[1:])))
        ports[name]=(int(q[1]),int(q[2]),q[3],rects)
    def contains(inst,pin,layer,x,y):
        if inst=='PIN':
            ox,oy,orient,rects=ports[pin];w=h=0
        else:
            c=db['components'][inst];_,ox,oy,orient=c['placement']
            (w,h),pins=layers[c['master']];rects=pins[pin]
        for lx,ly,ux,uy in rects.get(layer,[]):
            x1,y1=transform(lx,ly,w,h,orient);x2,y2=transform(ux,uy,w,h,orient)
            if min(x1,x2)<=x-ox<=max(x1,x2) and min(y1,y2)<=y-oy<=max(y1,y2):return True
        return False
    return contains


def pa_check(work, db, max_rss, max_vm, contains):
    expected={(net,p if i=='PIN' else i+':'+p):(i,p) for net,pins in db['nets'].items() if len(pins)>=2 for i,p in pins}
    needed=len(expected)
    die=db['die']
    track_pattern=r'([XY]) (\d+) DO (\d+) STEP (\d+) LAYER (\S+)'
    tracks=set()
    for record in db['physical']['TRACKS']:
        axis,start,count,pitch,layer=re.fullmatch(track_pattern,record).groups()
        tracks.add((layer,axis,start,count,pitch))
    log=(work/'result/rt/rt.log').read_text(errors='replace')
    actual=set(re.findall(r'EDA_DEF_TRACK layer=(\S+) axis=([XY]) start=(\d+) count=(\d+) pitch=(\d+)',log))
    if tracks!=actual:
        raise ValueError(f'DEF tracks differ: expected {len(tracks)}, observed {len(actual)}, missing {sorted(tracks-actual)[:2]}')
    declared=re.search(r'EDA_PA_COVERAGE expected=(\d+) resolved=(\d+)',log)
    if not declared or tuple(map(int,declared.groups()))!=(needed,needed):
        raise ValueError(f'Native endpoint totals differ from frozen DEF {needed}')
    layers={r[0] for r in tracks}
    with (work/'pa.tsv').open() as stream:
        rows=csv.DictReader(stream,delimiter='\t')
        for r in rows:
            key=(r['net'],r['pin'])
            x,y=int(r['x']),int(r['y'])
            if key not in expected or r['layer'] not in layers or not(die[0]<=x<=die[2] and die[1]<=y<=die[3]):
                raise ValueError(f'Invalid or repeated endpoint {key} {x} {y}')
            i,p=expected.pop(key)
            if not contains(i,p,r['layer'],x,y):raise ValueError(f'AP outside independently transformed pin shape: {key} {x} {y}')
    if expected or not (0<max_rss<=8*2**30 and 0<max_vm<=8*2**30):
        raise ValueError(f'Unresolved endpoints or unavailable/out-of-contract memory: {len(expected)}, {max_rss}, {max_vm}')
    return {'expected_endpoints':needed,'matched_endpoints':needed,'independent_pin_shapes_matched':needed,'tracks_matched':len(tracks),'vm_hwm_bytes':max_rss,
            'vm_peak_bytes':max_vm,'ap_witness_sha256':sha(work/'pa.tsv'),'passed':True}


def usage(child):
    # Only descend from this sandbox process. VmPeak is single-process virtual size, VmHWM resident size.
    pending=[child]
    rss=vm=0
    while pending:
        pid=pending.pop()
        path=Path('/proc')/str(pid)
        try:
            pending.extend(map(int,(path/'task'/str(pid)/'children').read_text().split()))
            if (path/'comm').read_text().strip()!='iEDA':
                continue
            data=(path/'status').read_text()
            hwm=re.search(r'^VmHWM:\s+(\d+)',data,re.M)
            peak=re.search(r'^VmPeak:\s+(\d+)',data,re.M)
            if hwm and peak:
                rss=max(rss,int(hwm[1])*1024)
                vm=max(vm,int(peak[1])*1024)
        except (FileNotFoundError,ProcessLookupError):
            continue
    return rss,vm


def run(opts):
    ref=setup()
    source={'extreme':STUDY/'extreme.def','macro-io':RUNS/'macro-io-probe.def','cts-pair':RUNS/'cts-pair.def','abutment':RUNS/'abutment-126.def','fanout':RUNS/'fanout.def','full':SOURCE}[opts.case]
    binary=Path(opts.binary).resolve(strict=True)
    if sha(binary)!=opts.sha or sha(SOURCE)!=DEF_HASH: raise ValueError('Binary or checkpoint digest mismatch')
    snapshot=json.loads((binary.parent/'snapshot.json').read_bytes())
    if snapshot['upstream_commit']!='65c39fd28aa0dc0cdd56325df07f6e440069061b' or snapshot['binary_sha256']!=opts.sha:
        raise ValueError('Snapshot identity mismatch')
    if any(sha(Path(p))!=digest for p,digest in snapshot['runtime_system_libs_sha256'].items()):
        raise ValueError('Runtime system libraries changed since freeze')
    db=read_def(source)
    contains=pin_geometry(db,ref)
    work=RUNS/(opts.case+'-'+opts.mode+'-'+opts.sha[:12]+('-trace' if opts.trace else ''))
    if (work/'receipt.json').is_file():
        saved=json.loads((work/'receipt.json').read_bytes())
        print(json.dumps(saved));return saved
    if opts.case=='full':
        for c in ('extreme','macro-io','abutment'):
            comparison=[]
            for mode in ('eager','lazy'):
                row=json.loads((RUNS/(c+'-'+mode+'-'+opts.sha[:12])/'receipt.json').read_bytes())
                if not(row.get('stop_reason')=='completed_pa_measurement' and row['pa']['passed']):
                    raise ValueError('Missing successful canary '+c)
                comparison.append(row['pa']['ap_witness_sha256'])
            if comparison[0]!=comparison[1]:
                raise ValueError('PA witnesses differ, investigate before full route: '+c)
    work.mkdir()
    (work/'result/rt').mkdir(parents=True)
    (work/'result/report').mkdir()
    shutil.copytree(BASE/'config',work/'config')
    tcl=(BASE/'routing.tcl').read_text().replace('/work/result/legalization.def','/frozen.def')
    (work/'route.tcl').write_text(tcl)
    args=['bwrap','--die-with-parent','--unshare-user','--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts']
    for p in ('/usr','/bin','/lib','/lib64'):args+=['--ro-bind',p,p]
    for p,target in [(binary,'/official/iEDA'),(RT,'/runtime'),(ref,'/reference'),(source,'/frozen.def')]:
        args+=['--ro-bind',str(p),target]
    args+=['--proc','/proc','--dev','/dev','--tmpfs','/tmp','--bind',str(work),'/work','--chdir','/work','--clearenv']
    env={'PATH':'/usr/bin:/bin','HOME':'/tmp','TCL_LIBRARY':'/runtime/tcl8.6','LC_ALL':'C','OMP_NUM_THREADS':'4','OMP_THREAD_LIMIT':'4','OPENBLAS_NUM_THREADS':'1','IEDA_RT_PORT_NATIVE':'1',
         'IEDA_RT_PA_LAZY_TARGETS':str(int(opts.mode=='lazy')),'IEDA_RT_PA_WITNESS':'/work/pa.tsv','IEDA_RT_PA_GATE':'/work/gate',
         'RESULT_DIR':'/work/result','CONFIG_DIR':'/work/config'}
    timeout=4989 if opts.case=='full' else 300
    if sha(ref/'data/input2.lef')!='834a79295054cd4209178d1bade67c353863c47bb4b3c22ee38b862b7cec37f2':
        raise ValueError('Unreviewed technology for the metal2 rectangular PRL rule')
    env['IEDA_RT_PA_RECT_PRL']='1'
    if opts.case=='cts-pair':
        env['IEDA_RT_PA_TRACE_PIN']='cts_flow_clk_0_core_clock_hard_macro_cluster_buf_1:Z'
    if opts.case=='fanout':
        env['IEDA_RT_PA_TRACE_PIN']='gen_85648_:S'
    args+=['--ro-bind','/srv/edagent/main-agent-remote-v1/runs/bp-multi-sram-ce-escape-drc-v1/screened-escapes.tsv','/screened.tsv']
    env['IEDA_RT_PA_ESCAPE_FILE']='/screened.tsv'
    if opts.case=='full':
        from qualify_route_state import configure
        configure(work,source,binary,Path('/srv/edagent/main-agent-remote-v1/runs/bp-multi-sram-ce-escape-drc-v1/screened-escapes.tsv'),env)
    for k,v in env.items():args+=['--setenv',k,v]
    args+=['/usr/bin/timeout','--foreground','--kill-after=5',str(timeout)]
    if opts.trace:
        args+=['/usr/bin/strace','-f','-qq','-k','-e','trace=tgkill','-e','signal=SIGSEGV,SIGABRT','-o','/work/stack.txt']
    args+=['/official/iEDA','-script','/work/route.tcl']
    receipt={'case':opts.case,'mode':opts.mode,'binary_sha256':opts.sha,'input_sha256':sha(source),'checkpoint':DEF_HASH,
             'timeout_s':timeout,'cpus':4,'address_space_gib':8,'env':env,'pa':{'passed':False},'stage_marker':False}
    start=time.monotonic()
    rss=vm=0
    with (work/'stdout.log').open('wb') as log:
        proc=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,preexec_fn=limits)
        from macro_agent.remote_native import identity
        save(RUNS/'qualification-live.json',{'pid':proc.pid,'start_ticks':identity(proc.pid),
             'case_id':'bp_multi','stage':'routing / '+opts.case+' / '+opts.mode,
             'run':work.name,'input_sha256':sha(source)})
        try:
            while proc.poll() is None:
                r,v=usage(proc.pid)
                rss=max(rss,r);vm=max(vm,v)
                if not receipt['pa']['passed'] and (work/'gate.ready').exists():
                    receipt['pa']=pa_check(work,db,rss,vm,contains)
                    save(work/'pa-accepted.json',receipt['pa'])
                    if opts.case=='full':
                        (work/'gate.accept').touch(exist_ok=False)
                    else:
                        receipt['stop_reason']='completed_pa_measurement'
                        os.killpg(proc.pid,signal.SIGTERM)
                        break
                time.sleep(.5)
        except Exception as exc:
            receipt['gate_error']=str(exc)
            if proc.poll() is None:os.killpg(proc.pid,signal.SIGTERM)
        finally:
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGKILL);proc.wait()
    receipt.update(returncode=proc.returncode,wall_s=round(time.monotonic()-start,3),peak_rss_bytes=rss,peak_vm_bytes=vm,
                   stage_marker='SWERV_STAGE_OK routing' in (work/'stdout.log').read_text(errors='replace'))
    from qualify_route_state import record
    record(work,receipt)
    save(work/'receipt.json',receipt)
    print(json.dumps(receipt),flush=True)
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','run'])
    parser.add_argument('--case',choices=['extreme','macro-io','cts-pair','abutment','fanout','full'])
    parser.add_argument('--mode',choices=['eager','lazy'])
    parser.add_argument('--binary');parser.add_argument('--sha')
    parser.add_argument('--trace',action='store_true')
    opts=parser.parse_args()
    if opts.action=='prepare':prepare_cases()
    else:
        remote_service.init()
        with remote_service.gate():
            if active_jobs():raise RuntimeError('Other native job active')
            result=run(opts)
        ok=result['pa']['passed'] and (result.get('stop_reason')=='completed_pa_measurement'
                                      if opts.case!='full' else result['returncode']==0 and result['stage_marker'])
        sys.exit(0 if ok else 1)
