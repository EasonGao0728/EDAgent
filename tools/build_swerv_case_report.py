"""Build a source-linked SWERV case report from completed, verified artifacts."""
from pathlib import Path
import datetime,html,json,shutil

ROOT=Path(__file__).resolve().parents[1]
E=ROOT/'runs/medium-macro-fullflow-20261114'
DELIVERY=ROOT/'runs/dsh-desktop-496d07b4ac6da42c/main-task'
OUT=ROOT/'output/SWERV_case_report_20261115'
load=lambda p:json.loads(p.read_text(encoding='utf-8'))
v=load(E/'delivery-verification.json');a=load(DELIVERY/'acceptance.json')
t=load(E/'final-evidence/task.json');r=load(E/'runtime-analysis.json')
assert v['passed'] and v['workflow_completed'] and t['status']=='target_met'
assert len(t['completed'])==17
OUT.mkdir(parents=True,exist_ok=True)
esc=lambda x:html.escape(str(x))
def duration(s):
    s=round(s);return f'{s//3600}小时{(s%3600)//60:02d}分{s%60:02d}秒' if s>=3600 else f'{s//60}分{s%60:02d}秒'
def table(headers,rows):
    return '<div class="table-wrap"><table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'
def link(path,label):return '<a href="'+esc(Path(path).resolve().as_uri())+'">'+esc(label)+'</a>'
labels={'TopologyGenerator':'拓扑生成 TG','LayerAssigner':'层分配 LA','SpaceRouter':'空间布线 SR','TrackAssigner':'轨道分配 TA','DetailedRouter':'详细布线 DR'}
timing_rows=[[labels[x['stage']],duration(x['historical']['wall_seconds']),duration(x['current']['wall_seconds']),f"{x['wall_ratio']:.2f} 倍",duration(x['extra_wall_seconds'])] for x in r['stages']]
timing_rows.append(['布线阶段总计',duration(r['historical_route_seconds']),duration(r['current_route_seconds']),f"{r['route_wall_ratio']:.2f} 倍",duration(r['extra_route_seconds'])])
cpu_rows=[[labels[x['stage']],duration(x['historical']['cpu_seconds']),duration(x['current']['cpu_seconds']),f"{x['cpu_ratio']:.2f} 倍",f"{x['historical']['average_cpu_cores']:.2f} → {x['current']['average_cpu_cores']:.2f}"] for x in r['stages'] if x['stage'] in ('TopologyGenerator','DetailedRouter')]
macro_rows=[]
for name,old in r['macro_coordinates']['historical']['macros'].items():
    now=r['macro_coordinates']['current']['macros'][name]
    macro_rows.append([name,now['master'],f"({old['placement'][1]/2000:g}, {old['placement'][2]/2000:g})",f"({now['placement'][1]/2000:g}, {now['placement'][2]/2000:g})"])
stage_rows=[[str(i+1),name,'阶段检查通过',duration(t['results'][name]['seconds']) if t['results'][name].get('seconds') is not None else 'Python 检查；无独立原生计时'] for i,name in enumerate(t['completed'])]
history=[*r['known_failed_route_seconds'],r['current_route_seconds']]
drc=a['drc'];quality='通过支持规则范围内的检查' if a['physical_quality_passed'] else '未通过：仍有残余 DRC'
ui_file=E/'workbench-card-verification.json'
ui=load(ui_file) if ui_file.exists() else {'visual_verified':False,'note':'尚未取得本次最终报告和版图卡片的真实界面核验证据。'}
preview=(DELIVERY/'placement.svg').read_text(encoding='utf-8')
shutil.copy2(DELIVERY/'placement.svg',OUT/'placement.svg')
shutil.copy2(E/'runtime-analysis.json',OUT/'runtime-analysis.json')
body=f'''
<header><p class="eyebrow">aiEDA · SWERV / Nangate45 · 2026-11-15</p>
<h1>含三个硬宏的后端流程测试报告</h1>
<p class="lead">同一持久任务完成登记的 17 个阶段。布线耗时 {duration(r['current_route_seconds'])}，是历史记录的 {r['route_wall_ratio']:.2f} 倍。流程执行与版图质量分别判定。</p></header>
<section><h2>1. 本次结果</h2>
{table(['项目','结论'],[['登记流程','17/17 阶段通过，工作台原任务 target_met'],['版图质量',quality],['最终独立 DRC',f"{drc['violation_count']:,} 项"],['初始输入','6,777 个标准单元（含791个tie cell）＋3个研究 SRAM 硬宏'],['最终 DEF',f"{v['final_instances']:,} 个实例，其中3个硬宏；其余包含物理填充单元"],['最终网表规模',f"{v['final_nets']:,} 个 net；{v['multiterminal_nets']:,} 个多端点 net"],['交付完整性','下载文件长度及 SHA256 全部匹配；三个硬宏身份与 FIXED 状态保持'],['原两小时目标','未通过。最终单次布线在另行批准的6小时上限内完成'],['制造签核','未完成；研究宏、抽象 GDS、未提取 RC 的诊断时序'],['工作台界面核验','已完成' if ui.get('visual_verified') else ui.get('note','待完成')]])}
<p>此处“流程通过”指本项目登记的检查链执行并如实交付；不等于 DRC clean、物理连通性签核、LVS 或可制造芯片。本次 DEF 额外检查了所有多端点网络存在 route records，未把该记录存在性检查冒称几何电气连通性验证。</p></section>
<section><h2>2. 时间到底花在哪里</h2>
{table(['布线子阶段','历史','本次','耗时倍数','增加时间'],timing_rows)}
<p>总增时 {duration(r['extra_route_seconds'])}。TG 增加65分33秒，DR增加61分07秒，两者解释约95.2%的增时；SR增加5分31秒。表内子阶段来自原生日志，布线总计来自宿主阶段凭据，二者范围不同，不要求子阶段之和等于总计。</p>
<h3>不仅是“等待变长”，CPU 计算量也增加</h3>
{table(['子阶段','历史 CPU 累计时间','本次 CPU 累计时间','CPU 时间倍数','CPU累计／墙钟时间'],cpu_rows)}
<p>TG平均利用约3.43核，历史约3.35核，因此TG变慢不能主要用“只分到更少CPU”解释。DR的CPU时间增至4.33倍，同时平均利用从2.10核降到1.76核，使墙钟时间增至5.14倍。CPU时间仍受机器频率等影响；没有历史同期主机负载数据，不能把这些比值等同于指令数。</p>
<h3>三次尝试和用户等待时间需要分开</h3>
{table(['尝试','布线实际耗时','结果'],[['第一次',duration(history[0]),'达到90分钟上限，退出124'],['第二次',duration(history[1]),'达到3小时上限，退出124；DR停在294/441之后'],['第三次',duration(history[2]),'在6小时上限内完成，退出0']])}
<p>三次原生布线累计 {duration(r['all_three_route_seconds'])}，其中失败尝试累计4小时30分01秒。前11个已完成阶段没有重跑。尚未完成的布线没有经过验证的内部恢复点，因此重试从合法化DEF重新启动布线；没有伪称从第295个分区续算。任务从首次建立到交付的日历时长还包含人工确认、关机、网络和认证恢复，不是单次iEDA运行时长。</p></section>
<section><h2>3. 已确认的具体差异</h2>
<h3>3.1 保持时间修复显著增加了待布线规模</h3>
{table(['步骤','新增缓冲器','阶段自身耗时'],[[k,x['added_instances'],duration(x['native_seconds'])] for k,x in r['insertions'].items()])}
<p>本次从6,780实例增长到布线前8,327实例，增加1,547个缓冲器；其中hold插入1,389个，占新增量89.8%。历史布线前后为6,814实例。本次多端点待布线网络8,597条，历史7,084条，增加21.36%。hold步骤自身只需约11秒，但它把后续路由问题变大了。<strong>这是已确认的规模来源，不是“hold导致全部增时”的单变量因果证明。</strong></p>
<p>该hold阶段凭据记录hold WNS改善约0.186458ns、hold TNS改善约8.532866ns，同时setup WNS下降约0.149657ns。它优化的是当前未提取RC的时序模型，不能只根据局部时序改善就认定对最终布线和PPA净有益。</p>
<h3>3.2 宏布局与库输入并非同一组条件</h3>
{table(['宏实例','master','历史坐标 µm','本次坐标 µm'],macro_rows)}
<p>历史使用固定shelf宏位置；本次由原生iMP决定宏位置后固定，改变了可布线通道、端点距离和障碍物相对关系。两者使用同一源结构网表与相同die/core边界，但前序流程、优化后的网表、宏位置以及8个LEF/Liberty文件哈希不同；只有tech LEF哈希一致。本次使用公开固定提交的库，未读取历史脚本提到的私有工艺目录。因此本报告属于历史对照，不能称为严格同输入A/B测试。</p>
<h3>3.3 热点已定位到两个计算环节</h3>
<ul><li><strong>TG：</strong>第二次尝试的两次10秒采样，约98.31%和99.38%的inclusive样本经过 <code>TGNode::getCost</code>，调用链包括 <code>updateTGCandidate</code>、map/set复制与内存分配。本次日志中最后597条网络占据TG约97%的时间，是明显的尾部计算热点；尚未确定具体最慢net ID。</li>
<li><strong>DR：</strong>本次10秒采样共802样本、0丢失，约53.74%的inclusive样本经过 <code>RuleValidator::prepareRVCluster</code>，约23.69%经过 <code>DetailedRouter::routeSinglePath</code>；可见几何对象复制、内存分配与路径搜索。不同调用链百分比有嵌套，不能相加，也不能当作整个75分钟DR的时间分解。</li></ul>
<p>本次DR分区过程的累计违规候选明显多于历史，伴随规则检查与路径搜索计算增多；这支持“当前布局/网表触发更重的路由工作负载”这一判断。没有做单变量分支实验，仍不能量化宏位置、hold缓冲器和库差异分别贡献多少增时。</p>
<h3>3.4 不能归结为本机配置或 LLM 计算慢</h3>
<p>真实iEDA始终在服务器执行；本机只负责模型编排和持久job_id查询。布线等待没有持续调用模型。SSH偶发超时只影响状态查询，原生进程未重启。布线完成后曾发生登录令牌校验错误，原有验证流程随后成功恢复，才继续后续阶段；这部分延迟不计入原生布线的189.4分钟。</p>
<p>历史内存预算32GiB，本次每进程地址空间上限8GiB；本次监测到的最大RSS约{r['current_max_observed_rss_mib']:.1f}MiB，历史峰值RSS约{r['historical_peak_rss_mib']:.1f}MiB。未见本次OOM终止，不能据此说8GiB就是根因；RSS不等于虚拟地址空间占用，也未验证扩大内存会加速。</p></section>
<section><h2>4. 质量结果与计数口径</h2>
{table(['口径','本次','历史'],[['DR分区过程累计候选',270621,32175],['路由器最终自身统计',r['routing_producer_residual_drc'],r['historical_producer_residual_drc']],['后续独立检查',drc['violation_count'],r['historical_audit_residual_drc']]])}
<p>三行来自不同阶段和检查范围，不能混用，也不能把候选去重后的下降都解释为修复成功。历史审计和本次后续DRC的输入/检查路径并非完全相同，表格不作为严格质量倍数的依据。本次仍有DRC，质量未通过；原生 <code>route_complete=false</code> 的原因由路由摘要说明为残余DRC，并非被隐去。</p>
<p>独立DRC自身另有190,147个过滤前、分区级候选，过滤去重后导出149,846个标记，与原生日志总数一致；这与上表路由器DR过程中270,621个候选是不同统计。计数来源与口径已核对，但尚未独立证明每条物理过滤规则的正确性。</p>
<p>独立DRC检查规则：{esc(', '.join(drc['checked']))}。未支持的规则：{esc(', '.join(drc['unsupported']))}。本次检查结论受此覆盖范围限制。</p></section>
<section><h2>最终诊断时序</h2>
<p>最终iSTA报告列出的max路径最小slack为0.777ns，max TNS为0；min路径最小slack为−0.083ns，min TNS为−24.348ns，仍有保持时间违例。这是无提取SPEF的诊断结果，不能视作布线寄生下的签核结论，也不能将报告中的估算频率当作芯片可达频率。</p>
<p>{link(E/'final-evidence/accepted-result-timing-swerv_wrapper.rpt','最终原生时序报告')} · {link(E/'final-evidence/accepted-timing-evidence.json','时序检查范围与阶段凭据')}</p></section>
<section><h2>交付过程中修复的校验器问题</h2>
<p>第一次GDS原生导出正常退出并生成文件，但独立检查器把2,094个“只有一个端点、DEF中没有路由”的网络误判为缺少导线。逐项核对后修正该语义：这类网络必须保留命名空引用；多端点网络、已有显式路由的单端点网络、实例和IO几何仍须通过原有检查。</p>
<p>17项回归测试通过；在原GDS上只读复核8,597个实际布线网络和456,769个路由坐标通过。保留原失败凭据与旧校验器，记录冻结输入指纹变更，仅重试未验收的GDS导出及后续回读，前15阶段未重跑。这是导出检查的误报修复，与前面189.4分钟的布线耗时无关。</p>
<p>服务器完成全部阶段后，模型决策预算已耗尽，原工作台未自动完成下载。新增宿主交付恢复路径：仅在任务已认证完成且原执行作业完成时，使用已有下载工具校验交付，不再调用模型或执行EDA。12项工作台测试通过；本次16个交付文件的长度与SHA256全部核验通过。预算和历史错误均保留。</p>
<p>{link(E/'gds-single-terminal-diagnosis.json','单端点逐项诊断')} · {link(E/'gds-checker-check.json','原产物只读复核')} · {link(E/'gds-checker-deploy.json','校验器部署与审计')}</p></section>
<section><h2>5. 后续应优先做什么</h2>
<ol><li><strong>先限制和评估hold插入代价。</strong>在原结果之外建立检查点分支，对照“原参数”与“限制新增缓冲器／调整时序约束的候选”，同时看hold、setup、单元数、估计拥塞及路由耗时。约束必须有电路依据，不能单纯放松到好看。</li>
<li><strong>隔离宏布局因素。</strong>固定库、前序策略、路由版本与预算，仅比较宏位置/通道策略；不要把改库、改宏位置和关掉优化同时混在一起。</li>
<li><strong>补充TG逐网络和DR逐分区可观测性。</strong>标出最慢net/box、端点数、空间范围和实际调用耗时；结合最终DRC热点决定局部候选，避免凭总DRC猜测根因。</li>
<li><strong>主Agent增加代价反馈。</strong>阶段结束不仅看执行成功，还应比较新增实例比例、时序收益、拥塞/连线估计与剩余预算；异常增长时先产出解释并选择分支验证。对已有能力以真实动作和证据为准，本报告不声称这些候选已实施或有效。</li></ol>
<p>本轮只完成既定流程、只读诊断和交付，没有启动上述新实验，没有提前推进Algorithm Agent。</p></section>
<section><h2>6. 已完成的阶段</h2>{table(['序号','阶段','结果','本次有效阶段原生耗时'],stage_rows)}</section>
<section><h2>7. 版图概览与交付</h2>
<p>下图来自最终DEF和LEF的实例矩形、宏与IO位置；是布局概览，不是逐线布线或DRC热点视图。</p><img class="layout" src="placement.svg" alt="最终DEF生成的三个硬宏与标准单元布局概览">
<p>{link(DELIVERY/'report.html','原生交付报告')} · {link(DELIVERY/'final.def','最终 DEF')} · {link(DELIVERY/'final.gds','抽象 GDS')} · {link(DELIVERY/'final.v','最终网表')} · {link(DELIVERY/'acceptance.json','验收数据')}</p>
</section><section><h2>8. 证据与可复核范围</h2>
<p>持久任务 <code>remote-ba81f7bdbfebcf944da30462</code>；本次路由作业 <code>job-f863e2f008543b31ebcfd294</code>。实际路由器SHA256：<code>{esc(r['router_sha256'])}</code>，与历史路由阶段一致；不能拿历史顶层默认二进制代替实际分阶段版本。</p>
<ul>{''.join('<li>'+link(p,label)+'</li>' for p,label in [(E/'runtime-analysis.json','机器可读耗时对照'),(E/'final-evidence/manifest.json','服务器最终证据清单与SHA256'),(E/'delivery-verification.json','下载与DEF独立检查'),(E/'comparison-evidence/historical-routing.log','历史原生日志'),(E/'comparison-evidence/current-routing.log','本次原生日志'),(E/'detailed-perf-inclusive.json','本次DR采样符号报告'),(E/'研发记录.md','完整研发记录'),(E/'workbench-card-verification.json','工作台卡片核验记录')])}</ul>
<p>报告生成：{datetime.datetime.now().astimezone().isoformat(timespec='seconds')}。结论基于保留的原始产物、阶段凭据及本地SHA核验；区分流程成功、质量失败和未完成的因果验证。</p></section>'''
css='''*{box-sizing:border-box}body{margin:0;background:#f4f6f8;color:#17283a;font:16px/1.8 "Microsoft YaHei",sans-serif}main{max-width:1120px;margin:auto;background:white;padding:48px 58px}header{border-bottom:3px solid #245d85;padding-bottom:24px}h1{font-size:32px;line-height:1.4;margin:10px 0}h2{font-size:24px;border-bottom:1px solid #d9e1e8;padding-bottom:8px;margin-top:40px}h3{font-size:19px;margin-top:25px}.eyebrow{color:#245d85;font-weight:700;letter-spacing:.04em}.lead{font-size:18px}table{border-collapse:collapse;width:100%;font-size:14px;margin:20px 0}th,td{text-align:left;padding:10px 12px;border:1px solid #d9e1e8;vertical-align:top}th{background:#edf3f7}tr:nth-child(even)td{background:#fafcfd}.table-wrap{overflow:auto}code{font-size:13px;overflow-wrap:anywhere}a{color:#175e9c}.layout{width:100%;max-height:800px;object-fit:contain;border:1px solid #d9e1e8}li{margin:9px 0}@media(max-width:700px){main{padding:20px}h1{font-size:26px}}@media print{body{background:white}main{padding:0}table{break-inside:auto}tr{break-inside:avoid}a{color:inherit}}'''
doc='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SWERV 含宏后端流程与耗时分析报告</title><style>'+css+'</style><main>'+body+'</main></html>'
(OUT/'SWERV案例测试与耗时分析报告.html').write_text(doc,encoding='utf-8')
print(json.dumps({'report':str(OUT/'SWERV案例测试与耗时分析报告.html'),'workflow_completed':True,'physical_quality_passed':a['physical_quality_passed'],'drc':drc['violation_count'],'visual_verified':ui.get('visual_verified',False)},ensure_ascii=False))
