import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {readMemory,goalStatus,memoryDirectory} from './decision-context.mjs';

// The host owns completion; an unfinished goal does not invalidate its evidence.
// This narrow prose lint is NOT a verifier of arbitrary diagnosis/measurement claims.
// Keep the complete draft and every replacement in the audit.
export function correctStatusClaims(text,{incomplete,qualityCertified=false}){
  const corrections=[];
  const rules=[
    ...(incomplete?[
      /(?:全部(?:任务|子目标)?|所有(?:任务|子目标)|整体|本轮(?:调查|诊断|任务)?|子目标)[^，,。！？；;\n]{0,24}?(?:均已|均|已经|已|全部)?完成(?!条件|阶段|实验|记录|列表|\d)/g,
      /(?:完成条件|证据接收条件)[^。！？；;\n]{0,12}?(?:已经|已|全部|均)?满足/g,
      /(?:这|已)[^。！？；;\n]{0,4}满足(?:证据接收|完成)条件/g,
      /\b(?:all (?:tasks?|subgoals?|criteria) (?:are |have been )?(?:complete[d]?|met|satisfied)|subgoal (?:is |has been )?completed)\b/gi,
      /(?:状态|标记|status)[^。！？；;\n]{0,12}?criteria_met/gi,
    ]:[]),
    ...(!qualityCertified?[/质量[^。！？；;\n]{0,6}?(?:已通过|通过|合格)/g,/(?:制造)?签核(?:已)?通过/gi]:[]),
  ];
  const corrected=text.split(/(?<=[，。！？；;\n])|(?<=[.!?])(?=\s|$)/u).map(segment=>{
    // Negation is local to each assertion, never a blanket exemption for a paragraph.
    const plain=segment.replace(/[*_`]/g,'');
    for(const pattern of rules){pattern.lastIndex=0;for(const match of plain.matchAll(pattern)){
      const before=plain.slice(0,match.index),claim=match[0];
      const localPrefix=before.split(/但是|然而|不过|但|却|而是|\bbut\b|\bhowever\b/i).at(-1);
      if(/(?:不|未|尚未|没有|不能|不可|并非|不是|不足以|不代表|不宣称|不应|不得|待|\bnot\b|\bnever\b|\bcannot\b|\bno\b)\s*[^，,。！？；;\n]*$/i.test(localPrefix)||/(?:未|不|没有|尚未)/.test(claim))continue;
      // Mentioning a quality term to distinguish two concepts is not asserting it.
      if(/(?:区分|分开|分别判定|不是一回事|并不等同)/.test(plain)&&/[“「][^”」]*[”」]/.test(plain))continue;
      // Definitions, requirements and proposed future work are not completion assertions.
      if(/(?:只有|才能|需要|应当|必须|如何|如果|若|后续|将来|目标是)[^，,。！？；;\n]{0,30}$/.test(before))continue;
      const replacement=incomplete&&rules.indexOf(pattern)<rules.length-2?'[宿主更正：子目标完成条件尚未全部满足，详见状态与缺口清单。]':'[宿主更正：当前不能据此宣称物理质量或签核通过。]';
      corrections.push({original:segment,replacement,matched:claim});
      return replacement+(segment.endsWith('\n')?'\n':'');
    }}return segment;
  }).join('');
  return {text:corrected,corrections};
}
export function checkFinal(blocks,task,memory){
  if(blocks.some(b=>b.type==='tool-call'))return {blocks,check:{disposition:'tool_turn'}};
  const goals=memory.goals.map(g=>goalStatus(g,task,memory.receipts));
  const relevant=goals.filter(g=>g.status!=='different_task_scope');
  const unresolved=relevant.filter(g=>g.status!=='criteria_met');
  const scopeMismatch=goals.length>0&&goals.at(-1).status==='different_task_scope';
  const incomplete=Boolean(unresolved.length||scopeMismatch);
  const check={version:2,authority:'host_predicate',state_id:task?.state_id??null,
    disposition:incomplete?'diagnosis_with_gaps':relevant.length?'predicates_met':'no_subgoal',
    incomplete,diagnosis_verification:'not_a_semantic_fact_checker',corrections:[],
    goals:relevant.map(g=>({id:g.id,objective:g.objective,status:g.status,completion:g.completion,
      predicate_precision:g.predicate_precision,missing_evidence:g.missing_evidence||[],
      missing_tools:g.completion==='evidence_received'?[...new Set((g.missing_evidence||[]).map(q=>q.split(':')[0]))]:[]})),
    scope_mismatch:scopeMismatch,quality_certified:false};
  if(check.disposition==='no_subgoal')return {blocks,check};
  const lines=check.goals.map(g=>`- ${g.objective}：${g.status==='criteria_met'?'登记的完成谓词已满足（criteria_met）':'尚未满足完成条件（active）'}${g.missing_evidence.length?'；缺少成功回执：'+g.missing_evidence.join('、'):''}${g.completion==='evidence_received'&&g.predicate_precision==='tool_or_stage_only'?'；旧目标仅按工具级回执判定，不认证查询内容是否覆盖目标':''}。`);
  const body=blocks.map(b=>{
    if(b.type!=='text')return b;
    const result=correctStatusClaims(b.text,{incomplete});check.corrections.push(...result.corrections);
    return {...b,text:result.text};
  });
  if(incomplete){
    const failures=memory.receipts.filter(r=>!r.ok&&unresolved.some(g=>g.id===r.goal_id&&g.scope===r.scope));
    const errors=failures.slice(-4).map(r=>`- ${r.tool}：${String(r.error||r.status||'未获得有效证据').slice(0,600)}`);
    const received=memory.receipts.filter(r=>r.ok&&relevant.some(g=>g.scope===r.scope));
    return {check,blocks:[{type:'text',text:[
      '本轮诊断已展示；子目标尚未全部完成。已有证据不会因其他证据缺失而作废，以下宿主状态不由模型正文改写。',
      '宿主完成状态：\n\n'+lines.join('\n'),
      scopeMismatch?'当前任务与最新子目标作用域不一致，需要重新核对任务绑定。':'',
      received.length?'已取得的同任务工具回执：'+[...new Set(received.map(r=>r.tool))].join('、')+'。成功返回只证明已收到证据，不代表正文所有推断已验证。':'',
      errors.length?'未完成证据：\n\n'+errors.join('\n'):'',
      '下一步应补齐缺失证据或明确处理能力缺口，再核验完成条件。失败返回不算成功回执；本检查不会修改目标、重跑阶段或提交工具作业。',
      '子目标完成条件、物理质量与文件交付分别判定；此处不表示质量通过。',
      check.corrections.length?`已局部更正 ${check.corrections.length} 处与宿主状态冲突的宣称；原文及更正记录已留存审计。`:'',
      '以下保留诊断与建议。工具测量结论、原因推断、后续建议应分别阅读；缺失证据不能当成通过。'
    ].filter(Boolean).join('\n\n')},...body]};
  }
  return {check,blocks:[{type:'text',text:'宿主已核对本任务子目标的完成条件；这不代表版图质量通过。\n\n'+lines.join('\n')},...body]};
}

export async function guardFinal(run,task,blocks){
  if(blocks.some(b=>b.type==='tool-call'))return {blocks,check:{disposition:'tool_turn'}};
  let memory;
  try{memory=await readMemory(run);}catch{throw Error('FINAL_STATE_UNAVAILABLE: 无法读取子目标证据，最终答复未发布。');}
  const result=checkFinal(blocks,task,memory);
  const dir=path.join(memoryDirectory(run),'final-checks');
  const record={at:new Date().toISOString(),...result.check,raw_blocks:blocks,displayed_blocks:result.blocks};
  const id=createHash('sha256').update(JSON.stringify(record)).digest('hex');
  await fs.mkdir(dir,{recursive:true});await fs.writeFile(path.join(dir,id+'.json'),JSON.stringify(record,null,2));
  return {...result,check:{...result.check,audit:path.join(dir,id+'.json')}};
}
