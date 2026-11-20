import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {searchTools} from '../dsh/tool-library.mjs';
import {writePerceptionReport} from '../dsh/perception-report.mjs';
const out=path.resolve('runs/p1-tool-library-20261114');
const queries=[
  ['SRAM macro placement','placement','macro-place'],
  ['标准单元布局','placement','cell-place'],
  ['输入网表规模和宏单元特征报告','input','input-profile'],
  ['clock tree synthesis hold timing','clock','clock-timing'],
  ['最终DRC热点按层分析','diagnosis','quality-diagnosis'],
  ['检索后端版本知识 RAG','diagnosis','knowledge-retrieval'],
  ['从检查点调整布局目标密度','optimization','density-branch'],
  ['制作草莓蛋糕',null,null]
];
const results=[];
for(const [query,stage,expected] of queries){const r=await searchTools(query,{stage});results.push({query,stage,expected,mode:r.mode,top:r.candidates.map(c=>({id:c.id,score:c.semantic_score})),expected_in_candidates:expected?r.candidates.some(c=>c.id===expected):r.candidates.length===0,disposition:r.disposition});}
const reports=[];
for(const [kind,name]of [['input','remote-e5c7f543bbce738395e58a0a-input.json'],['quality','remote-0416695c41fde120d84bfdcf-quality.json']]){
 const source=path.resolve('runs/p1-feedback-20261114',name),bytes=await fs.readFile(source);
 const record=JSON.parse(bytes);reports.push({source,source_sha256:createHash('sha256').update(bytes).digest('hex'),...await writePerceptionReport(out,kind,record)});
}
await fs.writeFile(path.join(out,'retrieval-evaluation.json'),JSON.stringify({scope:'Eight hand-written integration probes, not held-out accuracy or threshold calibration',results},null,2));
await fs.writeFile(path.join(out,'reports.json'),JSON.stringify(reports,null,2));
console.log(JSON.stringify({queries:results.length,expected_in_candidates:results.filter(r=>r.expected_in_candidates).length,modes:[...new Set(results.map(r=>r.mode))],reports:reports.map(r=>r.report.path)},null,2));
