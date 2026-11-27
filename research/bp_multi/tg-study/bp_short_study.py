"""Fixed bp_multi branch: native marker inventory, paired controls and isolated ECO."""
import argparse
from collections import Counter, defaultdict
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time
from contextlib import contextmanager

ROOT = Path('/srv/edagent/main-agent-remote-v1')
sys.path[:0] = [str(ROOT), str(ROOT/'qualification-evidence/catalog-v1/bp_multi_official')]
from macro_agent.drc_counts import marker_stream, AUDITED_BINARY
from macro_agent.def_validation import read_def
from def_conductors import PhysicalLibrary, independent_graph

FAMILY = ROOT/'runs/bp-multi-official-pa-v1/full-lazy-a299a1d992ac'
BACK = FAMILY/'backend'
WORK = FAMILY/'short-study-v1'
ORIGINAL = BACK/'delivery/final.def'
REFERENCE = ROOT/'runs/bp-multi-tg-study-20261121/reference'
MARKERS = BACK/'result/report/violations.json'
HASH = 'cfa1cf9b26c4862565e94535e6cfe0528f4b769d55ba0198507216318552f5d6'
VIA = ['via1_4','via2_5','via3_2','via4_0','via5_0']
ENTRY = re.compile(r'^- (\S+) .*?;',re.M|re.S)
ROUTE = re.compile(r'(?:\+ ROUTED|NEW)\s+(metal\d+)\s+\(\s*(-?\d+) (-?\d+) \)\s+(?:\(\s*(\*|-?\d+) (\*|-?\d+) \)|(via\d+_\d+))')
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''): h.update(chunk)
    return h.hexdigest()
def save(path,value):
    tmp=path.with_suffix('.writing')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    tmp.replace(path)
def read(p): return json.loads(p.read_bytes())
def tile(box):
    x,y,a,b=box
    return ((x+a)//400000,(y+b)//400000)
def entries(text):
    a=re.search(r'^NETS \d+ ;',text,re.M).end()
    b=text.index('END NETS',a)
    yield from ENTRY.finditer(text,a,b)
def markers(path):
    for kind,row in marker_stream(path):
        if kind=='marker':yield row
def scan():
    if digest(ORIGINAL)!=HASH:raise ValueError('Parent identity changed')
    layers=Counter();tiles=Counter();nets=Counter();card=Counter();layer_tiles=defaultdict(Counter)
    by_layer=defaultdict(Counter)
    with gzip.open(WORK/'production.keys.gz','wt') as out:
        for m in markers(MARKERS):
            print(m['canonical_key'],file=out)
            if m['type']!='metal_short':continue
            l=m['layer'];t=tile(m['bbox']);ids=m['net_ids']
            layers[l]+=1;tiles[t]+=1;layer_tiles[t][l]+=1;card[len(ids)]+=1;nets.update(ids)
            by_layer[l][t]+=1
    assert sum(layers.values())==213494
    def tile_row(t,n):
        return dict(bounds_um=[100*t[0],100*t[1],100*(t[0]+1),100*(t[1]+1)],count=n,layers=dict(layer_tiles[t]))
    result=dict(parent=HASH,layers=layers,net_cardinality=card,top_nets=nets.most_common(15),
                tiles=[tile_row(t,n) for t,n in tiles.most_common()],per_layer_top={l:[tile_row(t,n) for t,n in c.most_common(3)] for l,c in by_layer.items()},
                die_um=[0,0,1153.49,1162],tile_um=100,rule_count=213494)
    save(WORK/'diagnosis.json',result)
def net_checkpoint(p):
    with p.open('rb') as f:
        def num():return struct.unpack('<i',f.read(4))[0]
        def string():return f.read(num()).decode()
        assert string()=='ieda-route-state-v1'
        assert string()=='D12_4761'
        binding=string()
        count=num();f.read(8)
        names=[]
        for i in range(count):
            assert i==num()
            names.append(string());f.read(32)
            for j in range(num()):
                assert j==num()
                string();f.read(20)
        for name in names:yield name,f.read(24*num())
        for name in names:f.seek(24*num(),1)
        for name in names:yield name,f.read(36*num())
def projected():
    before=FAMILY/'recovery-v17-r1/DR-batch.bin'
    after=FAMILY/'terminal-eco/native-probe/terminal-native.bin'
    proof=read(FAMILY/'terminal-eco/terminal-eco-proof.json')
    assert digest(before)==proof['original'] and digest(after)==proof['derived']
    left={};right={};count=0;patch_changed=0
    for (a,x),(b,y) in zip(net_checkpoint(before),net_checkpoint(after),strict=True):
        assert a==b
        if x!=y:
            if count>=78493: patch_changed+=1
            else:left[a]=x;right[a]=y
        count+=1
    assert count==2*78493 and not patch_changed
    text=ORIGINAL.read_text()
    def primitives(buf):
        paths=[]
        for x,y,l,a,b,m in struct.iter_unpack('<6i',buf):
            if l==m:
                if (x,y)!=(a,b):paths.append(f'metal{l+1} ( {x} {y} ) ( {a} {b} )')
            else:
                assert (x,y)==(a,b)
                for z in range(min(l,m),max(l,m)):
                    paths.append(f'metal{z+2} ( {x} {y} ) {VIA[z]}')
        return paths
    for label,changes in [('pre',left),('control',right)]:
        folder=WORK/label;folder.mkdir(exist_ok=True)
        start=0;seen=set()
        with (folder/'input.def').open('w') as f:
            for m in entries(text):
                name=m[1]
                if name not in changes:continue
                prefix=m[0].partition('+ ROUTED')[0]
                assert len(prefix)<len(m[0]) and ' RECT ' not in m[0],name
                paths=primitives(changes[name])
                assert paths
                f.write(text[start:m.start()]+prefix+'+ ROUTED  '+'\n    NEW  '.join(paths)+' ;')
                start=m.end();seen.add(name)
            f.write(text[start:])
        assert seen==changes.keys(),(len(seen),len(changes))
    save(WORK/'projection.json',dict(changed_nets=sorted(left),count=len(left),original_checkpoint=proof['original'],post_checkpoint=proof['derived'],patch_records_changed=0))
def native_drc(folder):
    from macro_agent import bp_multi_native
    from macro_agent.portable_ieda import ENV, IMAGE
    if digest(ROOT.parent/'portable-runtime-v1/iEDA')!=AUDITED_BINARY:raise ValueError('Checker changed')
    (folder/'result/report').mkdir(parents=True,exist_ok=True)
    (folder/'result/drc').mkdir(exist_ok=True)
    if not (folder/'config').exists():shutil.copytree(BACK/'config',folder/'config')
    tcl=(BACK/'drc.tcl').read_text()
    # Same native initialization and run_drc statement as the accepted parent.
    tcl=tcl.split('save_drc -path')[0].replace('/work/result/filler.def','/work/input.def')+'puts BP_DRC_DONE\n} message]} {puts stderr $message; exit 1}\nflow_exit\n'
    (folder/'drc.tcl').write_text(tcl)
    (folder/'logs').mkdir(exist_ok=True)
    native_env=dict(ENV,OMP_NUM_THREADS='4',OMP_THREAD_LIMIT='4',OPENBLAS_NUM_THREADS='1',RESULT_DIR='/work/result',CONFIG_DIR='/work/config',TCL_SCRIPT_DIR='/work/script')
    args=['run','--rm','--pull=never','--name','aieda-bpshort-'+folder.name,'--network','none','--cpus','4','--memory','8g','--pids-limit','128',
          '--mount',f'type=bind,source={folder},target=/work','--mount',f'type=bind,source={REFERENCE},target=/reference,readonly',*[v for k,val in native_env.items() for v in ('--env',k+'='+val)],IMAGE,'timeout','--kill-after=5','21600','iEDA','-script','/work/drc.tcl']
    env=dict(os.environ,PYTHONPATH=str(ROOT),AIEDA_NATIVE_HANDLES=str(WORK/'handles'))
    with (folder/'drc.log').open('w') as log:
        subprocess.run([sys.executable,'-B','-m','macro_agent.bp_multi_native',*args],env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    assert 'BP_DRC_DONE' in (folder/'drc.log').read_text(errors='replace')
    report=folder/'result/report'
    ms=report/'violations.json';counts=Counter()
    with gzip.open(folder/'keys.gz','wt') as out:
        for m in markers(ms):
            counts[m['type']]+=1;print(m['canonical_key'],file=out)
    summary=read(report/'drc_summary.json')
    assert sum(counts.values())==summary['violation_count']
    save(folder/'receipt.json',dict(checker=AUDITED_BINARY,input=digest(folder/'input.def'),rules=counts,total=sum(counts.values()),
         markers=digest(ms),config=digest(folder/'config/drc_default_config.json'),checked=summary['checked']))
    # Preserve one native marker export and its compact identity list.
    marker_sha=digest(ms)
    for duplicate in (report/'violation_map.json',report/'drc.rpt.artifacts/violation_map.json',report/'drc.rpt.artifacts/violations.json'):
        if duplicate.is_file() and digest(duplicate)==marker_sha:duplicate.unlink()
def keys(p,rule=None):
    with gzip.open(p,'rt') as f:return {s.rstrip('\n') for s in f if rule is None or s.startswith(rule+'|')}
def compare():
    prod=keys(WORK/'production.keys.gz','metal_short');pre=keys(WORK/'pre/keys.gz','metal_short');ctrl=keys(WORK/'control/keys.gz','metal_short')
    assert len(prod)==213494
    item=dict(production=len(prod),pre_raw_projection=len(pre),post_raw_control=len(ctrl),post_control_only=len(ctrl-prod),production_only=len(prod-ctrl),
        production_pre_and_post_control=len(prod&pre&ctrl),production_only_after_in_paired_projection=len((prod&ctrl)-pre),
        production_pre_but_not_control=len((prod&pre)-ctrl),production_neither_projection=len(prod-(pre|ctrl)),paired_removed=len(pre-ctrl),paired_added=len(ctrl-pre),
        final_vs_pre_shared=len(prod&pre),final_vs_pre_added=len(prod-pre),final_vs_pre_removed=len(pre-prod))
    save(WORK/'attribution.json',item)
