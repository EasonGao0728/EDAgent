"""Collect actual 2026-11-06 commissioning evidence; never promote tool cards."""
import hashlib
import html
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from macro_agent.netlist_check import verify_import,liberty_bus_ports
from macro_agent.def_validation import read_def
from macro_agent.backend_checks import route_records
from macro_agent.main_task import verify_refs


def read(p):return json.loads(p.read_text(encoding='utf-8'))
def ref(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def segments(p):
    result={}
    for name,record in route_records(p).items():
        parts=re.split(r'(?:^|\+ )ROUTED ',record,maxsplit=1)
        if len(parts)!=2:raise ValueError('Unreviewed or unrouted net record')
        result[name]={'attributes':parts[0].strip(),
                      'segments':sorted(part.strip() for part in re.split(r'\bNEW\b',parts[1]))}
    return result


def main():
    out=ROOT/'runs/stage1-live-20261106';out.mkdir(exist_ok=True)
    trials=[];states=[]
    for number in ('04','05','06'):
        folder=ROOT/('runs/stage1-routed-baseline-20261106-'+number)
        state=read(folder/'task.json');states.append(state)
        if state['status']!='target_met' or state['pending']:raise ValueError('Trial not accepted: '+number)
        verify_refs(state['input_refs'])
        verify_refs(state['results']['routed_readback']['artifact_refs'])
        verify_refs([state['final_def']])
        metrics=read(folder/'metrics.json');accepted=Path(state['accepted_work'])
        route=read(accepted/'result/rt/violation_reporter/route_summary.json')
        trials.append({'trial':number,'task':ref(folder/'task.json'),'accepted':True,
            'final_def':state['final_def'],'report':ref(folder/'report.html'),'metrics':metrics,
            'routing':state['results']['routing']['routing_gate'],
            'drc':{k:v for k,v in state['results']['drc']['drc_gate'].items() if k!='runtime'},
            'native_drc_thread_count':state['results']['drc']['drc_gate']['runtime'].get('thread_count'),
            'route_dr_summary':route.get('dr_summary'),'route_summary':ref(accepted/'result/rt/violation_reporter/route_summary.json'),
            'readback_equal':state['results']['routed_readback']['readback_equal']})
    same_inputs=len({s['contract']['all_inputs_hash'] for s in states})==1
    if not same_inputs:raise ValueError('Trial contracts do not freeze identical inputs')
    defs=[Path(s['final_def']['path']) for s in states]
    repeat={'all_three_passed':True,'same_inputs_hash':same_inputs,
        'byte_identical':len({ref(p)['sha256'] for p in defs})==1,
        'parsed_placement_and_physical_semantics_identical':all(read_def(p)==read_def(defs[0]) for p in defs[1:]),
        'ordered_route_tokens_identical':all(route_records(p)==route_records(defs[0]) for p in defs[1:]),
        'per_net_route_segments_ignoring_record_order_identical':all(segments(p)==segments(defs[0]) for p in defs[1:]),
        'scope':'same local fixed HD subset only; not statistics, general determinism or complete A14'}
    macro=ROOT/'runs/stage1-native-macro-20261106-01'
    lib=ROOT/'third_party/ieda-reference/scripts/foundry/sky130/lib/sky130_sram_1rw1r_44x64_8_TT_1p8V_25C.lib'
    schema=liberty_bus_ports(lib)
    macro_input={'netlist':ref(macro/'gcd_sram.v'),'library':ref(lib),'bus_pin_schema':schema,
        'def':ref(macro/'result/iFP_result.def'),
        'check':verify_import(macro/'gcd_sram.v',macro/'result/iFP_result.def',schema),
        'placement_evidence':ref(ROOT/'runs/stage1-native-macro-verify-20261106-03/verification.json'),
        'production_registered':False,'dsh_accepted':False}
    if not macro_input['check']['passed']:raise ValueError('Macro input comparison failed')
    write(out/'macro-input-verification.json',macro_input)
    gaps=ROOT/'runs/stage1-backend-gaps-20261106-v2';gap_record=read(gaps/'verification.json')
    native_gds=next(x['gds_validation'] for x in gap_record['stages'] if x['stage']=='gds_native')
    to=read(gaps/'result/to/ito_pass_report.json')
    to_summary=[{k:x.get(k) for k in ('phase','status','accepted','rejected','canonical_hash_before','canonical_hash_after','metric_delta')} for x in to['passes']]
    blockers=[
        {'id':'native_gds','status':'failed','detail':'Native GDS lacks design top gcd and has approximately 1000x coordinate scale error; no conversion fallback admitted. Matching runtime/source fix and revalidation required.','evidence':native_gds},
        {'id':'to_integration','status':'partial','detail':'Fanout, DRV and hold execute using an explicit adapted schema, but not integrated/admitted into the shared core. Native no-mutation passes still change reported setup metrics; timing consistency/closure is unresolved.','evidence':to_summary},
        {'id':'macro_integration','status':'partial','detail':'Two real SRAMs pass native MP, stdcell placement, independent geometry/connectivity and fresh readback. Production manifest, Dispatcher admission, repeated macro runs and DSH remain pending.'},
        {'id':'full_backend','status':'pending','detail':'No native GDS, extracted-RC timing/power or complete server-flow certification. Final DSH full-flow demonstration deliberately withheld per the user prerequisite.'}]
    matrix=[
        ('A1','partial','HD raw input/import passed; SRAM input/bus proof passed separately; registered macro integration pending'),
        ('A2','partial','Three HD routed subsets passed eleven real stages; full backend not certified'),
        ('A3','partial','HD logical endpoints, approved CTS and later invariants passed; iTO-changing candidates not admitted'),
        ('A4-A6','partial','HD instances, IO, geometry and fixed objects passed; two-SRAM operator run passed separately'),
        ('A7','partial','Native two-SRAM placement and independent checks pass; formal production/DSH admission pending'),
        ('A8','partial','HD fresh DEF and full routing-token readback passed; native GDS failed'),
        ('A9','partial','Current DEF-derived self-contained reports generated; final full-flow DSH display pending'),
        ('A10-A12','partial','77 Python and 14 Node checks passed, including rejection/state preservation; full new runtime scenarios still pending'),
        ('A13','pending','No Agent LLM call or DSH full-flow demo in this resumed run'),
        ('A14','partial','Three identical-input HD routed runs passed; macro/full-backend repetition pending'),
        ('A15','partial','4 CPU quota/8 GiB/256 PID bounded containers; native DRC reports 128 worker threads despite OMP setting; no server runs here; quota snapshot linked; total peak memory unknown')]
    quota=read(ROOT/'.cache/dsh-quota.json')
    evidence={'schema':'stage1_live_evidence_v1','date':'2026-11-06','overall_phase1':'partial',
        'full_backend_certified':False,'dsh_final_demo_started':False,'agent_llm_calls':0,'server_eda_calls_this_resumed_run':0,
        'backend':states[0]['contract']['backend_version'],'image':states[0]['contract']['image'],
        'quota':{k:quota[k] for k in ('remainingPercent','checkedAt','source')},
        'tests':{'python':77,'node':14,'python_log':ref(out/'python-tests.log'),'node_log':ref(out/'node-tests.log')},
        'trials':trials,'repeatability':repeat,'macro_input':ref(out/'macro-input-verification.json'),
        'native_extensions':ref(gaps/'verification.json'),'blockers':blockers,
        'matrix':[dict(id=i,status=s,evidence=e) for i,s,e in matrix]}
    write(out/'verification.json',evidence);write(out/'acceptance-matrix.json',evidence['matrix'])
    rows=''.join('<tr><td>'+html.escape(t['trial'])+'</td><td>通过</td><td>'+str(t['routing']['routed_net_num'])+'/'+str(t['routing']['total_net_num'])+'</td><td>0</td><td>'+str(t['metrics']['elapsed_wall_seconds'])+' s</td><td>一致</td></tr>' for t in trials)
    svg=(ROOT/'runs/stage1-routed-baseline-20261106-06/placement.svg').read_text()
    body='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>阶段一实际验收进展</title>
<style>body{max-width:1100px;margin:32px auto;padding:0 22px;font:16px/1.7 system-ui;color:#182b42;background:#f5f7fa}h1{line-height:1.3}section{background:white;padding:20px;margin:20px 0;border:1px solid #dce3ed;border-radius:12px}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:9px;border-bottom:1px solid #ddd}svg{max-width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere} .notice{border-left:5px solid #c57516}summary{cursor:pointer;font-weight:bold}</style>
<h1>主 Agent 阶段一：实际运行与未通过项</h1><p>2026-11-06 · 本机固定 iEDA · 共享 main_task 核心 · 无 Agent 模型调用</p>
<section class="notice"><strong>阶段一仍为部分完成，尚未开始最终 DSH 演示。</strong><p>网表到布线 DEF 子流程已通过；原生 GDS、完整时序流程、宏案例正式接入和 DSH 全流程仍待验收。支持规则内 DRC=0 不等于工艺签核。</p></section>
<section><h2>相同冻结配置的三次真实运行</h2><table><tr><th>运行</th><th>结果</th><th>布线网络</th><th>最终 DRC</th><th>总耗时</th><th>新进程回读</th></tr>'''+rows+'''</table><p>从原始已映射网表开始，依次执行导入、floorplan/IO/PDN、标准单元布局、验证、DEF 回读、CTS、合法化、布线、填充、最终 DRC、布线 DEF 回读。仅覆盖已登记 HD GCD，仍有 16 类 DRC 规则未支持。</p></section>
<section><h2>已完成的修正</h2><p>信号 IO 使用原生 met3/met4 方向配对、800×800 DBU；电源轨 met1=460 DBU，met4/met5 条带=3200 DBU。配置写入新任务契约，并由输出 DEF 独立核对。之前失败任务保持原样。</p><p>两块真实 SRAM 的 native MP、标准单元布局、独立几何检查、新进程回读和原始总线连接核对已通过操作级实验；尚未作为正式宏案例开放。</p></section>
<section><h2>仍需解决</h2><ul><li>原生 GDS 回读缺少 gcd 顶层，几何尺度约小 1000 倍。没有用外部转换结果顶替。</li><li>iTO 新配置可执行，但 setup 时序未收敛；零变更前后的测量差异仍需解释。尚未纳入共享核心。</li><li>宏案例需生产适配、工具登记、重复运行及真实 DSH 验收。</li></ul><p>iTO 候选配置核对了 <a href="https://github.com/OSCC-Project/iEDA/blob/master/src/operation/iTO/source/config/Config.json">官方配置示例</a>和本地固定二进制，公开 master 不是当前课题组构建的同版证明。</p></section>
<section><h2>最新 DEF 派生预览</h2><p>下图只显示真实单元、边界与 IO，不显示金属走线。</p>'''+svg+'''</section><section><details><summary>全部证据与验收矩阵</summary><pre>'''+html.escape(json.dumps(evidence,ensure_ascii=False,indent=2))+'''</pre></details></section></html>'''
    (out/'report.html').write_text(body,encoding='utf-8')
    print(json.dumps({'evidence':str(out/'verification.json'),'report':str(out/'report.html'),'repeatability':repeat},ensure_ascii=False))


if __name__=='__main__':main()
