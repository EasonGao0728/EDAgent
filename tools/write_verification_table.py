from pathlib import Path
import json
base=Path('D:/aiEDA/literature/2026-10-10')
obj=json.loads((base/'verified_papers.json').read_text(encoding='utf-8'))
papers=obj['papers']
labels={'P01':'全文相关章节与框架图','P02':'全文方法和主要实验与流程图','P03':'全文方法与数据及结果表','P04':'全文基准和实验与结果图表','P05':'出版页面与摘要及更新信息；未取得全文','P06':'全文代理评价与实验及结果表','P07':'出版和大学记录及原始首页；未详读全文','P08':'正式论文页、arXiv、首页与摘要及方法介绍','P09':'作者页面、DOI与首页和摘要','P10':'全文局部改进和端到端实验及表V','P11':'arXiv与首页、摘要及代码入口','P12':'作者页面、DOI与首页和摘要','P13':'官方会议摘要与DOI书目；未取得全文'}
notes={'P01':'arXiv 初稿为 2023 年；正式 TCAD 卷期为 2024 年。','P04':'arXiv 初稿为 2024 年；正式版为 NeurIPS 2025。正式版与预印本作者列表不同，本记录采用正式版。','P05':'原论文页列有 2022 年作者更正与 2024 年增补。本批未获取付费正文。','P07':'注册记录将题名与副标题分开；已按原文完整题名核对。网页工具可读取原始 PDF，直接本地下载遇到 TLS 证书错误。','P10':'正式 TCAD 卷期为 2026 年 7 月；arXiv 上传时间为 2026 年 10 月 5 日。','P11':'只核验到 arXiv 预印本；正式同行评审发表状态未核实。','P12':'此记录为 DAC 2019 会议版。','P13':'已核对 ASP-DAC 官方会议程序与 DOI 注册记录；全文未取得。'}
parts=['# 宏单元布局论文存在性核验表','核验完成时间：'+obj['verification_completed']+'。共 13 篇：12 篇有正式出版记录，1 篇为已核验存在的 arXiv 预印本；取得 10 份本地 PDF。','所有记录均核对了实际题名及作者。10 个正式 DOI 通过 Crossref 题名匹配；PMLR 的两篇会议论文及一篇 arXiv 预印本通过原始记录与原文首页核对。所有论文代码均未执行。','阅读建议见 [文献调研与阅读路线](宏单元布局文献调研与阅读路线.md)，检索覆盖范围见 [检索与核验方法](检索与核验方法.md)。']
table=['| 编号 | 完整题名 | 年份与类型 | 阅读定位 |','|---|---|---|---|']
for r in papers:
    status='预印本' if r['id']=='P11' else ('期刊' if r['status']=='journal article' else '正式会议论文')
    role='首轮第 '+str(r['reading_order'])+' 篇' if r['reading_order'] else ('基础补读' if r['priority']=='foundation' else '延伸阅读')
    table.append(f'| {r["id"]} | [{r["title"]}]({r["primary_url"]}) | {r["year"]} {status} | {role} |')
parts.append('\n'.join(table))
for r in papers:
    parts.extend([f'## {r["id"]} 书目与证据',f'**题名：** {r["title"]}','**作者：** '+'；'.join(r['authors'])+'。',f'**出版信息：** {r["venue"]}，{r["year"]}年'+(f'，卷 {r["volume"]}' if r.get('volume') else '')+(f'，期 {r["issue"]}' if r.get('issue') else '')+(f'，页 {r["pages"]}' if r.get('pages') else '')+'。'])
    identifiers=[]
    if r.get('doi'):identifiers.append(f'[正式 DOI {r["doi"]}](https://doi.org/{r["doi"]})')
    if r.get('arxiv'):identifiers.append(f'[arXiv {r["arxiv"]}](https://arxiv.org/abs/{r["arxiv"]})')
    parts.append('**标识符：** '+'；'.join(identifiers)+'。')
    links=[f'[原始记录]({r["primary_url"]})']
    for i,url in enumerate(r['verification_sources'][1:],1):
        label='DOI 注册元数据' if 'api.crossref.org' in url else ('作者代码或工具文档' if 'github.com' in url or 'readthedocs' in url else f'核验来源 {i}')
        links.append(f'[{label}]({url})')
    parts.append('**实际核验证据：** '+'；'.join(links)+'。')
    if r.get('local_pdf'):parts.append(f'**原文：** [本地 PDF]({r["local_pdf"]})，{r["pdf_pages"]} 页；文件可解析，首页题名已核对。来源和 SHA256 见 verified_papers.json。')
    else:parts.append('**原文获取：** 本批没有取得本地全文 PDF，阅读范围如下。')
    parts.append('**本批阅读范围：** '+labels[r['id']]+'。')
    parts.append('**版本或获取说明：** '+notes.get(r['id'],'以所链接的正式版本或作者原始记录为准。'))
    if r.get('code_url'):parts.append(f'**代码入口：** [作者仓库或官方实现]({r["code_url"]})。本批没有运行代码。')
(base/'论文存在性核验表.md').write_text('\n\n'.join(parts)+'\n',encoding='utf-8')
print('Verification table written:',len(papers),'papers')
