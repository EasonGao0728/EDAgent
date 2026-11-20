"""Publish an evidence-backed addendum; preserve previous reports/results."""
from pathlib import Path
import html,json,re
ROOT=Path(__file__).resolve().parents[1];P=ROOT/'runs/swerv-no-hold-20261115'
load=lambda p:json.loads(p.read_text(encoding='utf-8'))
a=load(P/'analysis.json');r=load(P/'evidence/io-receipt.json');audit=load(P/'audit-and-preservation.json')
assert a['metric_gate_passed'] and all(a['controls'].values()) and audit['parent_unchanged'] and not audit['active_owned_handles']
out=ROOT/'output/SWERV_case_report_20261115/SWERV_IO修复与无hold对照报告.html'
esc=lambda x:html.escape(str(x))
def link(p,label):return '<a href="'+esc(p.resolve().as_uri())+'">'+esc(label)+'</a>'
def table(head,rows):
    return '<div class="table-wrap"><table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'
hold=[]
for key,title in [('hold_00','不执行hold'),('hold_05','5%配额'),('hold_10','10%配额'),('hold_20','原20%配额')]:
    x=a['hold'][key];t=x['timing'];c=x['cost']
    hold.append([title,x['hold_buffers'],c['instances'],c['nets'],f'{c["standard_cell_area_um2"]:,.3f}',f'{t["min_worst_reported_slack_ns"]:.3f}',f'{t["min_tns_ns"]:.3f}'])
root=[]
for key,title in [('macro_imp','旧iMP'),('macro_shelf','旧shelf')]:
    x=a['original'][key]
    root.append([title,f'{x["native_dbu"]:,}',f'{x["counterfactual_io_minus_one"]["total_dbu"]:,}',f'{x["real_io"]["total_dbu"]:,}','精确一致'])
corrected=[]
for key,title in [('imp_fixed','修复后iMP，无hold'),('shelf_fixed','修复后shelf，无hold')]:
    x=a['corrected'][key];t=x['timing']
    corrected.append([title,f'{x["native_dbu"]/2000:,.4f}',f'{x["independent"]["total_dbu"]/2000:,.4f}',f'{x["final_hpwl"]["all_um"]:,.4f}',x['cost']['instances'],f'{t["max_worst_reported_slack_ns"]:.3f}',f'{t["min_worst_reported_slack_ns"]:.3f}',f'{t["min_tns_ns"]:.3f}'])
decision={'evidence_status':'completed','metric_consistency':'pass_exact_integer_dbu_both_corrected_arms',
    'hold_policy':'Do not globally disable hold; preserve functional registers. Compare timing benefit against standard-cell area/net growth and measured congestion. No automatic promotion from process exit success.',
    'hold_00':'reject as a universal replacement: original-layout diagnostic hold slack/TNS worsen; no-SPEF scope',
    'hold_10':'retain tradeoff candidate; 695 fewer buffers than 20%, same worst reported slack but TNS 0.914 ns worse; not timing clean',
    'macro_preference':'iMP wins placement HPWL by 16.273905718522546 percent in this corrected single trial; hold worst slack is worse, not a Pareto winner',
    'production_promoted':False,'routing_executed':False,'original_drc_unchanged':149846,
    'fix_scope':'Opt-in SWERV server experiment adapter for supported single-port rectangular IO, applied at every native reload; binary and production frozen task unchanged',
    'agent_integration':'Machine-readable audit/decision produced. Production agent loop has NOT acquired autonomous hold cost-benefit selection in this experiment.',
    'next_acceptance_requirements':['No metric conflict or physical semantics change','Explicit limits for area/net growth and acceptable timing tradeoff','Post-route extracted timing, DRC and congestion evidence before claiming physical quality improvement']}
(P/'decision.json').write_text(json.dumps(decision,ensure_ascii=False,indent=2),encoding='utf-8')
body=f'''<header><p class="eyebrow">aiEDA · SWERV / Nangate45 · 2026-11-15</p>
<h1>IO坐标修复与无hold宏布局对照</h1>
<p class="lead">HPWL冲突已定位并完成适配修复验证：两组新布局的原生值与独立DEF重算精确一致。无hold条件下，iMP的布局HPWL比shelf低16.27%，但两者仍有保持时间违例。</p>
<p>仅服务器预布线实验。原17阶段、最终DEF/GDS和149,846项DRC结果保留；未执行新布线，未推进Algorithm Agent，未自动替换生产结果。</p></header>
<section><h2>1. 新增的是缓冲器，不是寄存器</h2>
<p>对原20%方案与真正跳过hold的候选逐个统计单元类型，差异恰好是1,389个BUF_X4；没有新增寄存器。功能网表中的寄存器必须保留，不能因为后端面积或拥塞而擅自删除。后端hold缓冲器是否插入、插多少，需要时序需求和代价共同决定。</p>
<p>此前编排将hold阶段执行成功当作继续依据，没有充分审查面积、网络增长与边际时序收益。这是编排与质量反馈策略的责任；也不能在发现这一问题后直接把所有hold修复永久关闭。</p>
<p>无hold对照复用原iMP/CTS/DRV检查点，仅执行候选合法化与相同诊断STA。没有把配额设为0来冒充跳过：旧算法可能先插入一组再检查配额。候选中的to_hold.def只是依赖文件别名，凭据明确hold_executed=false。</p>
{table(['方案','新增hold缓冲器','实例数','网络数','标准单元面积 / µm²','hold最差slack / ns','hold TNS / ns'],hold)}
<p>所有分支setup最差slack为+0.777 ns，setup TNS为0。无hold相对原20%省2,586.318 µm²标准单元面积，但hold最差slack从−0.083降至−0.279 ns，TNS从−24.348恶化到−43.038 ns。面积是LEF单元占用之和，核心尺寸没有缩小，未测得拥塞改善。</p>
<p>边际收益明显递减：0→5%增加349个缓冲器，TNS改善15.175 ns；5→10%再加345个，改善2.601 ns；10→20%再加695个，改善仅0.914 ns，最差slack不变。10%可保留为折中候选，但所有分支仍有hold违例，尚不能判定任何一组为合格最终方案。以上是同口径、无提取SPEF的诊断结果，不是签核时序。</p></section>
<section><h2>2. HPWL冲突的根因与证据</h2>
<p><strong>主要原因是当前iEDA快照的iDB输入处理行为。</strong>DEF中显式+ PORT分支设置端口几何及placement，却遗漏IO引脚average_coordinate初始化；其默认值为(-1,-1)。iPL的IDBWrapper随后读取这个average_coordinate。旧的报告因此把大量边缘IO当作原点附近端点，导致线长与宏布局优劣判断失真。</p>
<p><strong>另有一个较小的口径差异：</strong>此前独立计算使用引脚矩形包围盒中心；原生iDB使用全部矩形角点坐标的整数平均值。现在同时保留旧口径记录，并新增与原生一致的矩形角点平均值口径；不把单元中心代理当作引脚HPWL。</p>
{table(['旧布局','原生HPWL / DBU','独立计算：IO=(-1,-1) / DBU','独立计算：真实IO / DBU','错误坐标复现'],root)}
<p>2000 DBU=1 µm。两套9,253网络设计均精确复现到整数DBU；不是抽样近似，也不是仅靠源码猜测。真实IO下旧iMP为456,560.5495 µm，旧shelf为402,955.9460 µm。旧包围盒中心口径分别为456,505.909和402,901.495 µm，口径差只有几十微米，不能解释原生相差几十万微米的问题。</p>
<p>源码证据位于本人授权目录的官方参考源码：def_read.cpp 1617–1670与1715–1733行、IdbPins.cpp 40–56行、IDBWrapper.cc 631–695行、lef_read.cpp 1029–1060及1119–1124行，已保存摘录和SHA。参考源码不代表当前快照二进制的完整源码可追溯关系；本次运行行为另由两组旧结果精确复现和两组修复后精确一致验证。不是LLM生成了错误HPWL，也没有证据称所有官方版本均存在此问题。</p></section>
<section><h2>3. 修复方式与边界</h2>
<p>新增def_io_compat.py适配层：对已审查的单PORT矩形IO，将显式PORT写法转换为等价的隐式写法，使现有读取器正确初始化坐标。1,416个IO的名字、位置、方向、层、形状和连接均保持。多PORT、POLYGON/VIA等未覆盖格式拒绝处理，不悄悄近似。</p>
<p>每次原生加载前重新适配，包括fanout和DRV配置中的内部DEF入口；导出后恢复规范写法并保留未转换副本，以兼容既有结构校验。原生读取回写试验已验证物理与逻辑语义不变。iEDA二进制没有修改，原生产后端与冻结任务未改；当前修复是服务器SWERV对照入口的显式适配，不冒称已全局修复所有工艺/阶段。</p>
<p>当前主布局二进制SHA为<code>d9ae28962bf622f1139e2b438c6f69deb646d93a48ece783da80a082d607694a</code>。输入端点错误会影响布局实际看到的目标，因此本轮重新执行的是独立候选的必要预布线阶段，而不是给旧报告简单换一个数字。</p></section>
<section><h2>4. 修复后，比较两种无hold宏策略</h2>
<p>研究任务<code>{r['job_id']}</code>完成，用时{a['seconds']:.1f}秒；其中15个优化/检查阶段原生累计{sum(x['seconds'] for x in r['stages']):.3f}秒，另有两次只读语义探针及适配、解析、校验开销。4 CPU、每进程8 GiB地址空间上限，研究总预算1800秒。没有运行routing。</p>
<p>iMP分支从已存floorplan开始；shelf采用历史三个宏坐标、当前方向和相同工艺库。两组fanout后的网络、非宏单元、IO及其余物理字段相同，布局配置与原生effective config哈希相同；都执行相同placement/CTS/DRV/合法化/STA并跳过hold。iMP重新输出的三个宏坐标与旧iMP相同，实际标准单元布局因正确IO端点而改变。CTS/DRV后的单元数量差异是布局影响的结果，线长主对比固定在它们之前。</p>
{table(['方案','布局原生HPWL / µm','布局DEF重算 / µm','合法化后HPWL / µm','最终实例数','setup最差slack / ns','hold最差slack / ns','hold TNS / ns'],corrected)}
<p><strong>结论：</strong>本次修复后单次试验支持iMP在线长上更好：布局HPWL低16.2739%；setup最差slack和hold TNS也较好，但hold最差slack比shelf差0.021 ns。两组几何检查通过、hold均不通过，iMP不是所有指标上的支配方案。</p>
<p>不能据此宣称iMP布线DRC更少或一定更快：本轮没有完整布线，没有测得路由拥塞、DRC或提取RC时序。旧149,846项DRC保持原结论，IO问题解释了HPWL冲突，但尚未证明它是全部DRC或路由耗时的原因。</p></section>
<section><h2>5. 编排策略应承担的门禁</h2>
<ol><li>先检查原生指标与同口径独立重算是否一致；冲突时停止布局优劣判断。</li>
<li>保留无hold基线，报告每档候选的slack、TNS、面积、网络增长和边际收益；拥塞没有测量就标为未知。</li>
<li>时序仍失败，或改善需要超过已约定的面积/网络代价时，保留分支供审查，不因程序退出0自动接受。</li>
<li>真实质量接受须采用事前约定的时序、DRC、资源预算；当前研究不启动昂贵布线、不覆盖生产结果。</li></ol>
<p>本轮已产出机器可读的一致性门禁、控制条件、成本和接受/回退决定；这是受控研究执行与审查，不声称生产主Agent loop已自动完成成本收益选择。自动策略的后续接入应沿用这些证据与门禁，不能把“默认20%”或“永久不做hold”当作答案。</p></section>
<section><h2>6. 保全、失败记录与交付</h2>
<p>31项冻结输入/原任务/原最终产物哈希全部一致，研究无遗留活动native handle。54份结果证据共18,091,484字节逐项验证SHA；本轮服务器研究及失败探针共{audit['study_storage_bytes']/1024**2:.1f} MiB，未复制完整布线目录或工艺库。34项相关测试通过。</p>
<p>失败探针全部保留：v1受控进程名含下划线而在iEDA启动前被拒；v2对未布线快照调用report_route在加载后崩溃，没有有效报告。v3改为已验证的只读export_def语义检查，再以实际新placement报告验证指标。未放宽资源限制或隐去失败。</p>
<ul><li>{link(P/'analysis.json','完整数值与控制变量')} · {link(P/'decision.json','接受/回退与修复适用范围')}</li>
<li>{link(P/'source-evidence.json','源码摘录与SHA')} · {link(P/'audit-and-preservation.json','原结果保全与失败探针')}</li>
<li>{link(P/'evidence/manifest.json','54份证据清单')} · {link(P/'evidence/io-receipt.json','服务器作业凭据')}</li>
<li>{link(ROOT/'runs/medium-macro-fullflow-20261114/研发记录.md','研发记录')} · {link(out.parent/'SWERV受控优化筛选报告.html','此前筛选报告（历史原件保留）')}</li></ul></section>'''
old=(out.parent/'SWERV案例测试与耗时分析报告.html').read_text(encoding='utf-8')
style=re.search(r'<style>(.*?)</style>',old,re.S)[1]
out.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SWERV IO修复与无hold对照报告</title><style>'+style+'</style><body><main>'+body+'</main></body></html>',encoding='utf-8')
print(str(out))
