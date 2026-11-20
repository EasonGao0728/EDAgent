"""Self-contained presentation of the server inventory and proposed experiments."""
import json,html

def render_report(c,p):
    s=c['summary'];esc=html.escape
    options=lambda values:''.join('<option>'+esc(str(v))+'</option>' for v in values)
    selections=''.join('<tr>'+''.join('<td>'+esc(str(v))+'</td>' for v in [x['catalog_id'],x['role'],f"{x['instances']:,}",x['macros'],x['reason']])+'</tr>' for x in p['shortlist'])
    statrows=''.join('<tr><td>'+esc(k)+'</td><td>'+str(v)+'</td></tr>' for k,v in s['history'].items())
    payload=json.dumps(c['cases'],ensure_ascii=False).replace('<','\\u003c')
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>服务器案例感知报告 · hold 基准实验设计</title><style>
:root{--ink:#142b3e;--muted:#586b78;--line:#d6e0e4;--accent:#075f64;--paper:#fff;--back:#edf2f3}
*{box-sizing:border-box}body{margin:0;background:var(--back);color:var(--ink);font:16px/1.75 "Segoe UI","Microsoft YaHei",sans-serif}
main{max-width:1480px;margin:auto;padding:40px 36px 80px}header{padding:12px 0 28px;border-bottom:3px solid var(--accent)}.eyebrow{font:700 13px/1.6 monospace;color:var(--accent);letter-spacing:1px}h1{font-size:38px;line-height:1.3;margin:14px 0}h2{font-size:26px;margin:0 0 18px}h3{font-size:19px;margin:22px 0 8px}p{margin:10px 0}.lead{max-width:1100px;font-size:19px}.muted{color:var(--muted)}a{color:var(--accent)}nav{display:flex;gap:22px;flex-wrap:wrap;margin:20px 0}section{background:var(--paper);padding:28px;margin-top:24px;border:1px solid var(--line);border-radius:8px;scroll-margin-top:16px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:24px}.stat{background:#fff;padding:20px;border-top:3px solid var(--accent)}.stat strong{font-size:34px;display:block}.stat span{color:var(--muted)}.note{padding:14px 18px;background:#e8f3f2;border-left:4px solid var(--accent);margin:18px 0}.warn{background:#fff4e5;border-color:#a86017}.grid{display:grid;grid-template-columns:1fr 1fr;gap:24px}table{width:100%;border-collapse:collapse;font-size:14px}th{text-align:left;background:#eef4f4;color:#213b49}th,td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}tbody tr:hover{background:#f4f8f8}.scroll{overflow:auto}li{margin:7px 0}code{font:13px/1.5 Consolas,monospace;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6f7;padding:16px;font:13px/1.6 Consolas,monospace}.filters{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0}input,select{border:1px solid #b7c9cf;border-radius:5px;background:white;padding:10px;font:inherit}input{flex:1;min-width:230px}button{background:var(--accent);color:#fff;border:0;border-radius:4px;padding:7px 12px;cursor:pointer;font:inherit}button:hover{background:#09474b}button:focus-visible,input:focus,select:focus{outline:3px solid #d99b42;outline-offset:2px}.tag{display:inline-block;padding:2px 7px;margin:2px;background:#eaf1f4;border-radius:4px;font-size:12px}.detail td{background:#f7fafb;padding:20px}.hidden{display:none}.case-name{font-weight:650;word-break:break-all}#cases td:first-child{max-width:240px}.status{font:13px Consolas,monospace}.steps{counter-reset:step;list-style:none;padding:0}.steps li{padding:15px 0 15px 50px;position:relative;border-bottom:1px solid var(--line)}.steps li:before{counter-increment:step;content:counter(step);position:absolute;left:0;background:var(--accent);color:white;border-radius:50%;width:32px;height:32px;text-align:center;line-height:32px}.small{font-size:14px}footer{margin-top:28px;color:var(--muted)}@media(max-width:800px){main{padding:20px 14px}h1{font-size:28px}.stats{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}section{padding:18px}.filters>*{width:100%}th,td{padding:8px}}@media print{body{background:white}main{padding:0}.filters,button,nav{display:none}section{break-inside:avoid}#catalogue{break-before:page}.scroll{overflow:visible}.stats{grid-template-columns:repeat(4,1fr)}}
</style></head><body><main>
<header><div class="eyebrow">AIEDA · SERVER CASE INVENTORY · 2026-11-15</div><h1>先认识电路，再校准 hold 预算</h1>
<p class="lead">已统一盘点授权范围内的案例，建立可检索的特征目录。下一步用配对实验比较统一默认值、按规模默认值和按特征动态策略；本报告尚未给出经过多案例校准的最优比例。</p>
<p class="muted">本轮：只读扫描与实验设计 · 原结果保留 · 0 次原生 EDA 执行 · 不改变生产默认参数 · 不启动 Algorithm Agent</p></header>
<nav><a href="#findings">结论与边界</a><a href="#features">特征定义</a><a href="#catalogue">全部案例目录</a><a href="#selection">标杆候选</a><a href="#protocol">实验协议</a><a href="#policy">Agent 决策方式</a><a href="#evidence">来源与证据</a></nav>
<div class="stats"><div class="stat"><strong>278 + 7</strong><span>共享案例变体 + 已注册个人案例</span></div><div class="stat"><strong>41</strong><span>共享库含宏单元的变体</span></div><div class="stat"><strong>207 / 71</strong><span>结构重统计 / 哈希绑定历史统计</span></div><div class="stat"><strong>4</strong><span>工艺标签；不混为独立同质样本</span></div></div>
<section id="findings"><h2>这次盘点能回答什么</h2>
<div class="note"><b>你的思路可以做成可验证的策略。</b>输入感知先给出初始预算；CTS/DRV 后依据实际最短路径、时钟偏斜、hold 违例和 setup 余量修正预算。预算是上限，实际新增数量由工具在具体路径上决定。没有 hold 需求时，正确答案可以是零新增。</div>
<div class="grid"><div><h3>已查清的范围</h3><ul>
<li>共享库覆盖 Nangate45 75、Sky130 72、ICS55 66、ASAP7 65 个变体。全部278项与 MANIFEST 对齐。</li>
<li>共享网表完整哈希扫描约16.8 GB；服务器端读取后仅返回统计，无网表批量下载、无服务器新增文件。</li>
<li>小于等于25 MiB且支持的映射网表独立计数；大网表使用与当前网表SHA绑定的历史统计，明确区分证据。</li>
<li>另列7个主 Agent 已注册案例。SWERV共享版为5,989实例/3宏，个人注册版为6,780实例/3宏，不能按名字当作同一输入。</li></ul></div>
<div><h3>不能从目录直接推断的内容</h3><ul>
<li>输入规模和时钟周期不能直接决定 hold 数量。周期紧迫主要提示setup压力；hold还取决于最小路径延迟、时钟偏斜、角落和约束。</li>
<li>历史“完成布线”不等于时序、DRC或本轮流程验收通过；48项历史FAIL，16项明确未做CTS和DRC。</li>
<li>共享库部分工艺路径指向他人私有目录，本轮未访问。参考库可做单元分类，不证明与历史私有PDK或时序角落相同。</li>
<li>宏模型含fakeram研究抽象；功能等价、真实SRAM签核和新候选布线质量未验证。</li></ul></div></div>
<p>278个变体对应 <b>__UNIQUE__</b> 个不同网表SHA、<b>__LOGICAL__</b> 个声明的逻辑设计名。本报告进一步保守合并为 <b>__FAMILIES__</b> 个数据划分家族，避免同一电路的工艺/配置变体同时进入训练和留出集。家族归并是防泄漏分组，不是功能等价证明。</p>
<p>规模分布：<b>__SIZES__</b>。例如 openc910 的72,092,609个层次展开实例来自哈希绑定的历史统计，本轮没有独立展开或启动这个超大设计。</p>
</section>
<section id="features"><h2>统一感知字段与标签</h2><div class="scroll"><table><thead><tr><th>维度</th><th>本次获取的内容</th><th>用于后续决策的方式 / 限制</th></tr></thead><tbody>
<tr><td>规模</td><td>叶实例数、标准单元数、模块数、网表字节数</td><td>小型&lt;1k，中型1k–100k，大型100k–1M，超大型≥1M。分档是实验描述标签，不能直接映射为hold比例。</td></tr>
<tr><td>结构</td><td>宏数量/类型、输入输出位数、IO/实例比、时序单元数量与占比</td><td>FF/latch按Liberty识别，不把SRAM内部存储位当作标准单元寄存器；缺库时保留未知。功能类型来自名称/声明推断。</td></tr>
<tr><td>空间</td><td>声明core面积/利用率、参考LEF面积、宏占单元面积和core面积比例</td><td>同时看数量与面积：少量大宏也可能主导可用布局空间。这不是实测拥塞图。</td></tr>
<tr><td>约束</td><td>SDC时钟命令、简单常量周期、生成时钟声明、IO延迟/例外命令数量</td><td>不执行Tcl；数值保留SDC/库单位。跨工艺不默认都是ns。命令存在不代表约束覆盖正确。</td></tr>
<tr><td>可复现性</td><td>输入/SDC/清单SHA、历史结果、转换/模型声明、可读库路径</td><td>历史结果与本轮扫描分开；相同输入SHA仍需核对配置、库和检查点才可复用实验。</td></tr>
<tr><td>阶段反馈（未测）</td><td>hold/setup WNS、TNS、违例端点、偏斜、局部密度、拥塞、DRC</td><td>必须等真实阶段证据，不从名字或规模猜测。它们是动态扩档的主要依据。</td></tr>
</tbody></table></div><p class="small muted">共享库中__SEQ__项能用授权参考Liberty覆盖全部标准单元的FF/latch分类；__GEO__项能用参考LEF覆盖全部输入实例面积。其余字段显示“未知”，不填零。完整来源、模型限制和哈希可展开每个案例查看。</p></section>
<section id="catalogue"><h2>全部案例目录</h2><p>可组合搜索和过滤。数量为输入网表叶实例（包含宏），不是布局后插入CTS、DRV、hold与填充单元后的数量。</p>
<div class="filters"><input id="q" aria-label="搜索案例名称或标签" placeholder="搜索案例、功能、标签，例如 swerv / 含宏 / 高时序">
<select id="origin" aria-label="来源"><option value="">全部来源</option><option value="shared">共享库</option><option value="registered">主Agent已注册</option></select>
<select id="pdk" aria-label="工艺"><option value="">全部工艺</option>__PDKS__</select>
<select id="size" aria-label="规模"><option value="">全部规模</option>__SIZEOPTS__</select>
<select id="macro" aria-label="宏单元"><option value="">全部宏类别</option><option value="yes">含宏</option><option value="no">无宏</option></select></div>
<p id="count" role="status"></p><div class="scroll"><table id="cases"><thead><tr><th>案例 / 来源</th><th>工艺 / 规模</th><th>实例 / 宏</th><th>时序单元占比</th><th>宏面积占比</th><th>IO位数</th><th>标签 / 计数证据</th><th>证据</th></tr></thead><tbody id="body"></tbody></table></div>
<p class="small muted">宏面积占比=宏面积/全部输入实例面积；时序占比=FF或latch实例/标准单元实例。共享案例均为参考库匹配值，精确库的可复现性仍需资格验证。点击“展开”查看物理面积、静态周期、历史状态与输入SHA。</p></section>
<section id="selection"><h2>建议选取的标杆案例</h2><p>首批先固定Nangate45，减少工艺混杂：8个校准案例 × 6档，最多48个轻量候选分支；再按资格扩展2个大型校准和4个留出家族，最多84个分支。这里不包括资格验证、重复性实验和最终少量布线。现有SWERV结果只有精确检查点、工具及口径一致时才可抵扣。</p>
<div class="scroll"><table><thead><tr><th>案例</th><th>用途</th><th>输入实例</th><th>宏</th><th>选取理由与前置条件</th></tr></thead><tbody>__SELECTIONS__</tbody></table></div>
<div class="note warn">以上都是候选，不是已经具备多案例hold验收资格。toygpu历史仅PLACED，ariane133历史FAIL；资格不通过就记录限制，不为凑大型样本强行扩资源。beihai参考库分类未发现标准FF/latch，历史也无CTS，仅保留为边界对照。BlackParrot各变体不能同时充当独立训练和留出家族。首批宏家族有限，暂不声称未知宏架构上的泛化已验证。</div>
<p>第二批在可访问、已核对的Sky130库上做相同逻辑家族的工艺迁移检查；ICS55/ASAP7先补齐授权库、角落与工具适配。不是把278个案例全部跑一遍全流程。</p></section>
<section id="protocol"><h2>怎样探索一个可信的默认值</h2>
<ol class="steps"><li><b>先做资格验证。</b>核对网表/SDC/LEF/Liberty/二进制/配置SHA；检查时钟与端点覆盖、宏时序模型、IO适配和HPWL一致性。查明iTO内部时序与重载诊断时序差异后，冻结一种可解释口径；差异未解决的案例不进入数值校准。</li>
<li><b>冻结同一个CTS/DRV后检查点。</b>每个预算臂都从它分支，不能在前一档已插缓冲器的结果上累加。无需重跑已完成的上游阶段。新增不合格案例只跑必要资格阶段。</li>
<li><b>先粗扫6档。</b>真正跳过hold作为0新增对照，再试1%、2.5%、5%、10%、20%上限；0对照不能用“配额设0但仍调用hold”冒充。每档记录实际新增数量，核对工具上限计算分母及批量插入可能越界的行为。这里的百分比是iTO配置比例，不套用别的工具定义。</li>
<li><b>比较收益与代价。</b>记录hold最差slack/TNS/违例端点、setup余量、标准单元面积、独立引脚HPWL、网络数、合法性、连接性、运行时间和RSS。成本相对于同案例0新增基线归一化；TNS同时按端点数归一化，不能直接跨规模相加。新增缓冲器每100个的边际TNS收益只在同口径下比较。</li>
<li><b>按可行性与Pareto筛选。</b>先满足冻结的时序与合法性要求，再筛去在面积/HPWL/成本上被支配的候选。膝点附近可以细扫；不把未知拥塞/DRC当作改善，也不拿加权总分掩盖hold违例。当前20%成本预算是工程约束，不能在本轮改称实验结论。</li>
<li><b>比较4种策略。</b>A全局统一上限；B仅按规模分档；C加入时序占比、宏面积占比、IO比、工艺等输入特征；D输入先验+CTS/DRV后实际违例驱动扩档。样本小先用可解释规则，避免训练复杂模型。类别阈值须在校准集选择后冻结。</li>
<li><b>留出与重复验证。</b>按逻辑家族分组，留出UART、PPU、picorv32及一个合格大型家族。支持并确认随机种子控制时，对代表家族建立3个不同上游种子检查点，预算臂配对；若工具确定性运行，只把同输入复跑作为可复现性检查，不伪装成3个独立统计样本。</li>
<li><b>少量最终物理验证。</b>仅对已通过资格和预布线筛选的2–3组代表性Pareto候选与基线，在另行明确的时限下比较拥塞、布线DRC、提取RC时序。完整布线不是每一档的筛选步骤，HPWL变好也不能替代DRC验证。</li></ol>
<p><b>资源与停止条件：</b>工具仍在服务器执行，单个原生任务4核/8GiB、同一时刻1个任务；先用600秒/hold臂、3600秒/案例做预算试验。资格阶段另记时限，不自动扩时或改SDC；无可行解、超时、库不匹配都是结果。超大型先不计算。候选独立目录保留精简指标、必要检查点与失败日志，重复库引用原库，不能删除原验收成果。</p>
<p><b>如何判断新策略值得上线：</b>在未见过的家族上比较时序可行率、成本超限率、选择相对该案例最佳已测可行臂的代价差距（regret）、中位数/最差面积与HPWL增量、运行时间。必须报告超时与不支持案例的分母，不能只挑成功例。小样本先给逐案例结果与范围，不宣称统计显著。</p></section>
<section id="policy"><h2>最后应交给 Agent 什么</h2>
<p>建议输出一份<b>有适用范围的预算策略</b>，包含初始上限、扩档序列、最大成本、停止条件、证据来源、版本和置信度。用户明确时序优先、面积限制或拥塞风险时，改变可行候选之间的偏好与允许预算；若与硬约束冲突，则报告冲突，不悄悄放宽时序。</p>
<pre>输入感知 → 选择已验证的工艺/特征类别 → 给出初始尝试上限
    ↓
CTS/DRV 后检查点 → 实测 hold/setup、空间余量与风险
    ↓
0新增已满足要求：保持零新增
存在违例：在独立候选中按预算尝试 → 统一测量 → 成本/质量门禁
    ↓
合格且代价可接受：接受候选
收益继续明显、预算允许：扩档
收益饱和 / setup恶化 / 未解决违例：保留检查点，诊断或请求策略调整</pre>
<div class="note"><b>当前结论：尚无经过多案例校准的默认比例。</b>已有SWERV的5%→10%→20%实验提示边际收益递减，但四档都存在hold违例。5%只能作为待测试的起始档之一，不能包装为均衡最优值，更不能推导所有网表都适用。</div></section>
<section id="evidence"><h2>证据、原始数据与复现</h2>
<div class="grid"><div><h3>历史状态分布（非本轮验收）</h3><table><thead><tr><th>共享库标记</th><th>案例数</th></tr></thead><tbody>__STATUSROWS__</tbody></table></div><div><h3>可下载与复核</h3><ul>
<li><a href="case-catalog.json">完整特征目录 case-catalog.json</a>：全部285项、来源SHA、标签、未知项。</li>
<li><a href="hold-experiment-plan.json">结构化实验协议 hold-experiment-plan.json</a>。</li>
<li><a href="../../runs/case-perception-20261115/case-features-raw.jsonl">原始只读扫描JSONL</a>。</li>
<li><a href="../../runs/case-perception-20261115/registered-reference-correction.json">sky130_gcd引用根目录更正</a>：扫描器最初按manifest目录解析失败，依现有注册表改为个人目录third_party引用；原失败记录保留，未修改案例。</li>
<li><a href="../../runs/case-perception-20261115/library-reference-catalog.json">授权参考库分类与哈希</a>；<a href="../../runs/case-perception-20261115/constraint-profile.json">SDC静态常量补充</a>。</li></ul></div></div>
<h3>方法参考</h3><p>OpenROAD的<a href="https://github.com/The-OpenROAD-Project/OpenROAD/blob/master/src/rsz/README.md">Resizer官方文档</a>将缓冲器比例作为修复上限，并提供setup/hold修复控制；不能据此证明iEDA应采用相同比例。ORFS的<a href="https://openroad-flow-scripts.readthedocs.io/en/latest/user/InstructionsForAutoTuner.html">AutoTuner官方文档</a>展示参数扫描、逐试验指标与多目标偏好。这两项支持“受控搜索+逐试验评估”的方法；本报告的类别、预算档、留出与门禁设计属于本项目方案，不是文献已证明的最佳设置。</p>
<p class="small muted">授权范围：/srv/benchmarks/iBench/benchmarks/designs 与个人 main-agent-remote-v1/cases；参考库仅在这两棵授权目录下读取。未跟随共享pdk指向他人私有目录的链接。本报告的“全部”指这些已授权库中的清单，不宣称穷举服务器所有用户的文件。</p></section>
<footer>aiEDA · 输入感知与实验基线准备 · 报告可离线搜索，无外部脚本或网络依赖</footer>
</main><script type="application/json" id="data">__DATA__</script><script>
const rows=JSON.parse(document.getElementById('data').textContent);const $=id=>document.getElementById(id);
const e=s=>String(s??'未知').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=x=>x==null?'未知':Number(x).toLocaleString('en-US');const pct=x=>x==null?'未知':(x*100).toFixed(1)+'%';
const kinds={measured_structural_scan:'结构重统计',hash_bound_historical_statistics:'哈希绑定历史统计'};
function detail(r){const g=r.reference_geometry,s=r.sequential,cp=r.constraint_profile;return '<div class="grid"><div><b>几何与约束</b><p>标准单元 '+num(r.standard_cell_instances)+'；FF/latch '+num(s.count)+'；参考库分类覆盖 '+pct(s.coverage_fraction)+'</p><p>输入总面积 '+num(g.all_cell_area_um2)+' µm²；宏面积 '+num(g.macro_area_um2)+' µm²；core面积 '+num(g.core_area_um2_declared)+' µm²</p><p>参考利用率 '+pct(g.utilization_from_reference)+'；宏/core '+pct(g.macro_fraction_of_core)+'；IO/实例 '+(r.io_to_instance_ratio??0).toFixed(3)+'</p><p>静态周期（SDC/库单位）：'+e((cp.clocks||[]).map(x=>x.period_sdc_units??'未解析').join(', '))+'。未执行Tcl，未验证时序覆盖。</p><p>历史状态 '+e(r.historical_package?.result_status??'无共享包记录')+'；当前预算实验资格：待验证</p><p>分组家族 '+e(r.split_family)+'；相同网表SHA的目录 '+e(r.exact_netlist_duplicates.join(', '))+'</p></div><div><b>来源与证据边界</b><p>计数：'+e(r.counts_kind)+'；面积：'+e(g.kind)+'</p><p>网表路径<br><code>'+e(r.netlist.path)+'</code></p><p>SHA256<br><code>'+e(r.netlist.sha256)+'</code></p><p>SDC SHA256<br><code>'+e(cp.source?.sha256)+'</code></p><p>历史统计来源<br><code>'+e(r.historical_statistics?.source?.path??'未使用历史统计')+'</code></p></div></div><p><b>尚未获得：</b>实际hold/setup违例、短路径与偏斜、候选拥塞/DRC、校准后的最佳预算。历史FLOW状态不替代新验证。</p>'}
function render(){const q=$('q').value.trim().toLowerCase();const rs=rows.filter(r=>(!$('origin').value||r.origin===$('origin').value)&&(!$('pdk').value||r.pdk===$('pdk').value)&&(!$('size').value||r.size_class===$('size').value)&&(!$('macro').value||($('macro').value==='yes'?r.macro_instances>0:r.macro_instances===0))&&(!q||(r.catalog_id+' '+r.tags.join(' ')+' '+r.split_family).toLowerCase().includes(q)));$('count').textContent=`显示 ${rs.length} / ${rows.length} 项（共享278，注册7）`;
$('body').innerHTML=rs.map(r=>'<tr><td class="case-name">'+e(r.case_id)+'<br><span class="muted">'+(r.origin==='shared'?'共享库':'已注册')+'</span></td><td>'+e(r.pdk)+'<br>'+e(r.size_class)+'</td><td>'+num(r.counts.cell_count)+' / '+num(r.macro_instances)+'</td><td>'+pct(r.sequential.fraction_of_std)+'</td><td>'+pct(r.reference_geometry.macro_fraction_of_cell_area)+'</td><td>'+num(r.counts.top_pin_bits)+'</td><td>'+r.tags.slice(1).map(t=>'<span class="tag">'+e(t)+'</span>').join('')+'<br>'+e(kinds[r.counts_kind]??r.counts_kind)+'</td><td><button aria-expanded="false" data-id="'+e(r.catalog_id)+'">展开</button></td></tr>').join('');}
for(const id of ['q','origin','pdk','size','macro'])$(id).addEventListener('input',render);
$('body').addEventListener('click',ev=>{const b=ev.target.closest('button');if(!b)return;const tr=b.closest('tr');if(b.getAttribute('aria-expanded')==='true'){tr.nextElementSibling.remove();b.textContent='展开';b.setAttribute('aria-expanded','false');return;}const r=rows.find(x=>x.catalog_id===b.dataset.id);const d=document.createElement('tr');d.className='detail';d.innerHTML='<td colspan="8">'+detail(r)+'</td>';tr.after(d);b.textContent='收起';b.setAttribute('aria-expanded','true');});render();
</script></body></html>'''.replace('__UNIQUE__',str(s['unique_netlist_sha_shared'])).replace('__LOGICAL__',str(s['declared_logical_designs'])).replace('__FAMILIES__',str(s['conservative_split_families'])).replace('__SIZES__','；'.join(f'{k}：{v}' for k,v in sorted(s['size'].items()))).replace('__SEQ__',str(s['reference_seq_full_coverage'])).replace('__GEO__',str(s['reference_geometry_full_coverage'])).replace('__PDKS__',options(sorted(s['pdk']))).replace('__SIZEOPTS__',options(s['size'])).replace('__SELECTIONS__',selections).replace('__STATUSROWS__',statrows).replace('__DATA__',payload)
