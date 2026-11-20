"""Analyze saved native logs and receipts, without executing any EDA stage."""
from pathlib import Path
import json,re

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/medium-macro-fullflow-20261114'
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
def seconds(t):
    h,m,s=map(int,t.split(':'));return h*3600+m*60+s
def log_stages(path):
    text=re.sub(r'\x1b\[[0-9;]*m','',path.read_text(errors='replace'))
    selected={'TopologyGenerator':'generate','LayerAssigner':'assign','SpaceRouter':'route','TrackAssigner':'assign','DetailedRouter':'route'}
    result={}
    for cls,fn in selected.items():
        pattern=rf'{cls}\.cpp:\d+ Info {fn}\] Completed \(elapsed = (\d+:\d+:\d+), cpu = (\d+:\d+:\d+)'
        matches=re.findall(pattern,text)
        if len(matches)!=1:raise ValueError(f'Expected exactly one completed {cls}: {path}')
        wall,cpu=map(seconds,matches[0]);result[cls]={'wall_seconds':wall,'cpu_seconds':cpu,'average_cpu_cores':cpu/wall}
    batches=[]
    for done,total,violations,wall,cpu in re.findall(r'DetailedRouter[^\n]*Routed (\d+)/(\d+)[^\n]*?boxes with (\d+) violations \(elapsed = (\d+:\d+:\d+), cpu = (\d+:\d+:\d+)',text):
        batches.append({'done':int(done),'total':int(total),'intermediate_violations':int(violations),'wall_seconds':seconds(wall),'cpu_seconds':seconds(cpu)})
    return result,batches

history=read('historical-baselines.json')['swerv_wrapper']
h=history['report/baseline/run.json'];hm=history['report/baseline/metrics.json']
current=read('comparison-evidence/current-routing-evidence.json')
assert current['passed'] and current['returncode']==0
assert h['routing_binary_sha256']==current['binary_sha256']
hs,hb=log_stages(OUT/'comparison-evidence/historical-routing.log')
cs,cb=log_stages(OUT/'comparison-evidence/current-routing.log')
total_delta=current['seconds']-h['stages']['routing']['elapsed_s']
rows=[]
for k in hs:
    delta=cs[k]['wall_seconds']-hs[k]['wall_seconds']
    rows.append({'stage':k,'historical':hs[k],'current':cs[k],'wall_ratio':cs[k]['wall_seconds']/hs[k]['wall_seconds'],
                 'cpu_ratio':cs[k]['cpu_seconds']/hs[k]['cpu_seconds'],'extra_wall_seconds':delta,'share_of_total_extra_wall':delta/total_delta})
old=read('server-evidence/task.json');insertions={}
for name in ('fanout','cts','to_drv','to_hold'):
    r=old['results'][name];insertions[name]={'added_instances':r['transformation']['added_instances'],'native_seconds':r['seconds']}
    if 'native_optimization' in r:insertions[name]['metric_delta']=r['native_optimization']['passes'][0]['metric_delta']
resources=[]
for line in (OUT/'route-monitor.jsonl').read_text(encoding='utf-8').splitlines():
    v=json.loads(line)
    for sample in v.get('samples',[]):
        for p in sample['processes']:
            if p['name']=='ld-linux-x86-64':resources.append({'time':sample['time'],'rss_mib':p['rss_bytes']/1024**2,'cpu_seconds':p['cpu_seconds']})
perf=read('detailed-perf-inclusive.json')['report']
perf_rows=[]
for line in perf.splitlines():
    m=re.match(r'^\s*(\d+\.\d+)%\s+(\d+\.\d+)%\s+\[.\]\s+(.*)',line)
    if m and any(x in m[3] for x in ('prepareRVCluster(idrc::RVCluster&) -','routeSinglePath','expandSearching','malloc -')):
        perf_rows.append({'inclusive_percent':float(m[1]),'self_percent':float(m[2]),'symbol':m[3].strip()})
data={'scope':'Historical comparison with changed layout, netlist transformations, libraries and memory budget; not a controlled A/B',
 'same_router_binary':True,'router_sha256':current['binary_sha256'],
 'historical_route_seconds':h['stages']['routing']['elapsed_s'],'current_route_seconds':current['seconds'],
 'route_wall_ratio':current['seconds']/h['stages']['routing']['elapsed_s'],'extra_route_seconds':total_delta,
 'stages':rows,'detailed_router_batches':{'historical':hb,'current':cb},'insertions':insertions,
 'macro_coordinates':read('comparison-evidence/macro-coordinate-comparison.json'),
 'historical_routable_nets':7084,'current_routable_nets':8597,
 'historical_memory_limit_gib':h['memory_limit_gib'],'current_memory_limit_gib':8,
 'historical_peak_rss_mib':hm['routing']['peak_rss_mib'],
 'current_max_observed_rss_mib':max(x['rss_mib'] for x in resources),
 'memory_observation_scope':'Sampled resident memory only; not proof of address-space usage, no memory budget adjustment made',
 'detailed_router_perf':perf_rows,'perf_scope':'10-second sample, 802 samples, zero lost; inclusive percentages overlap and must not be added',
 'routing_producer_residual_drc':current['routing_gate']['residual_drc'],
 'historical_producer_residual_drc':hm['routing']['producer_residual_drc'],
 'historical_audit_residual_drc':hm['routing']['residual_drc'],
 'known_failed_route_seconds':[5400.541,10800.727],
 'all_three_route_seconds':5400.541+10800.727+current['seconds'],
 'not_proven':['Which individual upstream change caused how much slowdown','Exact worst topology net ID','Historical and current host CPU frequency/load equivalence','Effect of changing memory limits','A layout-quality improvement from any proposed future action']}
(OUT/'runtime-analysis.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'route_wall_ratio':data['route_wall_ratio'],'extra_route_seconds':total_delta,'stages':rows,'max_observed_rss_mib':data['current_max_observed_rss_mib'],'all_three_route_hours':data['all_three_route_seconds']/3600},ensure_ascii=False))
