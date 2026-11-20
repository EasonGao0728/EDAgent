from __future__ import annotations

import html
import json
from pathlib import Path


def svg(case):
    c = case["core"]
    colors = ["#2563eb", "#0891b2", "#7c3aed", "#059669", "#d97706"]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{c["x"]-2} {c["y"]-2} {c["width"]+4} {c["height"]+4}" role="img" aria-label="Macro layout">',
             f'<rect x="{c["x"]}" y="{c["y"]}" width="{c["width"]}" height="{c["height"]}" fill="#f8fafc" stroke="#64748b" stroke-width="0.4"/>']
    for b in case.get("blockages", []):
        parts.append(f'<rect x="{b["x"]}" y="{b["y"]}" width="{b["width"]}" height="{b["height"]}" fill="#fee2e2" stroke="#dc2626" stroke-width="0.4"/>')
    for i, m in enumerate(case["macros"]):
        color = "#475569" if m["fixed"] else colors[i % len(colors)]
        parts.append(f'<rect x="{m["x"]}" y="{m["y"]}" width="{m["width"]}" height="{m["height"]}" fill="{color}" opacity="0.88"/>')
        parts.append(f'<text x="{m["x"]+m["width"]/2}" y="{m["y"]+m["height"]/2}" text-anchor="middle" dominant-baseline="middle" font-size="2.4" fill="white">{html.escape(m["id"])}</text>')
    parts.append('</svg>')
    return "".join(parts)


def write_report(directory, baseline, best, summary, rounds):
    directory = Path(directory)
    before, after = summary["baseline"]["weighted_hpwl"], summary["best"]["weighted_hpwl"]
    change = 100 * (before - after) / before if before else 0
    lines = ["# 宏单元布局 Agent 首版运行报告", "",
             f"案例：{baseline['case_id']}；模型：{summary['model']}；状态：{summary['status']}。", "",
             "本结果使用教学矩形与宏中心引脚模型，仅验证 Agent 功能和代理线长；没有运行真实标准单元布局、布线、时序或功耗分析。", "",
             f"基线加权 HPWL：{before:g}；最佳：{after:g}；降低：{change:.2f}%。单位：{baseline['units']}。", "",
             f"模型请求：{summary['model_calls']}；候选评价：{summary['evaluations']}；生成版本：{summary['operator_versions']}；已验证工具：{summary['verified_tools']}。", "",
             f"停止原因：{summary['stop_reason']}。", "",
             "| 轮次 | 诊断／需求 | 执行与反馈 |", "|---|---|---|"]
    rows = []
    for record in rounds:
        problem = record.get("problem", "尚未形成有效需求")
        feedback = record.get("feedback", {})
        if feedback.get("error"):
            result = "未接受本轮工具：" + feedback["error"]
        elif feedback.get("selected"):
            selected = feedback["selected"]
            result = (f"外部评价 {feedback['candidate_count']} 个候选；接受 {selected['evaluation_id']}，"
                      f"HPWL {selected['before']['weighted_hpwl']:g} → {selected['after']['weighted_hpwl']:g}。")
        else:
            result = f"外部评价 {feedback.get('candidate_count', 0)} 个候选；保留此前最佳结果。"
            if feedback.get("errors"):
                result += " " + "; ".join(feedback["errors"])
        result = result.replace("|", "/").replace("\n", " ")
        lines.append(f"| {record['round']} | {problem.replace('|', '/')} | {result} |")
        detail = html.escape(json.dumps(feedback, ensure_ascii=False, indent=2))
        rows.append(f"<tr><td>{record['round']}</td><td>{html.escape(problem)}</td><td>{html.escape(result)}<details><summary>完整反馈</summary><pre>{detail}</pre></details></td></tr>")
    lines.extend(["", "证据链：`queries/` → `insights/` → `tool_requests/` → `operators/` → `evaluations/` → `events.jsonl`。", "",
                  "`tool_registry.json` 仅收录产生合法改进候选的工具；这些证据限于本次案例与状态。", "",
                  "[查看布局与反馈](report.html)；[完整运行摘要](run_summary.json)；[最佳设计](best_case.json)。", ""])
    (directory / "report.md").write_text("\n".join(lines), encoding="utf-8")
    (directory / "before.svg").write_text(svg(baseline), encoding="utf-8")
    (directory / "after.svg").write_text(svg(best), encoding="utf-8")
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>宏布局 Agent 运行记录</title>
<style>body{{font:16px/1.7 system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;color:#172033}}h1{{font-size:28px}}.note{{background:#eff6ff;padding:16px;border-radius:10px}}.layouts{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}svg{{width:100%;max-height:420px}}table{{border-collapse:collapse;width:100%;table-layout:fixed}}td,th{{padding:12px;border-bottom:1px solid #dbe2ea;text-align:left;vertical-align:top;overflow-wrap:anywhere}}td:first-child,th:first-child{{width:2.5em;white-space:nowrap}}pre{{font:13px/1.5 ui-monospace,monospace;white-space:pre-wrap;overflow-wrap:anywhere;max-height:300px;overflow:auto}}details{{margin-top:8px;color:#475569}}@media(max-width:650px){{.layouts{{grid-template-columns:1fr}}thead{{display:none}}table,tr,td{{display:block;width:auto!important}}tr{{border-bottom:1px solid #dbe2ea;padding:12px 0}}td{{border:0;padding:6px 0}}td:first-child{{font-weight:bold}}td:first-child::before{{content:'轮次 '}}}}</style>
<h1>宏单元布局 Agent · {html.escape(baseline['case_id'])}</h1>
<p class="note">教学案例：验证设计感知、工具生成与反馈。灰色为固定宏，浅红色为阻塞。图中 Y 轴向下显示。质量仅为宏中心加权 HPWL；尚无真实芯片 PPA 结论。</p>
<p>模型：{html.escape(summary['model'])} · 请求 {summary['model_calls']} 次 · 外部候选评价 {summary['evaluations']} 次 · 已验证工具 {summary['verified_tools']} 个</p>
<div class="layouts"><div><h2>初始布局 · {before:g}</h2>{svg(baseline)}</div><div><h2>最佳已验证布局 · {after:g}</h2>{svg(best)}</div></div>
<p>代理线长降低 {change:.2f}% · {html.escape(summary['stop_reason'])}</p>
<h2>设计诊断与执行反馈</h2><table><thead><tr><th>轮次</th><th>问题与需求</th><th>真实反馈</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<p><a href="run_summary.json">运行摘要</a> · <a href="events.jsonl">事件记录</a> · <a href="tool_registry.json">已验证工具</a> · <a href="best_case.json">最佳设计</a></p></html>'''
    (directory / "report.html").write_text(page, encoding="utf-8")
