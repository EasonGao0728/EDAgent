"""Aggregate immutable stage-one trials; require explicit live DSH/UI evidence.

This does not change task contracts, tool qualification or historical artifacts.
"""
import hashlib,html,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from macro_agent.main_task import verify_refs
from macro_agent.def_validation import read_def
from macro_agent.backend_checks import route_records
from macro_agent.full_backend import STAGES as FULL_STAGES
from macro_agent.macro_stages import STAGES as MACRO_STAGES
OUT=ROOT/'runs/stage1-acceptance-20261107'
EXPECTED_DSH={
    'ibench_gcd_legacy':('full_backend',list(FULL_STAGES)),
    'sky130_sram_pair':('placement_def',list(MACRO_STAGES)),
}
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def ref(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def segments(p):
    result={}
    for name,row in route_records(p).items():
        parts=re.split(r'(?:^|\+ )ROUTED ',row,maxsplit=1)
        if len(parts)!=2:raise ValueError('Unrouted net '+name)
        result[name]={'attributes':parts[0].strip(),'segments':sorted(p.strip() for p in re.split(r'\bNEW\b',parts[1]))}
    return result
def group(prefix,macro=False):
    records=[];states=[]
    for n in ('01','02','03'):
        folder=ROOT/'runs'/(prefix+n);s=read(folder/'task.json');states.append(s)
        if s['status']!='target_met' or s['pending']:raise ValueError('Incomplete trial '+str(folder))
        verify_refs(s['input_refs']);verify_refs(s['results'][s['completed'][-1]]['artifact_refs']);verify_refs([s['final_def']])
        r={'task':ref(folder/'task.json'),'contract':s['contract'],'completed':s['completed'],'counts':s['counts'],
           'final_def':s['final_def'],'metrics':read(folder/'metrics.json'),'acceptance':ref(folder/'acceptance.json')}
        if macro:r['macro_validation']=s['results']['macro_placement']['independent_macro_check']
        else:
            r.update(routing=s['results']['routing']['routing_gate'],
              drc={k:v for k,v in s['results']['drc']['drc_gate'].items() if k!='runtime'},
              actual_drc_threads=s['results']['drc']['drc_gate']['runtime'].get('thread_count'),
              native_gds=s['results']['gds_export']['validation'],final_gds=s['deliverables']['final_gds'],
              timing_optimization={k:s['results'][k]['optimization']['native_pass']['timing_quality_after']['wns_tns'] for k in ('to_drv','to_hold')})
        records.append(r)
    same=len({s['contract']['all_inputs_hash'] for s in states})==1
    if not same:raise ValueError('Repeat trial input contracts differ')
    defs=[Path(s['final_def']['path']) for s in states]
    repeat={'three_passed':True,'same_input_hash':same,'byte_identical':len({ref(p)['sha256'] for p in defs})==1,
       'parsed_design_identical':all(read_def(p)==read_def(defs[0]) for p in defs[1:]),
       'same_route_segments_ignoring_order':None if macro else all(segments(p)==segments(defs[0]) for p in defs[1:]),
       'scope':'Three local trials only, not statistical/generalized reproducibility'}
    return {'trials':records,'repeatability':repeat}
def main():
    OUT.mkdir(exist_ok=True)
    full=group('stage1-full-core-20261107-');macro=group('stage1-sram-core-20261106-',True)
    python_log=ROOT/'runs/stage1-final-python-20261107-04.log';node_log=ROOT/'runs/stage1-final-node-20261107-03.log'
    if not re.search(r'Ran 152 tests.*\bOK\b',python_log.read_text(encoding='utf-8',errors='replace'),re.S):raise ValueError('Python tests not passed')
    if not re.search(r'pass 20.*fail 0',node_log.read_text(encoding='utf-8',errors='replace'),re.S):raise ValueError('Node tests not passed')
    current_log=ROOT/'runs/stage1-final-python-20261107-05.log'
    quota_log=ROOT/'runs/stage1-quota-tests-20261107.log'
    recheck_log=ROOT/'runs/stage1-sandbox-timeout-recheck-20261107.log'
    current_text=current_log.read_text(encoding='utf-8',errors='replace')
    # Keep the full-run timing failure visible. The exact failed check was rerun
    # with its original 8-second threshold; never relabel the full run as green.
    failures=re.findall(r'^FAIL: (.+)$',current_text,re.M)
    if (failures!=['test_infinite_program_is_terminated (test_windows_sandbox.SandboxTests.test_infinite_program_is_terminated)']
        or not re.search(r'Ran 154 tests.*FAILED \(failures=1\)',current_text,re.S)
        or not re.search(r'Ran 10 tests.*\bOK\b',quota_log.read_text(encoding='utf-8'),re.S)
        or not re.search(r'test_infinite_program_is_terminated.*Ran 1 test.*\bOK\b',recheck_log.read_text(encoding='utf-8'),re.S)):
        raise ValueError('Latest regression/recheck evidence does not match recorded results')
    tests={'python':154,'node':20,'status':'passed_with_recorded_timing_recheck',
      'latest_full_run':{'passed':153,'failed':1,'failed_test':failures[0],
        'detail':'AppContainer termination wall time 8.281s exceeded unchanged 8s test bound'},
      'failed_check_recheck':{'passed':True,'threshold_changed':False,'test_wall_seconds':2.022},
      'quota_regression_tests':10,
      'evidence':[ref(p) for p in (python_log,current_log,quota_log,recheck_log,node_log)]}
    ui_path=OUT/'dsh-ui-evidence.json';ui=read(ui_path) if ui_path.exists() else {'status':'pending','reason':'DSH activation failed twice; user assistance requested'}
    dsh=[]
    for entry in ui.get('runs',[]):
        task=Path(entry['task']);s=read(task)
        expected=EXPECTED_DSH.get(s['contract']['case_id'])
        if expected is None or s['contract']['goal']!=expected[0] or s['completed']!=expected[1]:
            raise ValueError('DSH task goal/stages do not match the required acceptance workflow')
        if s.get('pending'):raise ValueError('DSH task still has an unresolved action')
        verify_refs(s['input_refs']);verify_refs(s['results'][s['completed'][-1]]['artifact_refs'])
        verify_refs([s['final_def'],s['deliverables']['report'],s['deliverables']['preview']['preview']])
        if s['contract']['goal']=='full_backend':
            verify_refs([s['deliverables']['final_gds'],s['deliverables']['final_netlist']])
        if s['status']!='target_met' or s['contract'].get('input_source')!='conversation_attachments':raise ValueError('DSH task did not complete from conversation inputs')
        if s['counts']['model_calls']<=0:raise ValueError('No real DSH model requests recorded')
        dsh.append({'task':ref(task),'case_id':s['contract']['case_id'],'goal':s['contract']['goal'],'stage_count':len(s['completed']),'counts':s['counts'],
          'report_opened':entry.get('report_opened') is True,'preview_opened':entry.get('preview_opened') is True,
          'ui_observation':entry.get('observation')})
    ui_pass=(ui.get('status')=='passed' and len(dsh)==2 and {r['case_id'] for r in dsh}=={'ibench_gcd_legacy','sky130_sram_pair'}
       and all(r['report_opened'] and r['preview_opened'] for r in dsh))
    matrix=[{'id':f'A{i}','status':'pass','scope':'registered HD full workflow and two-SRAM placement fixture'} for i in range(1,16)]
    for item in matrix:
        if item['id'] in ('A9','A13'):item['status']='pass' if ui_pass else 'pending_live_dsh'
        if item['id']=='A7':item['scope']='Two initially unplaced real SRAM macros, derived reproducible integration netlist; not a functional CPU/PPA benchmark'
        if item['id']=='A8':item['scope']='Fresh DEF roundtrip; native iDB GDS abstract geometry checked by an independent reader'
        if item['id']=='A15':item['scope']='Bounded Docker CPU/memory/PID/time; actual full-flow DRC threads=4; peak memory/model cost unknown'
    limits=['Registered cases and constraints only; no arbitrary netlist/process support',
       'SRAM case verifies macro+stdcell placement, not macro routing or PPA',
       'Native GDS contains LEF abstracts/routes; no transistor-level library GDS or qualified foundry stream map',
       'iDRC covers 10 supported rule families; 16 unsupported families remain; no manufacturing signoff',
       'No qualified RCX technology model, activity or PG electrical scenario; routed timing/power/IR remain unqualified',
       'iTO estimated-RC setup WNS is negative and no timing closure is claimed; standalone iSTA uses no SPEF']
    result={'status':'passed_registered_scope' if ui_pass else 'backend_passed_waiting_live_dsh',
       'overall_phase1_certified':ui_pass,'all_server_compute_this_revision':False,
       'full_backend':full,'macro':macro,'tests':tests,
       'dsh':dsh,'ui_status':ui,'acceptance_matrix':matrix,'limitations':limits,
       'quota':read(ROOT/'.cache/dsh-quota.json')}
    write(OUT/'verification.json',result);write(OUT/'acceptance-matrix.json',matrix)
    rows=''.join('<tr><td>'+x['id']+'</td><td>'+html.escape(x['status'])+'</td><td>'+html.escape(x['scope'])+'</td></tr>' for x in matrix)
    dsh_rows=''.join('<tr><td>'+html.escape(r['case_id'])+'</td><td>'+html.escape(r['goal'])+
      '</td><td>'+str(r['stage_count'])+'</td><td>'+('通过' if r['report_opened'] else '待验收')+
      '</td><td>'+('通过' if r['preview_opened'] else '待验收')+'</td></tr>' for r in dsh)
    text=f'''<!doctype html><meta charset="utf-8"><title>aiEDA stage-one acceptance</title>
<style>body{{font:16px/1.65 sans-serif;max-width:1100px;margin:40px auto;color:#192b43}}table{{border-collapse:collapse;width:100%}}td,th{{padding:9px;border:1px solid #cbd5e1}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}li{{margin:8px 0}}</style>
<h1>aiEDA 阶段一实际验收</h1><p>状态：{result['status']}</p>
<p>{'两类登记案例范围内验收完成。两次真实DSH对话的报告和独立版图卡片均已实际打开并正常显示；界面复核没有重跑布局。' if ui_pass else '仍有真实DSH或交付界面检查未完成，不能标记整体验收通过。'}</p>
<table><tr><th>DSH案例</th><th>目标</th><th>阶段数</th><th>报告卡片</th><th>独立版图卡片</th></tr>{dsh_rows}</table>
<p>HD GCD：完整16阶段后端，固定输入重复3次通过。双真实SRAM：原生宏布局、标准单元布局与回读，重复3次通过。154项Python与20项Node检查有完整记录：最新Python整套运行153通过、1项超时边界失败；该项保持原门槛单独复测通过。新增额度路径的10项回归通过，首次失败日志保留。</p>
<p>完整后端目标包括：导入→版图/IO/PDN→扇出→布局→CTS→DRV/hold→合法化→布线→填充→DRC→时序诊断→原生iDB抽象GDS→新进程DEF回读。</p>
<table><tr><th>项目</th><th>状态</th><th>验收范围</th></tr>{rows}</table>
<h2>明确限制</h2><ul>{''.join('<li>'+html.escape(s)+'</li>' for s in limits)}</ul>
<details><summary>完整证据及文件哈希</summary><pre>{html.escape(json.dumps(result,ensure_ascii=False,indent=2))}</pre></details>'''
    (OUT/'report.html').write_text(text,encoding='utf-8')
    print(json.dumps({'status':result['status'],'full_repeat':full['repeatability'],'macro_repeat':macro['repeatability'],'report':str(OUT/'report.html')},ensure_ascii=False))
if __name__=='__main__':main()
