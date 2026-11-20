"""Derived report; the original campaign, receipts and failed attempts stay intact."""
from pathlib import Path
import json,html

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/hold-repair-20261116'
def esc(x):return html.escape(str(x))
def num(x):return f'{x:,.6f}'.rstrip('0').rstrip('.') if isinstance(x,(float,int)) else esc(x)
def table(head,rows):return '<table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table>'

def build():
    d=json.loads((ROOT/'runs/hold-repair-20261116/evidence.json').read_text(encoding='utf-8'))
    assert all(p['status']=='completed' for p in d['phases'].values())
    assert d['original_binary_unchanged'] and len(d['original_failures'])==10 and not d['active_jobs']
    merged=[]
    for name in ('gcd','aes','jpeg','tinyram'):
        case=next(x for x in (d['resumed'] if name in ('aes','tinyram') else d['original_sweep']) if x['case']==name)
        assert len(case['candidates'])==6 and all(x['status']=='measured' for x in case['candidates'])
        merged.append(case)
    result={'schema':'hold_guard_budget_comparison_v1','date':'2026-11-16','measurement_scope':d['qualification']['scope'],
        'qualification':d['qualification'],'cases':merged,'production_default_changed':False,'full_routing_executed':False,
        'all_eight_cases_qualified':False,'routing_allowed':False,
        'conclusion':'1% is the lowest tested nonzero cap sufficient for estimated hold repair in AES/tinyram; neither passes overall timing; no universal or category default calibrated',
        'limits':['No post-route extracted RC, congestion, DRC or power measurement','Reference is another build of iSTA, not independent timing-engine signoff','Summary agreement does not prove all individual path/RC values identical','No held-out case or sub-1% sweep; four of eight cases remain blocked'],
        'new_native_calls':len(d['stage_audit']),'old_failures_preserved':len(d['original_failures'])}
    OUT.mkdir(exist_ok=True)
    (OUT/'experiment-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    chunks=['<h1>Hold 除零修复与预算对照</h1><p>2026-11-16 · 服务器执行 · 首批 8 案例</p>',
        '<p class="note">除零补丁已在此前失败的 10 个分支通过。4 个可研究案例的六档数据现已齐全；另外 4 个仍受资格阻塞。AES 和 tinyram 的 hold 改善，但 setup 仍未通过，因此没有修改生产默认预算，也没有宣布版图质量通过。</p>',
        '<h2>修复范围与版本</h2><p>根因是进度打印取模使用 <code>batch_size = fanins.size()/10</code>；当候选数为 1–9 时除数为 0。隔离副本把该除数下限设为 1，原算法、目标 slack、预算与库不变。实际采用精确身份锁定的 10 字节兼容补丁，<b>不是官方新发布或重新编译版本</b>。同时保存源码修复副本。原快照及历史失败保持。</p>',
        table(['角色','SHA-256'],[['原快照',esc(d['tool_manifest']['base_sha256'])],['隔离 hold 补丁',esc(d['tool_manifest']['binary_sha256'])],['官方源码参考构建（commit 65c39fd28aa0dc0cdd56325df07f6e440069061b）','6e50227803fcf3162d64f6bfa739cf63521c72c63aa44b07d16121fbc25f36ea']]),
        '<p>真实机器指令边界测试覆盖候选数 0–10000，UBSan 测试通过；生产主 Agent 的默认二进制没有被静默替换。研究入口显式选择补丁，后续生产接入须建立新工具版本契约。</p>',
        '<h2>时钟资格</h2>',table(['案例','当前判断'],[['SWERV','107 个唯一端点无时钟数据；JTAG 周期／模式未知。用户确认无补充约束，保持阻塞。'],['timer','70 个唯一端点无时钟数据；组合派生时钟约束缺失，归档 RTL 为空，保持阻塞。'],['s35932','缺 IO 时序约束。'],['bp_fe','缺 3 组宏 LEF／Liberty 模型。'],['GCD、AES、JPEG、tinyram','检查到预期时钟组，日志未发现无时钟端点；允许本轮限定口径比较，不等于穷尽证明所有模式的约束完整。']]),
        '<h2>统一 RC 测量口径</h2><p>每次用新进程读同一冻结 DEF／LEF／Liberty／SDC，先 <code>run_sta</code> 建立时钟传播，再 <code>run_timing_eval FLUTE</code>。时序结果从后者输出读取，不能混入前者的初始数值。解析器新增脚本顺序核验；直接 FLUTE 的诊断结果另标，不用于预算选择。</p>',
        '<p>官方源码在 StaClockPropagation 中设置网络的 clock 标记；InitSTA 的 RC 构造会据此选择不同层参数。直接 FLUTE 的初始化只构建图，尚未执行该传播。这解释了初始化次序能够改变估计；它不意味着设计改变。</p>',
        table(['案例／候选','官方构建与快照的最大 WNS／TNS 差值（ns）','比较'],[[esc(x['case']+' / '+x['label']),f"{x['maximum_abs_delta_ns']:.3g}",'通过（容差 1e-9 ns）' if x['passed'] else '未通过'] for x in d['qualification']['comparisons']]),
        '<p>官方构建没有当前快照的 RC 剪边告警，六组汇总数值仍一致。反汇编显示快照会删除指向已访问节点的有向边，包含树的反向边；因此日志数量不能直接解释为同等数量的物理 RC 错误。现有证据支持本批同口径相对比较，未证明任意输入的每条 RC 支路或路径完全正确；也不是独立 STA 引擎／提取 RC 签核。</p>',
        '<h2>为什么 JPEG 加预算没有变化</h2><p>原 iTO 内部报告 hold WNS +0.020573 ns、TNS 0，因此插入 0 个缓冲器。统一评价器为 hold WNS −0.027887 ns、TNS −4.137387 ns。参考源码显示 iTO 与评价器使用不同的线层／时钟 RC 估计规则。增大上限无法让一个内部认为无违规的优化器开始修复；需要后续对齐优化与评价模型，不能继续机械增加配额。</p>',
        '<h2>预算结果</h2><p>skip 是完全跳过 hold；1／2.5／5／10／20% 是插入上限，不是强制插入数量。下表均为布线前估计。GCD、JPEG 复用上一批完成记录；AES、tinyram 使用新补丁完成原失败分支。每个非零档真实调用 hold；八个新分支输出与 1% 候选的 hold 输出逐字节一致，后续合法化／测量复用并记录来源。</p>']
    for c in merged:
        base=c['candidates'][0];rows=[]
        for x in c['candidates']:
            m=x['measurement'];b=base['measurement'];t=x['timing']
            rows.append([esc(x['label']),str(m['instances']-b['instances']),num((m['standard_cell_area_um2']/b['standard_cell_area_um2']-1)*100)+'%',num(m['hpwl_um']-b['hpwl_um']),num(t['min_worst_slack_ns']),num(t['min_tns_ns']),num(t['max_worst_slack_ns']),num(t['max_tns_ns'])])
        chunks+=['<h3>'+esc(c['case'])+'</h3>',table(['档位','新增 buffer','标准单元面积增长','HPWL 变化 µm','hold WNS ns','hold TNS ns','setup WNS ns','setup TNS ns'],rows)]
    chunks+=['<h2>本批能支持的决策</h2><ul><li>GCD：无需 hold 插入，保留 skip；不能外推所有小芯片都跳过。</li><li>AES：各非零档都只加 1 个 BUF_X4。hold 转正，面积约 +0.012672%，HPWL +5.306 µm，但 setup TNS 略恶化、setup 仍失败，因此成本收益审查拒绝晋升。</li><li>tinyram：各非零档都只加 6 个 BUF_X4。hold 转正，面积约 +0.295858%，HPWL +37.212 µm，setup 不变但仍失败，因此不能宣布整体通过。</li><li>JPEG：六档均不插入，评价器仍报 hold 与 setup 违规，优先处理优化／评价模型差异。</li></ul>',
        '<p><b>1% 只能称为 AES／tinyram 本轮已测档位中足够修复估计 hold 的最低非零上限，不能称为最优值、通用默认值或按类别学到的默认值。</b>没有测试更低比例，也没有留出案例。建议默认行为保持“先测缺口，无缺口跳过；有缺口先小预算试探；按 setup、hold、面积、HPWL 共同决定接受”。</p>',
        '<h2>执行与保留性</h2><p>本轮 23 次服务器原生调用：6 次 smoke（hold／合法化／测量）、1 次接口探查、2 次初始化顺序诊断、6 次官方构建测量、8 次失败分支修复续跑。不是 23 次全流程。4 CPU／8 GiB 地址空间限制保留；分支 600 秒、案例 3600 秒未放宽。10 份历史失败、6 个已存在的冻结检查点与原快照均保留；当前无本批后台作业。没有全局布局或完整布线重跑。</p>',
        '<p>23 项相关 Python 自动测试通过，另有服务器机器指令边界测试与实际原生回执。没有在本轮做工作台点击验收，不声称生产工具已全面替换。原 rc-direct 回执曾沿用通用方法标签；实际脚本没有 run_sta，本报告已明确纠正为“直接 FLUTE 诊断”，原始记录不覆盖。</p>',
        '<p><a href="experiment-results.json">结构化对照结果</a> · <a href="../../runs/hold-repair-20261116/evidence.json">原始证据与源码片段</a></p>']
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Hold 修复与预算对照</title><style>body{font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif;color:#203247;max-width:1280px;margin:36px auto;padding:0 24px}h1{font-size:32px}h2{margin-top:36px}table{border-collapse:collapse;width:100%;font-size:14px;margin:18px 0}td,th{border:1px solid #ccd5df;padding:9px;text-align:left;overflow-wrap:anywhere}th{background:#edf2f6}code{background:#eef2f5}.note{border-left:4px solid #9c6a1e;padding:16px;background:#fff6e8}a{color:#165da8}</style>'+''.join(chunks)+'</html>'
    dest=OUT/'hold修复与预算对照报告.html';dest.write_text(page,encoding='utf-8')
    assert page.count('<table>')==7 and len(merged)==4
    print(dest)

if __name__=='__main__':build()
