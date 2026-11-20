"""Package and verify the measured DSH continuation artifacts."""
from pathlib import Path
import hashlib
import html
import json
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from macro_agent.def_validation import read_def

p=Path(__file__).resolve().parents[1]/'runs/dsh-gcd-fullflow-20261105-01'
remote=p/'remote'; task=p.parent/'dsh-desktop-9b53815d1135a901/main-task'
state=json.loads((task/'task.json').read_text(encoding='utf-8'))
def sha(f):return hashlib.sha256(f.read_bytes()).hexdigest()
def save(f,v):f.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
source=read_def(p/'inputs/placement.def'); lg=read_def(p/'result/legalization.def')
route=read_def(remote/'result/routing.def'); final=read_def(remote/'result/filler.def')
added=set(lg['components'])-set(source['components'])
clock_sinks=set(source['nets']['clk'])-{('PIN','clk')}
actual_sinks=set()
for k,pins in lg['nets'].items():
    if k.startswith('clk_'):
        actual_sinks.update(pin for pin in pins if pin[0] not in added)
checks={
 'source_def_unchanged':sha(task/'final.def')==state['final_def']['sha256'],
 'placement_copy_identical':sha(p/'inputs/placement.def')==state['final_def']['sha256'],
 'frozen_source_inputs_unchanged':all(sha(Path(ref['path']))==ref['sha256'] for ref in state['input_refs']),
 'source_cells_and_masters_preserved':all(final['components'].get(k,{}).get('master')==v['master'] for k,v in source['components'].items()),
 'nonclock_net_endpoints_preserved':all(final['nets'].get(k)==v for k,v in source['nets'].items() if k!='clk'),
 'clock_leaf_endpoints_preserved':actual_sinks==clock_sinks,
 'clock_buffer_inputs_connected':set(lg['nets']['clk'])=={('PIN','clk')}|{(k,'A') for k in added},
 'clock_buffer_outputs_connected':all(sum((k,'X') in v for v in lg['nets'].values())==1 for k in added),
 'routing_preserved_component_locations':route['components']==lg['components'],
 'routing_preserved_net_endpoints':route['nets']==lg['nets'],
 'filler_preserved_existing_components':all(final['components'].get(k)==v for k,v in route['components'].items()),
 'filler_preserved_net_endpoints':final['nets']==route['nets'],
}
assert all(checks.values()), checks
for a,b in [('filler.def','final.def'),('filler.v','final.v'),('final.gds','final.gds')]:
    shutil.copy2(remote/'result'/a,p/b)
features=json.loads((remote/'result/report/routing_features.json').read_text())
drc=json.loads((remote/'result/report/drc_summary.json').read_text())
gds=json.loads((remote/'result/report/final_gds_validation.json').read_text())
route_summary=json.loads((remote/'result/rt/violation_reporter/route_summary.json').read_text())
assert route_summary['route_complete'] and gds['readback_passed']
native_attempt=json.loads((p/'run.json').read_text())
if not (p/'local-attempt.json').exists():save(p/'local-attempt.json',native_attempt)
native_attempt=json.loads((p/'local-attempt.json').read_text())
remote_attempt=json.loads((remote/'remote-run.json').read_text())
stages=[r for r in native_attempt['stages'] if r['stage'] in ['import_check','cts','legalization']]
for name in ['routing','filler','drc']:
    stages.append(next(r for r in reversed(remote_attempt['stages']) if r['stage']==name and r['completed']))
stages.append({'stage':'gds_conversion_and_readback','completed':True,'tool':'KLayout 0.29.12'})
v={'status':'completed_with_limitations','source_task':str(task),'source_def_sha256':state['final_def']['sha256'],
   'stages':stages,'checks':checks,'route_complete':True,
   'metrics':{'placement_instances':365,'post_cts_instances':367,'final_instances':616,'nets':293,
              'wirelength_um':features['Nets']['wire_len'],'via_count':features['Nets']['num_via'],
              'final_reported_drc':drc['violation_count'],'drc_status':drc['status'],
              'drc_checked_rule_families':len(drc['checked']),'drc_unsupported_rule_families':len(drc['unsupported'])},
   'moved_original_cells':[{'instance':k,'before':c['placement'],'after':final['components'][k]['placement']}
                          for k,c in source['components'].items() if c['placement']!=final['components'][k]['placement']],
   'gds':gds,'timing_signoff':None,'power_signoff':None,'manufacturing_signoff':False,
   'notes':['Original DSH placement was not rerun. CTS added two buffers; legalization moved one original cell by 1.38 um.',
            'Local pinned iEDA router aborted with grid index out of bounds despite exit code 0; remote iEDA completed the same design.',
            'Personal filler configuration adapted for remote iEDA: remove MP; add info_iter_num=10 and is_adaptive_bin=0.',
            'Native iEDA GDS failed top-cell/extent validation; final.gds was converted from final DEF and frozen LEFs using KLayout.',
            'Final DRC summary and violation list report zero. Internal minimum_area runtime counter is 3; this discrepancy remains uninvestigated.',
            'Checks cover parsed DEF endpoints, not extracted electrical connectivity, formal equivalence, LVS or full foundry signoff.'],
   'deliverables':{f:{'path':str(p/f),'sha256':sha(p/f)} for f in ['final.def','final.v','final.gds']}}
save(p/'run.json',v);save(p/'verification.json',checks)
rows=''.join(f'<tr><td>{html.escape(r["stage"])}</td><td>完成</td><td>{r.get("seconds","—")}</td></tr>' for r in stages)
metrics=''.join(f'<tr><td>{html.escape(k)}</td><td>{html.escape(str(x))}</td></tr>' for k,x in v['metrics'].items())
doc='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>DSH GCD 后续流程报告</title>
<style>body{max-width:1000px;margin:36px auto;padding:0 24px;font:16px/1.7 system-ui;color:#172331}table{border-collapse:collapse;width:100%;margin:16px 0}td,th{padding:8px 12px;border-bottom:1px solid #dce2e8;text-align:left}a{color:#065cb4}code{overflow-wrap:anywhere}aside{padding:16px;background:#fff4d8;border-radius:8px}</style>
<h1>从 DSH 布局继续完成物理设计流程</h1>
<p>输入为本地 DSH 最新验收的 ibench_gcd_legacy 布局，保持原网表、LEF、Liberty 和 SDC；没有重新执行 placement，也没有使用服务器 gcd_sky130_t 的布局。</p>
<p><a href="final.def">最终 DEF</a> · <a href="final.v">最终网表</a> · <a href="final.gds">可回读 GDS</a> · <a href="run.json">完整运行记录</a> · <a href="verification.json">检查结果</a></p>
<aside>物理流程已运行至 GDS。最终 DRC 报告为 0，状态 partial_clean：检查了 10 类规则，16 类不支持。没有完成完整工艺签核、LVS 和提取 RC 后的时序/功耗验证。</aside>
<h2>阶段结果</h2><table><tr><th>阶段</th><th>结果</th><th>秒</th></tr>'''+rows+'''</table>
<h2>测量结果</h2><table>'''+metrics+'''</table>
<h2>对原布局的影响</h2><p>CTS 插入 2 个 sky130_fd_sc_hd__buf_1 缓冲器。合法化将 dpath/b_reg/out_reg_10_ 的 x 从 20.70 μm 调整至 19.32 μm，y 保持 46.24 μm。其余原始单元位置保持一致。布线阶段保持合法化后的位置和网表端点，填充加入 249 个物理单元。</p>
<h2>运行环境和失败记录</h2><p>回读、CTS 和合法化使用本机原固定 iEDA Docker 镜像。其布线器出现 grid map index y -2147483648 越界，见 <a href="logs/routing.log">本地布线日志</a>；随后用个人服务器目录中的同一批输入和另一 iEDA 二进制完成布线、填充和 DRC。二进制哈希及各次尝试见 <a href="remote/remote-run.json">服务器运行记录</a>。原始 DSH 文件与共享目录均未修改。</p>
<h2>GDS 和检查边界</h2><p>iEDA 原生 GDS 导出返回成功，但回读缺少完整 gcd 顶层且尺寸不正确，原文件保留在 remote/result/final.gds2。交付的 final.gds 使用 KLayout 从最终 DEF 和原 LEF 转换；gcd 顶层、DBU 0.001 μm、67.16 × 81.60 μm 外框回读通过。标准单元使用 LEF 抽象几何，尚未合并晶体管级库 GDS，也未验证 foundry 图层映射。</p>
<p>最终 DRC 汇总与违规清单均为 0，但内部 minimum_area 运行计数为 3，存在尚未解释的统计差异；不能据此认定制造级 DRC clean。<a href="remote/result/report/drc_summary.json">填充后 DRC 汇总</a> · <a href="remote/result/report/violations.json">违规清单</a> · <a href="remote/result/rt/violation_reporter/route_summary.json">布线完成性与 DRC</a> · <a href="remote/result/report/final_gds_validation.json">GDS 回读</a></p>
<h2>输入追溯</h2><p>源任务：<code>'''+html.escape(str(task))+'''</code></p><p>源 DEF SHA256：<code>'''+state['final_def']['sha256']+'''</code></p><p>原始文件哈希、非时钟网络端点、时钟叶端点和阶段间实例保存检查全部通过。以上端点检查不代替布线几何导通性或形式等价验证。本次是已有 DSH 结果的独立后续运行，尚未把全流程入口接入 DSH Agent。</p></html>'''
(p/'report.html').write_text(doc,encoding='utf-8')
print(json.dumps({'status':v['status'],'metrics':v['metrics'],'checks_passed':all(checks.values()),'report':str(p/'report.html')},ensure_ascii=False))
