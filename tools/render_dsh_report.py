"""Render measured DSH run artifacts; never executes tools or calls a model."""
from pathlib import Path
import html
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from macro_agent.reporting import svg
from macro_agent.geometry import metrics

run=Path(sys.argv[1]).resolve()
s=json.loads((run/'checkpoint.json').read_text(encoding='utf-8'))
runtime=json.loads((run/'runtime.json').read_text(encoding='utf-8'))
usage=[json.loads(line) for line in (run/'model-usage.jsonl').read_text(encoding='utf-8').splitlines()] if (run/'model-usage.jsonl').exists() else []
before=metrics(s['baseline'])['weighted_hpwl'];after=metrics(s['case'])['weighted_hpwl']
labels={'query_design':'感知设计','retrieve_knowledge':'检索知识 · RAG','run_fixed_tool':'调用固定工具','finish':'结束任务'}
rows=[]
for i,e in enumerate(s['events'],1):
 a=e['action'];r=e['result'];name=a['tool']
 detail= ('HPWL '+str(r['before']['weighted_hpwl'])+' → '+str(r['after']['weighted_hpwl'])+f"；检查 {r['evaluated']} 个候选" if 'evaluated' in r else
          f"检索到 {len(r['hits'])} 个带来源片段" if 'hits' in r else
          f"返回 {len(r['items'])} 个对象，状态与来源可核验" if 'items' in r else str(r.get('status',r.get('error',''))))
 rows.append(f'<article><span class="step">{i}</span><div><h3>{labels.get(name,html.escape(name))}</h3><b>{html.escape(detail)}</b><p>{html.escape(a.get("reason",""))}</p><details><summary>展开原始证据</summary><pre>{html.escape(json.dumps(e,ensure_ascii=False,indent=2))}</pre></details></div></article>')
mode='真实 OpenAI 订阅调用' if runtime['mode']=='official-chatgpt-subscription' else '离线固定动作替身'
models=', '.join(sorted({u['model'] for u in usage})) or '无模型'
page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DSH 主布局 Agent · 实际运行演示</title>
<style>body{{margin:0;background:#f4f6fa;color:#163047;font:16px/1.65 system-ui,'Microsoft YaHei',sans-serif}}main{{max-width:1120px;margin:36px auto;padding:0 24px}}h1{{font-size:30px;margin-bottom:4px}}.tag{{background:#dff3ec;color:#14604b;padding:6px 12px;border-radius:6px}}.cards,.layouts{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin:24px 0}}.cards>div,.layouts>div,article{{background:white;border:1px solid #dbe4ed;border-radius:12px;padding:20px}}.cards strong{{font-size:30px;display:block}}.layouts{{grid-template-columns:1fr 1fr}}svg{{width:100%;height:300px}}h2{{font-size:20px}}h3{{margin:0 0 8px}}article{{display:flex;gap:18px;margin:14px 0}}.step{{border-radius:50%;background:#e8f0ff;width:38px;height:38px;text-align:center;flex-shrink:0;font-weight:700}}p{{color:#536579}}pre{{white-space:pre-wrap;font-size:12px;max-height:300px;overflow:auto}}.note{{background:#e9f0fa;padding:14px;border-radius:8px}}a{{color:#2465a9}}@media(max-width:700px){{.cards,.layouts{{grid-template-columns:1fr}}}}</style>
<main><span class="tag">{mode} · {html.escape(models)}</span><h1>DSH 主布局 Agent · 运行演示</h1><p>感知设计 → 检索知识 → 选择现成工具 → 独立评价与反馈</p>
<div class="cards"><div>加权宏中心 HPWL<strong>{before:g} → {after:g}</strong></div><div>本次代理指标下降<strong>{100*(before-after)/before if before else 0:.2f}%</strong></div><div>模型请求 / 候选评价<strong>{s['counts']['model_calls']} / {s['counts']['evaluations']}</strong></div></div>
<div class="note">这是 DSH 专用主 Agent 的实际运行记录，尚未嵌入 DSH 桌面聊天界面。Tool Maker 未启用。教学案例仅验证机制与代理线长，不能据此声称真实芯片 PPA 提升。</div>
<div class="layouts"><div><h2>初始布局 · {before:g}</h2>{svg(s['baseline'])}</div><div><h2>已接受布局 · {after:g}</h2>{svg(s['case'])}</div></div><p>灰色宏固定不动；图中 Y 轴向下显示。演示批次已结束，保存检查点可继续；不代表达到全局最优。</p>
<h2>模型选择了什么，宿主实际做了什么</h2>{''.join(rows)}
<p><a href="checkpoint.json">完整检查点与测量记录</a> · <a href="model-responses.jsonl">模型原始动作</a> · <a href="model-usage.jsonl">实际调用用量</a></p></main></html>'''
(run/'report.html').write_text(page,encoding='utf-8')
print(run/'report.html')
