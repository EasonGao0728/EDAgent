"""Evidence-only pilot report; never invent a default for an infeasible case."""
from pathlib import Path
import json,html,hashlib

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'runs/hold-calibration-20261115'
OUT=ROOT/'output/hold-calibration-20261115'

def load(n):return json.loads((SRC/n).read_text(encoding='utf-8-sig'))
def esc(v):return html.escape(str(v))
def fmt(v):return '未测' if v is None else f'{v:,.6f}'.rstrip('0').rstrip('.') if isinstance(v,float) else esc(v)
def table(headers,rows):return '<table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(x)+'</td>' for x in r)+'</tr>' for r in rows)+'</tbody></table>'

def build():
    OUT.mkdir(parents=True,exist_ok=True)
    q=load('qualification.json');r=load('results.json');static=load('static-qualification.json')
    # Keep raw server evidence intact. This delivered interpretation never grants
    # routing permission from diagnostic metrics with unresolved model warnings.
    for c in r:
        if c.get('review'):
            v=c['review'];v['diagnostic_numeric_gate_passed']=v['passed'];v['passed']=False
            v['routing_allowed']=False;v['status']='measurement_model_review_required'
    catalog=json.loads((ROOT/'output/case-perception-20261115/case-catalog.json').read_text(encoding='utf-8'))['cases']
    features={}
    for x in q:
        key=('registered:' if x['case']=='swerv_nangate45' else 'shared:')+x['case']
        c=next(z for z in catalog if z['catalog_id']==key)
        features[x['case']]={k:c[k] for k in ('catalog_id','counts','standard_cell_instances','macro_instances','sequential','reference_geometry','tags','size_class')}
    universal=[]
    for label in ('skip','cap01','cap025','cap05','cap10','cap20'):
        measured=[(x,next((z for z in x.get('review',{}).get('candidates',[]) if z['label']==label),None)) for x in r if x.get('review')]
        eligible=[x['case'] for x,c in measured if c and c['eligible']]
        universal.append({'label':label,'eligible_cases':eligible,'evaluated_cases':[x['case'] for x,c in measured if c],
            'missing_cases':[x['case'] for x,c in measured if c is None]})
    best={x['case']:x.get('review',{}).get('selected') for x in r}
    analysis={'scope':'Nangate45 first-batch pre-route pilot; no production defaults changed','features':features,
        'qualification':q,'results':r,'fixed_cap_feasibility':universal,'selected_among_tested':best,
        'limitations':['RC cycle-edge pruning is unvalidated: no case is certified for production default calibration','No held-out validation; descriptive case groups are not learned rules','No extracted RC, routed congestion or DRC for these candidates',
            'SDC command and clock-name checks do not prove endpoint completeness','Public libraries differ from shared historical libraries',
            'One optimization realization per candidate; deterministic measurement repetition is not independent random-seed replication'],
        'production_modified':False,'full_routing_executed':False}
    (OUT/'experiment-results.json').write_text(json.dumps(analysis,ensure_ascii=False,indent=2),encoding='utf-8')
    chunks=['<h1>首批 8 案例 · Hold 预算对照</h1><p>基于固定 CTS／DRV 检查点，比较真正跳过 hold 与 1%、2.5%、5%、10%、20% 上限。先审查时序与结构，再比较面积、网络数和引脚 HPWL。</p>',
        '<p class="notice">这是统一 FLUTE 估计 RC 下的诊断实验。原生日志存在尚未独立验证的 RC 环路边剪除告警，因此下面的数值可行性不能升级为生产默认值或布线许可。原版图与生产默认值保留；本轮没有重新执行全局布局或完整布线，也没有候选 DRC／布线拥塞结论。</p>']
    chunks+=['<h2>资格与输入特征</h2>',table(['案例','输入标准单元／宏','时序单元占比','标签','资格／阻塞'],[
        [esc(x['case']),f"{features[x['case']]['standard_cell_instances']} / {features[x['case']]['macro_instances']}",
        fmt(100*features[x['case']]['sequential']['fraction_of_std'])+'%' if features[x['case']]['sequential']['fraction_of_std'] is not None else '未知',
        esc('、'.join(features[x['case']]['tags'])),esc(x['status'])+'<br>'+esc('; '.join(x['blockers']))] for x in q])]
    chunks+=['<h2>各档预算的诊断数值可行性</h2>',table(['预算','满足数值预筛的案例','已测／缺测'],[[esc(x['label']),esc('、'.join(x['eligible_cases'])) or '无',f"{len(x['evaluated_cases'])} / {len(x['missing_cases'])}"] for x in universal]),
        '<p>“满足门槛”要求估计 setup／hold slack ≥0、TNS=0、结构与合法性通过，标准单元面积和网络数相对 skip 增长均不超过20%。20%成本限额是既有工程政策，不是本轮学习出的最优值。HPWL参与成本比较；布线拥塞和DRC未测，不能填0。</p>']
    chunks+=['<h2>本批发现的阻塞问题</h2><ul><li>AES／tinyram：原生 hold 返回136（SIGFPE）。崩溃PC对应 optHoldViolationEnd 的整数取模；参考源码 batch_size=fanins.size()/10，候选不足10时会除零。现有二进制反汇编与故障地址相符。修复补丁草案已保存，但未替换实验冻结工具；不能把崩溃记作预算不足。</li><li>timer／SWERV：原生日志分别发现70／107个未获得时钟数据的端点。SWERV可追溯到 jtag_tck 及其派生支路；timer涉及组合逻辑驱动的时钟支路。需要明确时钟域与工作模式，不能自动编造周期或假路径。</li><li>s35932：无输入／输出延迟约束。bp_fe：缺少授权范围内的3组宏LEF/Liberty模型。</li><li>全部估计RC结果仍有模型验证边界；重复测量一致只证明可复现，不能证明绝对时序正确。</li></ul>']
    chunks+=['<h2>按类别能得出什么结论</h2>',table(['类别','本批证据','默认预算结论'],[
        ['小型无宏：GCD／timer','GCD六档均新增0个buffer，skip满足诊断数值门槛；timer有时钟覆盖缺口。','GCD可保留skip作为候选；不能推广为“小芯片一律不做hold”。'],
        ['中型无宏：AES／JPEG','AES的非零预算均触发工具除零；JPEG六档均不插入，独立setup与hold仍不满足。','无法从本批选出1%、5%等默认比例；先解决工具与测量问题，setup缺口也须单独处理。'],
        ['中型少宏：tinyram','2个宏；五档非零预算均触发原生hold除零。','暂不能标定；不能把失败归因于宏数量或配额太小。'],
        ['中型含宏／宏面积较大：SWERV、bp_fe','SWERV存在未约束的JTAG时钟支路，bp_fe宏模型缺失。','暂不纳入比例学习；旧SWERV 5/10/20%数据不能代替本次完整资格。']]),
        '<p>当前不支持统一数值，也不足以训练“规模→比例”或“宏数量→比例”的规则。更合理的待验证策略是：输入特征提供搜索先验，CTS／DRV后的setup／hold缺口、利用率和时钟覆盖决定是否启用与扩大预算。尚未执行大型案例、跨工艺和留出家族验证。</p>']
    for case in r:
        chunks.append('<h2>'+esc(case['case'])+'</h2>')
        review=case.get('review',{});selected=review.get('selected')
        chunks.append('<p>仅按当前诊断数值的候选：<b>'+esc(selected or '无可接受候选／尚不具备资格')+'</b>；'+esc(case['status'])+'。测量模型资格尚不满足生产标定要求。</p>')
        rows=[]
        details={x['label']:x for x in review.get('candidates',[])}
        for c in case['candidates']:
            if c['status']!='measured':
                rows.append([esc(c['label']),*['—']*7,esc(c.get('error','未完成'))]);continue
            v=details.get(c['label'],{});t=c['timing'];m=c['measurement']
            rows.append([esc(c['label']),fmt(v.get('added_buffers')),fmt(t['min_worst_slack_ns']),fmt(t['min_tns_ns']),fmt(t['max_worst_slack_ns']),
                fmt(m['standard_cell_area_um2']),fmt(m['hpwl_um']),fmt(m['nets']),esc(', '.join(v.get('rejection_reasons',[]))) or '通过本轮预筛'])
        chunks.append(table(['预算档','新增buffer','hold slack ns','hold TNS ns','setup slack ns','标准单元面积 µm²','引脚HPWL µm','网络数','结论'],rows))
        if case['blockers']:chunks.append('<p>'+esc('; '.join(case['blockers']))+'</p>')
    chunks+=['<h2>如何用于 Agent</h2><ol><li>先通过输入库、约束、检查点与测量资格检查。</li><li>在统一估计 RC 下测量 CTS／DRV 基线。基线满足时序时，保留 skip 作为零新增缓冲器候选。</li><li>有 hold 缺口时，从同一检查点按预算生成候选；测量真实新增数量、时序、面积和 HPWL，不能将上限当作必须插入的数量。</li><li>只在结构、合法性、时序和成本门槛均满足时接受；无可行候选则保留基线并报告原因，不能不断增加缓冲器冒充修复。</li></ol>',
        '<p>本批结果可用于决定下一步实验顺序，不能仅凭规模或宏数量确定通用比例。尚未完成跨家族留出验证，不能宣称分类策略已学会泛化。最终预算还需要候选布线拥塞、DRC与提取RC时序验证。</p>',
        '<h2>测量与证据</h2><p>时序：新进程读取同一库／SDC／合法化DEF，run_sta 初始化后 run_timing_eval FLUTE；独立比较估计RC结果，不与优化器内部或此前无SPEF诊断混用。SWERV已完成的5／10／20%优化与合法化产物按哈希复用，仅补测新口径。检查点重建只覆盖用户授权且具备资格的案例。</p>',
        '<p>完整结构化结果、来源SHA、日志路径、预算与复用记录：<a href="experiment-results.json">experiment-results.json</a>。源实验保存在个人服务器 runs/hold-calibration-20261115-v1；本地证据在 runs/hold-calibration-20261115。</p>']
    doc='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>首批8案例 Hold预算对照</title><style>body{font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif;color:#172b45;max-width:1400px;margin:40px auto;padding:0 24px}h1{font-size:32px}h2{margin-top:36px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid #d7e0e9;padding:10px;text-align:left;vertical-align:top}th{background:#edf4fa}td{overflow-wrap:anywhere}.notice{padding:16px;background:#fff5df;border-left:4px solid #c68724}a{color:#175fab}</style>'+''.join(chunks)+'</html>'
    p=OUT/'首批8案例_hold预算对照报告.html';p.write_text(doc,encoding='utf-8');print(p)

if __name__=='__main__':build()
