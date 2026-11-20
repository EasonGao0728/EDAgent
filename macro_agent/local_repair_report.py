"""Render recorded local ECO evidence; does not run EDA or alter a decision."""
import json
from html import escape


def render(receipt):
    d = receipt['diagnosis']
    before = receipt.get('baseline', {})
    after = receipt.get('candidate_quality', {})
    local_before = sum(before.get('local', d['regional_rules_intersecting']).values())
    local_after = sum(after['local'].values()) if 'local' in after else None
    number = lambda n: '未验证' if n is None else f'{n:,}'
    rows = ''.join('<tr><td>'+escape(k)+'</td><td>'+number(before.get('rules', {}).get(k, 0))+'</td><td>'+number(after.get('rules', {}).get(k, 0))+'</td></tr>'
                   for k in sorted(set(before.get('rules', {})) | set(after.get('rules', {}))))
    changes = receipt.get('changes', [])
    region = d['region_dbu']
    extent=[]
    for c in changes:
        for side in ('before_shapes','after_shapes'):
            for rects in c[side].values():
                extent.extend([[a+c['xy'][0],b+c['xy'][1],e+c['xy'][0],f+c['xy'][1]] for a,b,e,f in rects])
    viewport=[min(r[0] for r in extent)-200,min(r[1] for r in extent)-200,max(r[2] for r in extent)+200,max(r[3] for r in extent)+200] if extent else region
    def drawing(key):
        x0, y0, x1, y1 = viewport
        scale = 440 / max(x1-x0, y1-y0)
        elements = []
        colors = {'li1':'#be7030', 'mcon':'#3a5b74', 'met1':'#236bc5', 'via1':'#b3324d', 'met2':'#19a588', 'via2':'#7544bb', 'met3':'#b69811', 'via3':'#db608e', 'met4':'#477588', 'via4':'#885933', 'met5':'#818b47'}
        for c in changes:
            for layer, rects in c[key].items():
                for a,b,e,f in rects:
                    x,y=c['xy']; xx=30+(x+a-x0)*scale; yy=470-(y+f-y0)*scale
                    elements.append(f'<rect x="{xx:.3f}" y="{yy:.3f}" width="{(e-a)*scale:.3f}" height="{(f-b)*scale:.3f}" fill="{colors.get(layer,"#888")}" fill-opacity=".35" stroke="{colors.get(layer,"#888")}" stroke-width=".7"><title>{escape(c["net"]+" / "+layer)}</title></rect>')
        return '<svg viewBox="0 0 500 500" role="img" aria-label="热点内实际改动过孔包围矩形"><rect x="30" y="30" width="440" height="440" fill="#f8fafc" stroke="#9baabc"/>'+''.join(elements)+f'<text x="30" y="493" font-size="12">局部视窗 {escape(str(viewport))} DBU</text></svg>'
    changed_rows=''.join('<tr><td>'+escape(c['net'])+'</td><td>'+escape(str(c['xy']))+'</td><td>'+escape(c['before'])+'</td><td>'+escape(c['after'])+'</td></tr>' for c in changes)
    reasons='、'.join(receipt.get('reasons', [])) or receipt.get('error', '尚无最终判定')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>局部质量反馈与修复闭环</title><style>
body{font:16px/1.7 system-ui;color:#183149;max-width:1150px;margin:32px auto;padding:20px;background:#f8fafc}section{background:white;border:1px solid #d6e1eb;border-radius:12px;padding:22px;margin:18px 0}h1,h2{line-height:1.3}table{width:100%;border-collapse:collapse}td,th{padding:8px;text-align:left;border-bottom:1px solid #e0e7ef;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}svg{width:100%}.muted{color:#53677b}.badge{background:#fff1db;padding:8px 15px;border-radius:8px}@media(max-width:650px){.pair{grid-template-columns:1fr}}
</style><h1>局部质量反馈与修复闭环</h1><p>诊断真实热点 → 已登记固定工具生成候选 → 区域限定调整 → 同一 iDRC 全芯片验证 → 接受门禁 / 回退</p>'''+f'''
<section><h2>判定：{escape(receipt['status'])}</h2><p class="badge">{escape(reasons)}</p><p>原始成果保留；候选未覆盖生产 DEF。Algorithm Agent 未启用。</p><table><tr><th>指标</th><th>基线</th><th>候选</th></tr><tr><td>热点相交 DRC</td><td>{number(local_before)}</td><td>{number(local_after)}</td></tr><tr><td>全芯片 DRC</td><td>{number(before.get('total'))}</td><td>{number(after.get('total'))}</td></tr></table><p>实际修改 {len(changes)} 个过孔记录；区域外新增 marker：{number(receipt.get('new_outside_markers'))}。历史布局、布线阶段未重跑。</p></section>
<section><h2>诊断与动作范围</h2><p>区域 {escape(str(region))} DBU；1000 DBU = 1 μm。按原生 via 相关 marker 的 10 μm 网格密度确定，选择先于候选生成。</p><p>实际候选来源：{escape(receipt.get('proposal_source','原生 iECO 建议'))}。</p><p>假设：形状适配的过孔模板替换可能减小局部冲突。只修改旧、新包围矩形均完整落在热点内的过孔名称；其余原始 DEF 文本逐字保留。原快照旧接口失败、官方 iECO 零替换的记录保留，不能把后续固定适配器的改动记作原生 iECO 的改动。</p><p>这不是通用局部重布线；DRC 总数变化也不能证明连通性、时序或制造签核通过。</p></section>
<section><h2>局部改动预览</h2><p class="muted">仅绘制实际修改过孔的 LEF/DEF 包围矩形，不是完整版图或拥塞热图。两图使用相同坐标与比例；未绘制未修改的线段、引脚和障碍物。</p><div class="pair"><div><h3>调整前</h3>{drawing('before_shapes')}</div><div><h3>候选</h3>{drawing('after_shapes')}</div></div><table><tr><th>网络</th><th>位置 DBU</th><th>原模板</th><th>候选模板</th></tr>{changed_rows}</table></section>
<section><h2>全芯片逐规则对照</h2><table><tr><th>规则</th><th>基线</th><th>候选</th></tr>{rows}</table><p>不允许以总数下降掩盖个别规则回退。电气连通性及布线后时序未验证时，不自动晋升候选。</p></section>
<section><h2>原始证据</h2><details><summary>展开完整 JSON、SHA256、预算与执行日志引用</summary><pre>{escape(json.dumps(receipt,ensure_ascii=False,indent=2))}</pre></details></section></html>'''
