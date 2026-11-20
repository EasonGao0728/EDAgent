"""Generate a follow-up report without modifying the original case delivery."""
from pathlib import Path
import html,json,re
ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'runs/swerv-screening-20261115-v2'
load=lambda p:json.loads(p.read_text(encoding='utf-8'))
a=load(P/'analysis.json');r=load(P/'evidence/receipt.json');c=load(P/'comparison-controls.json');audit=load(P/'audit-and-preservation.json')
assert a['status']=='completed' and audit['parent_unchanged'] and not audit['active_owned_handles']
out=ROOT/'output/SWERV_case_report_20261115/SWERV受控优化筛选报告.html'
esc=lambda x:html.escape(str(x))
def link(path,label):return '<a href="'+esc(path.resolve().as_uri())+'">'+esc(label)+'</a>'
def table(headers,rows):
    return '<div class="table-wrap"><table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'
hold=[]
for key in ('hold_05','hold_10','hold_20'):
    x=a['hold'][key];t=x['fresh_sta']
    hold.append([f'{x["cap"]:.0%}',x['inserted_buffers'],x['instances'],x['nets'],f'{t["min_worst_reported_slack_ns"]:.3f}',f'{t["min_tns_ns"]:.3f}',f'{t["max_worst_reported_slack_ns"]:.3f}','通过'])
macro=[]
for key,label in [('macro_imp','当前 iMP（复用）'),('macro_shelf','历史 shelf 坐标候选')]:
    x=a['macro'][key];macro.append([label,f'{x["native_hpwl_um"]:,.3f}',f'{x["independent_pin_bbox_hpwl"]["all_um"]:,.3f}',f'{x["center_hpwl_um"]:,.3f}','通过'])
decision={'scope':'Pre-route research screening; no production task mutation','hold_05':'not promoted: lower buffer cost but worse hold slack/TNS','hold_10':'retain as experimental tradeoff, not promoted: 695 fewer buffers but diagnostic TNS worsens 0.914 ns','macro_shelf':'not promoted: exported-DEF proxy improves but native placement HPWL disagrees; native reread report unavailable','routing':'not submitted; no DRC improvement or runtime speedup claimed','parent_final_def_unchanged':audit['parent_unchanged'],'algorithm_agent_started':False}
(P/'decision.json').write_text(json.dumps(decision,ensure_ascii=False,indent=2),encoding='utf-8')
body=f'''<header><p class="eyebrow">aiEDA · SWERV / Nangate45 · 2026-11-15</p>
<h1>缓冲器与宏布局：受控优化筛选</h1>
<p class="lead">完成一次服务器预布线对照。10% hold 配额值得继续研究，但尚无候选满足无退化替换条件；宏布局线长报告存在未解决的一致性问题。</p>
<p>原任务、已验收17阶段、最终DEF/GDS均保留。原版图149,846项独立DRC未被本次实验改变。没有启动新布线，没有推进Algorithm Agent。</p></header>
<section><h2>1. 实验边界与控制变量</h2>
<p>固定案例swerv_wrapper，6,777个初始标准单元与3个研究SRAM宏。原生产任务为<code>{r['parent_task']}</code>。研究任务<code>{r['job_id']}</code>用时{a['study_seconds']:.1f}秒，共9次原生阶段调用；保留的基线不重复布局布线。原生计算全部在服务器，4 CPU、每进程8 GiB地址空间上限，单阶段最多600秒、研究最多3600秒。</p>
<p>hold从同一to_drv DEF出发，仅改变max_insert_instance_percent（5%、10%、原20%）；LEF、Liberty、SDC、工具二进制、BUF_X4选择均不变。三组原生优化前canonical hash一致。原20%分支复用合法化DEF，只追加相同诊断STA。</p>
<p>宏对照只改变3个宏的坐标，保持当前方向与库，用同一配置重新完成候选必需的fanout和placement；检查点位于CTS/hold之前。两组fanout后的网表连接、非宏单元、IO、物理约束一致，布局配置SHA完全相同。历史坐标不是历史流程复现，不能消除旧历史库、二进制与资源条件的差异。</p>
<p>服务器study目录共{audit['study_storage_bytes']/1024**2:.1f} MiB（含失败探针与证据）；未复制工艺库或巨型布线目录。收集31份文件逐一核验SHA。</p></section>
<section><h2>2. hold：20%配额不是必要性的证明</h2>
<p>原日志明确出现“Reach the maximum number of buffers that can be inserted”。官方参考源码按实例数量乘比例计算阈值，并在一组插入后检查严格大于阈值，允许实际数量小幅超过设定比例。本次20%产生1,389个、10%产生694个、5%产生349个；未改变hold目标0 ns。参考源码与当前快照二进制的完整对应关系尚未证明。</p>
{table(['配额','新增hold缓冲器','合法化实例数','网络数','诊断hold最差slack / ns','诊断hold TNS / ns','诊断setup最差slack / ns','几何合法性'],hold)}
<p><strong>10%相对20%：</strong>少695个缓冲器（减少50.04%），全体实例少8.35%，网络少6.50%。最差hold slack相同，但hold TNS从−24.348变为−25.262 ns，恶化0.914 ns。不能称为全面优于原方案。5%进一步减少缓冲器，却把最差hold slack降至−0.108 ns，因此不自动采用。</p>
<p>表中三组来自同一fresh STA路径、同一SDC和库，均无提取SPEF，报告精度0.001 ns；不是布线后寄生时序签核。iTO内部pass指标另存：20%/10% hold WNS均为−0.092152 ns，TNS分别−34.504782/−35.563288 ns；这些内部图采样与fresh STA的统计口径不同，不能混列比较。插入后图样本数变化，也不能把样本违例数当作固定端点集的修复率。</p>
<p><strong>决定：</strong>保留10%作为后续资源/时序折中候选；不修改默认20%配置，不覆盖原DEF。缺少RC时序、实际路由时间和DRC证据，不能宣称减半缓冲器必然带来更快、更干净的布线。</p></section>
<section><h2>3. 宏位置：先处理指标一致性</h2>
{table(['布局方案','原生iPL阶段HPWL / µm','导出DEF引脚包围盒中心HPWL / µm','单元中心HPWL / µm','几何合法性'],macro)}
<p>独立重算读取实际导出DEF与LEF，使用每个引脚矩形集合包围盒中心、实例方向变换和居中IO锚点。它与单元中心代理都提示shelf较短（引脚代理降低约11.74%），但原生阶段HPWL提示显著变差。剔除CLOCK与degree&gt;100网络后仍不一致，不能简单归因于中心近似或高扇出过滤。</p>
<p>两组库和配置一致，网表连接一致。当前尚不能确定是iPL内部拓扑/坐标更新、DEF导出同步还是其他统计口径导致；也没有证据把差异归咎于LLM。独立引脚包围盒中心是一种明确定义的检查口径，不等于真实访问点或布线总长度。</p>
<p>原生复核探针保留了全部失败记录：第一版缺少受控进程名称，在启动iEDA前被拒；第二版report_wirelength会进入路由评估初始化，并在8 GiB地址空间限制下出现std::bad_alloc，未产出有效报告；第三版init_pl → placer_report → destroy_pl正常退出、DEF语义不变，但没有生成报告。个人授权目录中的官方参考源码PlacerIO::reportPlacement()第247–258行仍为TODO，与观测相符；不能据此声称当前二进制所有实现都与该源码一致。</p>
<p>第三版最初用一个合并校验条件报“Audit did not preserve DEF”；后续逐项核对确认是<strong>报告缺失</strong>，DEF语义没有变化。已拆分错误类型，旧失败不删除。未扩大内存或重新执行布局来掩盖报告问题。</p>
<p><strong>决定：</strong>宏候选不升级为生产结果。先补足可靠的导出DEF线长评估与iPL报告一致性检查，再决定是否投入布线；本轮不根据相反的指标挑选“最优宏布局”。</p></section>
<section><h2>4. 对主Agent的意义与后续门禁</h2>
<p>这次是通过remote_client发起的固定研究对照，不宣称主Agent已自主发现并完成全部研究。生产Agent loop与生产工具配置未改；新增研究入口只能启动/查询这些固定实验，不能上传任意算法。</p>
<ol><li>感知：记录hold插入比例、网络膨胀、时序残差、指标一致性，不能只看工具返回成功。</li><li>筛选：先查合法性和比较控制条件，再评价成本与时序；指标相反时阻止自动推广。</li><li>验证：确认代理指标可信后，选一个候选做同口径完整路由与DRC；保留预算和失败记录。</li><li>接受或回退：按事前约定的时序、DRC、运行成本条件判断。本轮没有达到生产替换条件，原结果保持。</li></ol>
<p>每个候选本轮仅运行一次，是可行性筛选，不能估计随机波动或推广到其他芯片。需要决定推广时，再做重复试验与其他案例验证。</p></section>
<section><h2>5. 证据与研发记录</h2><ul>
<li>{link(P/'analysis.json','结构化对照结果')} · {link(P/'comparison-controls.json','控制变量核验')} · {link(P/'decision.json','接受/回退决定')}</li>
<li>{link(P/'evidence/manifest.json','31份证据文件与SHA清单')} · {link(P/'evidence/receipt.json','服务器研究凭据')}</li>
<li>{link(P/'audit-and-preservation.json','报告接口失败、参考源码与原结果保全核验')}</li>
<li>{link(ROOT/'runs/medium-macro-fullflow-20261114/研发记录.md','研发记录')} · {link(out.parent/'SWERV案例测试与耗时分析报告.html','原案例报告（未改动）')}</li></ul></section>'''
old=(out.parent/'SWERV案例测试与耗时分析报告.html').read_text(encoding='utf-8')
style=re.search(r'<style>(.*?)</style>',old,re.S)[1]
out.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SWERV受控优化筛选报告</title><style>'+style+'</style><body><main>'+body+'</main></body></html>',encoding='utf-8')
print(str(out))
