"""Render the AES acceptance matrix from actual receipts; pending stays pending."""
import datetime,hashlib,html,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'runs/aes-p1-20261108'
CASES=[('aes_sky130_t','AES Cipher',9434,'cipher'),('aes_legacy','AES wrapper',18646,'legacy'),('aes_core_sky130_t','AES Core',20092,'core')]
def read(p):return json.loads(p.read_text(encoding='utf-8')) if p.is_file() else None
def esc(v):return html.escape(str(v))

def sha(p):
    with Path(p).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def evidence_binding(case,server,desktop,task,comparison,ui):
    """Old-session comparisons or card observations cannot certify a new run."""
    comparison_errors=[];ui_errors=[]
    if not desktop or not task:return False,False,{'comparison':['missing_current_task'],'ui':['missing_current_task']}
    task_hash=sha(desktop/'task.json')
    def same_path(value,expected):
        return isinstance(value,str) and Path(value).resolve()==expected.resolve()
    if not comparison or comparison.get('status')!='matched':comparison_errors.append('comparison_not_matched')
    else:
        if comparison.get('case')!=case:comparison_errors.append('comparison_case')
        if not same_path(comparison.get('server'),server):comparison_errors.append('comparison_server_run')
        if not same_path(comparison.get('dsh'),desktop):comparison_errors.append('comparison_dsh_run')
        if comparison.get('server_run_sha256')!=sha(server/'run.json'):comparison_errors.append('comparison_server_hash')
        if comparison.get('dsh_task_sha256')!=task_hash:comparison_errors.append('comparison_task_hash')
    if not ui or ui.get('report_open_observed') is not True or ui.get('preview_open_observed') is not True:
        ui_errors.append('cards_not_observed')
    else:
        if ui.get('case')!=case:ui_errors.append('ui_case')
        if not same_path(ui.get('native_task'),desktop):ui_errors.append('ui_dsh_run')
        if ui.get('dsh_task_sha256')!=task_hash:ui_errors.append('ui_task_hash')
        delivery=task.get('deliverables') or {}
        expected={'report':delivery.get('report'), 'preview':(delivery.get('preview') or {}).get('preview')}
        observed=ui.get('opened_artifacts') or {}
        for kind,ref in expected.items():
            opened=observed.get(kind) or {}
            if not ref or not same_path(opened.get('path'),Path(ref['path'])) or opened.get('sha256')!=ref.get('sha256'):
                ui_errors.append('ui_'+kind+'_reference')
            elif not Path(ref['path']).is_file() or sha(ref['path'])!=ref['sha256']:
                ui_errors.append('ui_'+kind+'_artifact_changed')
    return not comparison_errors,not ui_errors,{'comparison':comparison_errors,'ui':ui_errors}
def render():
    status=read(OUT/'status.json');tracked={x['case_id']:x for x in status['cases']};rows=[];matrix=[]
    for case,label,cells,short in CASES:
        t=tracked[case]
        server=Path(t['server_run']) if t.get('server_run') else OUT/'downloaded/v5b'/('server-'+short+'-01')
        s=read(server/'run.json');desktop=Path(t['dsh_run']) if t.get('dsh_run') else None
        d=read(desktop/'task.json') if desktop else None
        comparison=read(OUT/'comparisons'/(case+'.json'));ui=read(OUT/'ui-evidence'/(case+'.json'))
        matched,displayed,binding=evidence_binding(case,server,desktop,d,comparison,ui)
        passed=bool(s and s['status']=='passed' and d and d['status']=='target_met' and matched and displayed)
        drc=(comparison or {}).get('drc',{}) if matched else {}
        baseline_drc=next((v['drc_gate']['violation_count'] for v in (s or {}).get('stages',[]) if v['stage']=='drc'),None)
        row={'case':case,'cells':cells,'hard_macros':0,'server':s['status'] if s else t['server_status'],
            'dsh':d['status'] if d else t['dsh_status'],'comparison':('matched' if matched else ('evidence_not_current' if comparison and comparison.get('status')=='matched' else comparison.get('status') if comparison else 'pending')),
            'report_and_preview_observed':displayed,'orchestration_passed':passed,
            'evidence_binding':binding,
            'wall_time_amendment':(d or {}).get('quota_continuation'),
            'resource_time_amendment':(d or {}).get('resource_continuation'),
            'server_drc':drc.get('server_violations',baseline_drc),'dsh_drc':drc.get('dsh_violations'),
            'supported_drc_clean':drc.get('physical_quality_passed'),'signoff_clean':False}
        matrix.append(row)
        details=' / '.join(esc(x) if x is not None else '待验' for x in [row['server_drc'],row['dsh_drc']])
        note='<small>额度中断后经授权续接；原九小时墙钟时限未满足，未重跑已完成阶段。</small>' if row['wall_time_amendment'] else ''
        if row['resource_time_amendment']:
            note+='<small>原六小时路由超时已保留；经用户授权仅将未完成路由上限延长到18小时、续接总时限20小时。前10阶段未重跑；原资源时间预算未通过。</small>'
        rows.append('<tr>'+''.join('<td>'+x+'</td>' for x in [esc(label)+'<small>'+esc(case)+'</small>'+note,f'{cells:,} / 0',esc(row['server']),esc(row['dsh']),esc(row['comparison']),details,'已核验' if displayed else '待验','通过' if passed else '待完成'])+'</tr>')
    accepted=all(r['orchestration_passed'] for r in matrix)
    receipt={'updated_at':datetime.datetime.now().astimezone().isoformat(),'p1_aes_orchestration_passed':accepted,
        'physical_quality_separate':True,'cases':matrix,'scope':'Three registered standard-cell AES cases; no AES hard-macro coverage or manufacturing signoff',
        'policy':'User-approved: complete truthful flow reproduction can pass orchestration while residual DRC fails physical quality'}
    (OUT/'acceptance-matrix.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    page='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>中型 AES P1 验收</title>
<style>body{font:16px/1.65 system-ui,sans-serif;margin:36px auto;max-width:1500px;padding:0 24px;background:#f6f8fb;color:#182b43}h1{margin-bottom:6px}.panel{background:white;padding:22px;border-radius:12px;margin:18px 0}table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:12px;text-align:left;border-bottom:1px solid #dbe3ee}th{background:#edf3fa}small{display:block;color:#5e6c80}code{overflow-wrap:anywhere}.status{font-size:22px;font-weight:700;color:#2463a5}a{color:#2463a5}</style>
<h1>中型 AES · P1 验收</h1><p>完整编排与版图质量分开判定；所有结论以本次运行证据为准。</p>
<div class="panel status">'''+('三例编排与复现验收通过' if accepted else '验收尚未完成')+'''</div>
<div class="panel"><table><thead><tr><th>案例</th><th>标准单元 / 硬宏</th><th>服务器全流程</th><th>DSH 对话运行</th><th>两端对比</th><th>DRC 数量<br>服务器 / DSH</th><th>交付卡片</th><th>编排验收</th></tr></thead><tbody>'''+''.join(rows)+'''</tbody></table></div>
<div class="panel"><b>验收依据</b><p>每例须从七个对话输入文件出发，完成16阶段；核对输入与运行版本、各阶段 DEF 几何和连接、逐网络布线、缓冲器端点及驱动方向、DRC 规则与违规位置、时序诊断数值、原生抽象 GDS 几何，以及报告和预览卡片的实际显示。</p><p>Windows/Linux 换行、布线记录顺序、报告生成时间和耗时按表示差异处理。时序报告若选择不同的同值最短路径，须专项验证 TNS、最大延时路径、完整精度数据路径、DEF 连接和零延时理想时钟条件；原报告仍记录为文本不同。数值或几何差异不能自动视为等价，不设置任意容差。</p><p>残余 DRC 单列为版图质量未通过。这里的时序为无 SPEF 的单元延时诊断；GDS 包含 LEF 抽象和布线，不能代表制造签核。三例都无硬宏；双 SRAM 布局验收属于此前单独的范围。</p></div>
<div class="panel"><b>Docker 启动恢复</b><p>已实际通过正常关闭后的冷启动验证。DSH 原生 EDA 动作执行前检查 Linux Engine，必要时通过 Windows 桌面入口启动已有 Docker；不直接从 Agent 进程拉起 Docker Desktop。该措施是本机验证过的规避方式，不承诺 Docker 套接字故障永不复发。</p><a href="docker-coldstart-check.json">冷启动证据</a> · <a href="runtime-smoke/runtime-parity.json">286 个运行文件核对</a></div>
<p><a href="acceptance-matrix.json">机器可读验收矩阵</a> · <a href="status.json">推进状态</a></p><small>生成时间：'''+esc(receipt['updated_at'])+'</small></html>'
    (OUT/'report.html').write_text(page,encoding='utf-8')
    print(json.dumps({'p1_aes_orchestration_passed':accepted,'cases':len(matrix),'report':str(OUT/'report.html')}))
if __name__=='__main__':render()
