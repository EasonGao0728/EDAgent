"""Audit paired TG timings and full backend routing evidence without rerunning a stage."""
import collections
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path('/srv/edagent/main-agent-remote-v1')
sys.path.insert(0,str(ROOT))
from macro_agent.aes_reproduction import routing_observation
from macro_agent.aes_transforms import check
from macro_agent.def_validation import read_def
from macro_agent.swerv_backend import BUFFERS

STUDY=ROOT/'runs/bp-multi-tg-study-20261121'
BASE=ROOT/'runs/bringup-bp_multi-area130-cts100-drv2/attempt-inherited-drv2'
FULL=STUDY/'full-subdivision-12-r1'
def read(p):
    return json.loads(p.read_bytes())
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
def seconds(value):
    h,m,s=map(int,value.split(':'))
    return 3600*h+60*m+s
def progress(path):
    rows=[]
    for line in path.open(errors='replace'):
        m=re.search(r'TopologyGenerator\.cpp:\d+ Info generateTGModel\] Routed (\d+)/(\d+).*?elapsed = ([\d:]+), cpu = ([\d:]+)',line)
        if m:rows.append({'done':int(m[1]),'total':int(m[2]),'wall_s':seconds(m[3]),'cpu_s':seconds(m[4])})
    return rows

def audit():
    checkpoint=BASE/'result/legalization.def'
    samples=read(STUDY/'sample.json')
    assert sha(checkpoint)==samples['source_sha256']==read(BASE/'legalization-evidence.json')['artifact_sha256']
    results={'checkpoint':samples['source_sha256'],'eligible_two_pin_nets':samples['eligible_two_pin_nets'],'paired_samples':{},'poll_resolution_ms':25}
    for name,sample in samples['selected'].items():
        values={}
        for variant,span in [('original',0),('subdivision',0),('subdivision',12)]:
            f=STUDY/f'{name}-{variant}-{span}-r1/receipt.json';r=read(f)
            if not r['tg_complete'] or r['full'] or r['def_sha256']!=sample['def_sha256']:raise ValueError(str(f))
            values[variant+str(span)]={'observed_wall_s':r['tg_observed_wall'],'events':r['events'],'binary':r['binary_sha256'],'receipt_sha256':sha(f)}
        results['paired_samples'][name]=dict(sample,runs=values)
    cohorts = {}
    for label in ('tail48', 'control48'):
        selection = read(STUDY / (label + '.json'))
        assert selection['source'] == samples['source_sha256']
        assert len(set(selection['nets'])) == 48
        times = {}
        for variant, span in [('original', 0), ('subdivision', 0), ('subdivision', 12)]:
            receipt = STUDY / f'{label}-{variant}-{span}-r1/receipt.json'
            row = read(receipt)
            assert row['tg_complete'] and row['def_sha256'] == selection['input']
            assert not row['full'] and row['source_sha256'] == selection['source']
            times[f'{variant}{span}'] = {'tg_s': row['tg_observed_wall'], 'receipt_sha256': sha(receipt)}
        cohorts[label] = dict(selection, measurements=times)
    results['cohorts'] = cohorts
    old=progress(BASE/'result/rt/rt.log')
    prof=FULL/'protocol.json';f=FULL/'result/rt/rt.log'
    data={'original_tg_batches':old,'candidate_tg_batches':[],'candidate_router_exited':False,'route_accepted':False,'downstream_eligible':False}
    results['full_chip']=data
    if not prof.exists():return results
    pr=read(prof)
    assert pr['def_sha256']==samples['source_sha256'] and pr['cpu']==4 and pr['as_gib']==8 and pr['timeout']==4989
    assert pr['env']['IEDA_RT_BEST_EFFORT']=='0' and not any(k in pr['env'] for k in ('IEDA_RT_MAX_TG_NETS','IEDA_RT_MAX_BOXES','IEDA_RT_MAX_PA_BOXES'))
    data['protocol_sha256']=sha(prof)
    if not f.exists():return results
    new=progress(f);data['candidate_tg_batches']=new
    lines=f.read_text(errors='replace').splitlines()
    data['last_native_line']=lines[-1] if lines else None
    spans=[tuple(map(int,m.groups())) for l in lines if (m:=re.search(r'TG_SUBDIVISION net=(\d+) pins=(\d+) original_edges=(\d+) divided_edges=(\d+) output_edges=(\d+) largest_original_span=(\d+) max_edge_span=(\d+)',l))]
    data['subdivided_nets']=len({r[0] for r in spans})
    data['subdivided_nets_pin_count_histogram']=dict(sorted(collections.Counter(r[1] for r in spans).items()))
    data['max_original_edge_span']=max((r[5] for r in spans),default=None)
    data['tg_all_nets']=bool(new and new[-1]['done']==new[-1]['total']==old[-1]['total'] and any('Info generateTGModel] Completed' in l for l in lines))
    if new and old:
        oldrow=next((r for r in old if r['done']==77000),None)
        newrow=next((r for r in new if r['done']==77000),None)
        if oldrow and newrow and newrow['wall_s']:
            data['same_batch_70000_to_77000']={'old_s':oldrow['wall_s'],'candidate_s':newrow['wall_s'],'speedup':round(oldrow['wall_s']/newrow['wall_s'],2)}
    stages={}
    for l in lines:
        m=re.search(r'(PinAccessor|SupplyAnalyzer|TopologyGenerator|LayerAssigner|SpaceRouter|TrackAssigner|DetailedRouter|ViolationReporter)\.cpp:\d+ Info (access|analyze|generate|assign|route|report)\] Completed \(elapsed = ([\d:]+)',l)
        if m:stages[m[1]]=seconds(m[3])
    data['completed_native_routing_modules_s']=stages
    if not (FULL/'receipt.json').exists():return results
    receipt=read(FULL/'receipt.json');data.update(candidate_router_exited=True,exit_code=receipt['exit'],elapsed_s=receipt['elapsed'])
    monitor = [json.loads(line) for line in (FULL/'logs/routing-progress.jsonl').read_bytes().splitlines()]
    data['sampled_peak_router_rss_bytes'] = max(p['rss_bytes'] for row in monitor for p in row['processes'] if p['name'] == 'ld-linux-x86-64')
    def native_pa_memory(directory):
        log = (directory/'result/rt/rt.log').read_text(errors='replace')
        return {name: float(m.group(1)) for name in ['initAccessPointList', 'uploadAccessPointList']
                if (m := re.search(r'Info '+name+r'\] Completed [^\n]*?mem = ([\d.]+)MB', log))}
    data['pa_reported_delta_mb'] = {'original': native_pa_memory(BASE), 'candidate': native_pa_memory(FULL)}
    alloc = STUDY / 'full-subdivision-12-r1-malloc'
    if (alloc/'receipt.json').is_file():
        allocator = read(alloc/'receipt.json')
        data['allocator_screen'] = {'exit': allocator['exit'], 'reason': allocator['stop_reason'], 'elapsed_s': allocator['elapsed'],
                                    'comparison': read(next(alloc.glob('allocation*.json')))}
    diag = STUDY/'pa-pressure-6400m/receipt.json'
    if diag.is_file():
        pressure = read(diag)
        assert pressure['def_sha256'] == pr['def_sha256'] and pressure['binary_sha256'] == pr['binary_sha256']
        data['pressure_diagnostic'] = pressure
    unwind = STUDY/'pa-pressure-unwind-6400m'
    if (unwind/'receipt.json').is_file():
        row = read(unwind/'receipt.json')
        assert row['def_sha256'] == pr['def_sha256'] and row['binary_sha256'] == pr['binary_sha256']
        data['pressure_stack'] = dict(row, trace=(unwind/'memory.trace').read_text(errors='replace').splitlines())
    out=FULL/'result/routing.def';summary=FULL/'result/rt/violation_reporter/route_summary.json'
    data['routed_def_produced']=out.is_file()
    if receipt['exit']!=0 or not out.is_file() or not summary.is_file():return results
    native=routing_observation(read(summary))
    tr=check(read_def(checkpoint),read_def(out),'routing',BUFFERS,r'FILLCELL_X(1|2|4|8|16|32)')
    iterations=re.findall(r'DetailedRouter[^\n]*Begin iteration (\d+)/(\d+)', '\n'.join(lines))
    ends=re.findall(r'DetailedRouter[^\n]*End Iteration (\d+)/(\d+)', '\n'.join(lines))
    data.update(native_routing_gate=native,transformation=tr,def_sha256=sha(out),detailed_iterations=iterations)
    data['route_accepted']=bool(data['tg_all_nets'] and native['passed'] and tr['passed'] and iterations==ends==[('1','1')] and 'SWERV_STAGE_OK routing' in (FULL/'logs/routing.log').read_text(errors='replace'))
    data['downstream_eligible']=data['route_accepted']
    return results
if __name__=='__main__':print(json.dumps(audit(),indent=2))
