"""Package separate review artifacts, keeping the original delivery immutable."""
from html import escape
from bp_short_study import *
from bp_short_hotspot import key_data
def table(head,rows):
    return '<table><thead><tr>'+''.join('<th>'+escape(str(k))+'</th>' for k in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+escape(str(c))+'</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table>'
def run():
    out=WORK/'delivery';out.mkdir(exist_ok=True)
    d=read(WORK/'diagnosis.json');phy=read(WORK/'physical-causes.json');a=read(WORK/'forest-attribution.json')['metal_short']
    p=read(WORK/'proposal.json');r=read(WORK/'trial-result.json')
    assert r['status']=='accepted' and digest(ORIGINAL)==HASH and r['candidate_sha256']==digest(WORK/'trial/input.def')
    added=sorted(keys(WORK/'trial/keys.gz')-keys(WORK/'production.keys.gz'))
    cross=phy['checkpoint_cross_tab']
    already=sum(n for k,n in cross.items() if k.startswith('new/raw_before/'))
    def n(i):return f'{i:,}'
    layers=[(l,n(ct),f'{100*ct/213494:.2f}%',n(phy['attribution_by_layer'][l]['retained']),n(phy['attribution_by_layer'][l]['new'])) for l,ct in sorted(d['layers'].items())]
    regions=[(f'{x0}–{x1}',f'{y0}–{y1}',n(row['count']),f'{100*row["count"]/213494:.2f}%') for row in d['tiles'][:8] for x0,y0,x1,y1 in [row['bounds_um']]]
    geom=phy['nonexclusive_geometry'];classified=sum(v for k,v in phy['exclusive_geometry'].items() if k!='unresolved')
    changes=[(key,n(r['before'][key]),n(r['after'][key]),r['removed'].get(key,0),r['added'].get(key,0)) for key in sorted(r['before'])]
    examples=[(key.split('|')[0],l,'，'.join(nets),', '.join(f'{i/2000:.3f}' for i in box)) for key in added for l,box,nets in [key_data(key)]]
    graph=r['whole_chip_graph'];trialref=WORK/'trial/input.def'
    name='bp-multi-hotspot.def.gz'
    tmp=out/'candidate.tmp'
    with trialref.open('rb') as src,tmp.open('wb') as raw,gzip.GzipFile(filename='',mode='wb',compresslevel=3,fileobj=raw,mtime=0) as dest:shutil.copyfileobj(src,dest)
    tmp.replace(out/name)
    with gzip.open(out/name,'rb') as f:
        h=hashlib.sha256()
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
        assert h.hexdigest()==r['candidate_sha256']
    att=read(WORK/'forest-attribution.json');proj=read(WORK/'forest-projection.json')
    data=dict(case='bp_multi',original_def_sha256=HASH,checker=AUDITED_BINARY,diagnosis=d,physical=phy,
              reference_files=read(FAMILY/'state-contract.json')['contract']['reference'],counterfactual=att,
              changed_checkpoint_nets=read(WORK/'projection.json')['count'],native_tree_control=proj['stats'],raw_sensitivity=read(WORK/'attribution.json'),new_marker_rows=added,
              proposal=p,trial=r,receipts={v:read(WORK/v/'receipt.json') for v in ('pre','control','forest-pre','forest-post','trial')})
    save(out/'bp-multi-hotspot.json',data)
    doc='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>bp_multi 金属短路归因与局部修复</title><style>body{max-width:940px;margin:42px auto;padding:0 22px;color:#1b2d36;font:16px/1.65 system-ui}h2{margin-top:32px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}td,th{border-bottom:1px solid #cbd3d7;text-align:left;padding:6px}code{overflow-wrap:anywhere}</style><h1>bp_multi 金属短路归因与局部修复</h1>'''
    doc+=f'<p>Nangate45 · 父版图 213,494 项金属短路 · 单网试验净减少 21 项短路和 20 项全片 DRC · 复验开路 0。</p><h2>短路集中在哪些层和位置</h2>'
    doc+=table(['布线层','原版短路','占比','补线前已有','相对补线前新增'],layers)
    doc+='<p>区域按标记包围盒的中心归属，采用固定 100 × 100 µm 网格。坐标原点为 DEF 左下角。</p>'+table(['X 范围（µm）','Y 范围（µm）','短路数','占全片'],regions)
    doc+=f'<h2>哪些是原有的，哪些随补线出现</h2><p>补线前的 D12_4761 检查点有 423 条断开的网，当时没有导出整片 DEF。对有修改的 1,201 条网，使用本次 iRT 的原生建树函数逐个引脚连通分量还原可导出的导体，保留固定放置和其他网的原始路由。补线后的对照用同一函数导出，与交付 DEF 的受影响线路和过孔逐段相符，全部 339,643 条 DRC 标记键完全一致。对照固定检查器、配置和 LEF，以规则、层、包围盒及涉网的原生键匹配。</p>'
    doc+=f'<p>还原的补线前版图有 {n(a["before"])} 项金属短路。前后共有 {n(a["common"])} 项，新增 {n(a["added"])} 项，消失 {n(a["removed"])} 项。新增按最终输出几何定义。其中 {n(already)} 项在补线前未裁剪的分区线段中就能检出，连通分量接通后才进入最终引脚树。其余 {n(a["added"]-already)} 项在原始分区线段对照中也没有同键标记。数量单位是几何标记，同一对网可以对应多条标记。</p>'
    doc+=f'<h2>物理原因</h2><p>对全部标记匹配实际导线、LEF 过孔金属和障碍形状，其中 {n(classified)} 条找到了双方几何在标记框内有正面积重叠的证据。{n(geom.get("perpendicular_wires",0))} 条涉及同层横、竖导线交叉，{n(geom.get("parallel_wires",0))} 条涉及同向导线金属相交，{n(geom.get("wire_via",0))} 条涉及导线与过孔金属相交。一个标记允许有多种几何解释。原生详细布线日志记录了 1/1 轮，原生布线器在导出前已报告大批短路。仅凭本实验无法确定增加轮数会减少多少违规。</p>'
    doc+=f'<p>填充单元插入前，路由器的违规报告已在 metal5 和 metal6 分别计到 63,537 和 59,131 项金属短路，与最终独立检查的这两层逐层计数一致。{n(phy["inside_macro"]["inside_macro"])} 个短路标记的中心落在硬宏平面投影内，具体导电层和相交对象仍需逐条核对。用闭合边界复核，另有 {n(phy["unresolved_detail"]["closed_contact"])} 项能匹配到边界接触，尚有 {n(phy["unresolved_detail"]["no_matched_pair"])} 项未能独立还原双方接触。</p>'
    doc+=f'<h2>已接受的服务器局部候选</h2><p>最密集格内的网络 <code>{escape(p["name"])}</code> 原本在优选竖走的 metal6 水平穿过其他网络。保留两端，在 y=333.830 µm、x=514.735–525.935 µm 之间转到优选横走的 metal5，经两个 via5_0 回接。只改动这条网的一段线。独立全片 iDRC 从 {n(r["total_before"])} 降至 {n(r["total_after"])}。该格 DRC 从 {n(r["hotspot_before"])} 降至 {n(r["hotspot_after"])}，金属短路从 {n(r["hotspot_short_before"])} 降至 {n(r["hotspot_short_after"])}。</p>'
    doc+=table(['规则','修复前','修复后','消失','新增'],changes)+ '<h3>新出现的四项标记</h3>'+table(['类型','层','涉网','包围盒 x₁, y₁, x₂, y₂（µm）'],examples)
    doc+=f'<p>候选完整 DEF 按引脚、导线和 LEF 过孔重建同网连通图，核对 {n(graph["net_count"])} 条网、{n(graph["pins"])} 个端点，开路与悬浮几何均为 0。此轮验收范围为短路、已加载规则的 DRC 与同网连通性。芯片仍有 {n(r["total_after"])} 项违规。</p><p>父 DEF SHA-256 <code>{HASH}</code><br>候选 DEF SHA-256 <code>{r["candidate_sha256"]}</code></p></html>'
    (out/'bp-multi-hotspot.html').write_text(doc,encoding='utf8')
    names=[name,'bp-multi-hotspot.json','bp-multi-hotspot.html']
    save(out/'manifest.json',dict(parent=HASH,candidate_sha256=r['candidate_sha256'],files={v:dict(bytes=(out/v).stat().st_size,sha256=digest(out/v)) for v in names}))
if __name__=='__main__':run()
