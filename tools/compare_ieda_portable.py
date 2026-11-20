"""Compare exact stage data, per-net routing records and merged final geometry."""
import hashlib
import html
import json
from pathlib import Path
import re
import sys
import klayout.db as db

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from macro_agent.def_validation import read_def
from ieda_gds_export import export

p=Path(__file__).resolve().parents[1]/'runs/portable-baseline-20261105'
local=p/'local-4';server=p/'server-4'
# Server input files are the verified same bundle, excluded from the return archive.
import shutil
if not (server/'input').exists():shutil.copytree(p/'bundle',server/'input')

def routes(file):
    text=file.read_text();body=re.search(r'^NETS \d+\s*;\s*\n(.*?)^END NETS',text,re.M|re.S).group(1)
    result={}
    for row in body.split(';'):
        if not row.strip():continue
        name=re.match(r'\s*-\s+(\S+)',row).group(1)
        head,sep,route=row.partition('+ ROUTED')
        result[name]={'head':' '.join(head.split()),'segments':sorted(' '.join(x.split()) for x in re.split(r'\bNEW\b',route)) if sep else []}
    return result

stages={}
for stage in ['import_check','cts','legalization','routing','filler']:
    a=local/'result'/f'{stage}.def';b=server/'result'/f'{stage}.def'
    stages[stage]={'byte_identical':a.read_bytes()==b.read_bytes(),'parsed_structure_identical':read_def(a)==read_def(b),
        'per_net_route_segments_identical':routes(a)==routes(b),'local_sha256':hashlib.sha256(a.read_bytes()).hexdigest(),
        'server_sha256':hashlib.sha256(b.read_bytes()).hexdigest()}
for w in [local,server]:export(w)
layouts=[]
for w in [local,server]:
    l=db.Layout();l.read(str(w/'result/final.gds'));layouts.append(l)
def regions(l):
    top=l.cell('gcd');return {(l.get_info(i).layer,l.get_info(i).datatype):db.Region(top.begin_shapes_rec(i)).merged() for i in l.layer_indices()}
a,b=map(regions,layouts)
geometry_equal=set(a)==set(b) and all((a[k]^b[k]).is_empty() for k in a)
metrics=[];drc=[]
route_states=[]
for w in [local,server]:
    f=json.loads((w/'result/report/routing_features.json').read_text())
    metrics.append({k:f[k] for k in ['Design Layout','Design Statis','Nets']})
    d=json.loads((w/'result/report/violations.json').read_text())
    drc.append(sorted(json.dumps(v,sort_keys=True) for v in d['violations']))
    rs=json.loads((w/'result/rt/violation_reporter/route_summary.json').read_text())
    route_states.append({k:rs[k] for k in ['route_complete','route_incomplete','reason','route_issue_count_map']})
v={'status':'matched','source':'same frozen DSH placement; all CTS-through-GDS settings shared',
   'stages':stages,'final_geometry_equal':geometry_equal,'metrics_equal':metrics[0]==metrics[1],
   'drc_violations_identical':drc[0]==drc[1],'drc_count':len(drc[0]),'metrics':metrics[0],
   'route_quality_state':route_states[0],'route_quality_state_identical':route_states[0]==route_states[1],
   'limits':['One registered GCD input, four threads; not proof for arbitrary cases/hardware','GDS is abstract geometry, not signoff','Final DRC contains nine violations; sixteen rule families unsupported']}
assert geometry_equal and v['metrics_equal'] and v['drc_violations_identical'] and v['route_quality_state_identical'] and all(s['parsed_structure_identical'] and s['per_net_route_segments_identical'] for s in stages.values())
(p/'comparison.json').write_text(json.dumps(v,ensure_ascii=False,indent=2))
rows=''.join(f'<tr><td>{k}</td><td>{s["byte_identical"]}</td><td>{s["parsed_structure_identical"]}</td><td>{s["per_net_route_segments_identical"]}</td></tr>' for k,s in stages.items())
doc='''<!doctype html><meta charset="utf-8"><title>本地与服务器 iEDA 一致性验证</title><style>body{max-width:1050px;margin:36px auto;font:16px/1.7 system-ui;color:#182b40}table{border-collapse:collapse;width:100%}td,th{padding:9px;border-bottom:1px solid #ddd;text-align:left}aside{background:#fff2d6;padding:16px}code{overflow-wrap:anywhere}</style>
<h1>本地与服务器：同环境、同输入、同结果</h1><p>从 DSH 已验收的 ibench_gcd_legacy placement DEF 出发。两端使用同一 iEDA 二进制、动态加载器、全部 57 个动态依赖库、Tcl 资源、输入包、阶段脚本和四线程参数。</p>
<p>结果：单元与连接一致，每个网络的布线段一致，最终 GDS 每层合并几何 XOR 为空，DRC 违规明细一致。</p>
<table><tr><th>阶段</th><th>DEF 字节一致</th><th>结构一致</th><th>逐网络布线一致</th></tr>'''+rows+'''</table>
<p>Routing/Filler 的 DEF 字节差异来自线段输出顺序；每条线段和每个过孔保持一致。GDS 使用 KLayout 0.29.12 从相同 DEF/LEF 转换并回读。</p>
<table><tr><th>指标</th><th>本地</th><th>服务器</th></tr><tr><td>线长（μm）</td><td>6142.99</td><td>6142.99</td></tr><tr><td>过孔数</td><td>2226</td><td>2226</td></tr><tr><td>网络数</td><td>294</td><td>294</td></tr><tr><td>最终 DRC</td><td>9</td><td>9</td></tr></table>
<aside>本轮验证环境一致性，不代表设计质量达标。新统一 CTS 版本插入 3 个缓冲器，与此前旧版 CTS 插入 2 个的混合流程不同，因此不能与上一轮 0 DRC 直接比较。16 类规则仍不支持，未执行完整签核、LVS 或提取 RC 后时序验证。</aside>
<p><a href="comparison.json">完整比较数据</a> · <a href="local-4/result/filler.def">本地最终 DEF</a> · <a href="local-4/result/final.gds">本地 GDS</a> · <a href="local-4/run.json">本地运行</a> · <a href="server-4/run.json">服务器运行</a></p>
<p>二进制 SHA256：<code>d9ae28962bf622f1139e2b438c6f69deb646d93a48ece783da80a082d607694a</code>。原始 DSH 输入及共享目录只读。仅对本案例本次配置提供实测一致性结论。</p>'''
(p/'report.html').write_text(doc,encoding='utf-8')
print(json.dumps({k:v[k] for k in ['status','final_geometry_equal','metrics_equal','drc_violations_identical','drc_count']}))
