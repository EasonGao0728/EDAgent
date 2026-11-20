import test from 'node:test';
import assert from 'node:assert/strict';
import {compactMessages,taskContext,TASK_MARKER} from './context-manager.mjs';
import {turnKey} from './request-budget.mjs';
test('compaction retains user constraints, current facts and complete tool pairs',()=>{
  const messages=[{role:'system',content:[{type:'text',text:'host constraints'}]},
    {role:'user',id:'u',content:[{type:'text',text:'fixed macro A must not move'}]}];
  for(let i=0;i<12;i++)messages.push(
    {role:'assistant',content:[{type:'tool-call',id:'c'+i,name:'mp_task_act',arguments:'{}'}]},
    {role:'tool',toolCallId:'c'+i,content:[{type:'text',text:'x'.repeat(4000)}]});
  messages.push({role:'user',source:{kind:'runtime-context'},content:[{type:'text',text:TASK_MARKER+JSON.stringify({state_id:'new',contract:{fixed:['A']}})}]});
  const result=compactMessages(messages,'archive.jsonl',12000);
  assert.ok(result.compacted);assert.ok(JSON.stringify(result.messages).length<=12000);
  assert.equal(taskContext(result.messages).state_id,'new');
  assert.ok(JSON.stringify(result.messages).includes('fixed macro A must not move'));
  const ids=result.messages.flatMap(m=>(m.content||[]).filter(b=>b.type==='tool-call').map(b=>b.id));
  for(const m of result.messages.filter(m=>m.role==='tool'))assert.ok(ids.includes(m.toolCallId));
  assert.equal(turnKey(messages),turnKey(messages.slice(0,-1)));
});
test('user contract too large fails explicitly, never silently truncates',()=>{
  assert.throws(()=>compactMessages([{role:'user',content:[{type:'text',text:'x'.repeat(6000)}]}],'ref',4000),/CONTRACT_TOO_LARGE/);
});

test('large DSH snapshots retain the latest completed tool call without duplicate metadata',()=>{
  const snapshot=TASK_MARKER+JSON.stringify({state_id:'after-import',contract:{files:'x'.repeat(22000)}});
  const resultText=JSON.stringify({state_id:'after-import',allowed_actions:['floorplan','stop'],evidence:'e'.repeat(22000)});
  const messages=[{role:'user',id:'u',content:[{type:'text',text:'observe once then continue all stages'}]},
    {role:'assistant',content:[{type:'text',text:'old'.repeat(18000)}]},
    {role:'assistant',id:'latest',content:[{type:'tool-call',id:'observed',name:'mp_task_observe',arguments:'{}'}]},
    {role:'tool',toolCallId:'observed',content:[{type:'text',text:resultText}]},
    {role:'user',source:{kind:'runtime-context',form:'snapshot',sections:[{text:snapshot}]},content:[{type:'text',text:snapshot}]}];
  const original=JSON.stringify(messages),result=compactMessages(messages,'archive.jsonl');
  assert.ok(result.compacted);assert.ok(JSON.stringify(result.messages).length<=64000);
  assert.equal(taskContext(result.messages).state_id,'after-import');
  assert.equal(result.messages.find(m=>m.role==='tool').content[0].text,resultText);
  assert.ok(result.messages.some(m=>m.id==='latest'));
  assert.equal(result.messages.find(m=>m.source?.kind==='runtime-context').source.sections,undefined);
  assert.equal(JSON.stringify(messages),original);
});

test('oversized latest tool interaction stops explicitly instead of forgetting and repeating it',()=>{
  const messages=[{role:'user',content:[{type:'text',text:'continue'}]},
    {role:'assistant',content:[{type:'tool-call',id:'c',name:'mp_task_query',arguments:'{}'}]},
    {role:'tool',toolCallId:'c',content:[{type:'text',text:'x'.repeat(20000)}]}];
  assert.throws(()=>compactMessages(messages,'ref',12000),/CONTEXT_LATEST_STEP_TOO_LARGE/);
});

test('branch jobs deduplicate only identical current contract, preserving job and branch state',()=>{
  const task={state_id:'parent',run:'bound',contract:{fixed:['A'],inputs:'x'.repeat(25000)}};
  const messages=[{role:'assistant',content:[{type:'tool-call',id:'c',name:'mp_feedback_continue',arguments:'{}'}]},
    {role:'tool',toolCallId:'c',content:[{type:'text',text:JSON.stringify({job:{job_id:'durable',status:'running'},task:{...task,feedback_campaign:{branches:[{state_id:'child'}]}}})}]},
    {role:'user',source:{kind:'runtime-context'},content:[{type:'text',text:TASK_MARKER+JSON.stringify(task)}]}];
  const result=compactMessages(messages,'archive',40000);const tool=JSON.parse(result.messages.find(m=>m.role==='tool').content[0].text);
  assert.equal(tool.job.job_id,'durable');assert.equal(tool.task.feedback_campaign.branches[0].state_id,'child');
  assert.ok(tool.task.runtime_deduplicated_fields.includes('contract'));assert.deepEqual(taskContext(result.messages).contract,task.contract);
  assert.ok(JSON.parse(messages[1].content[0].text).task.contract);
});
test('feedback branch replies reuse the identical authoritative campaign without losing new fields',()=>{
  const campaign={campaign_state_id:'campaign',branches:[{state_id:'child',evidence:'e'.repeat(22000)}],counts:{model_calls:2}};
  const messages=[{role:'assistant',content:[{type:'tool-call',id:'c',name:'mp_feedback_branch',arguments:'{}'}]},
    {role:'tool',toolCallId:'c',content:[{type:'text',text:JSON.stringify({...campaign,counts:{model_calls:1},warning:'keep'})}]},
    {role:'user',source:{kind:'runtime-context'},content:[{type:'text',text:TASK_MARKER+JSON.stringify({feedback_campaign:campaign})}]}];
  const result=compactMessages(messages,'archive',30000);
  const tool=JSON.parse(result.messages.find(m=>m.role==='tool').content[0].text);
  assert.equal(tool.warning,'keep');assert.equal(tool.counts.model_calls,1);
  assert.ok(tool.runtime_deduplicated_fields.includes('branches'));
  assert.equal(taskContext(result.messages).feedback_campaign.branches[0].state_id,'child');
});
test('server progress after submission does not re-inject an obsolete full campaign',()=>{
  const campaign={created_at:1,baseline_state_id:'base',campaign_state_id:'old',branches:[{branch_id:'b',state_id:'before',completed:[],latest_observation:'x'.repeat(25000)}]};
  const current={run:'bound',state_id:'base',feedback_campaign:{...campaign,campaign_state_id:'new',branches:[{branch_id:'b',state_id:'after',completed:['placement']} ]}};
  const messages=[{role:'assistant',content:[{type:'tool-call',id:'c',name:'mp_feedback_continue',arguments:'{}'}]},
    {role:'tool',toolCallId:'c',content:[{type:'text',text:JSON.stringify({job:{job_id:'j',status:'queued'},task:{run:'bound',state_id:'base',feedback_campaign:campaign}})}]},
    {role:'user',source:{kind:'runtime-context'},content:[{type:'text',text:TASK_MARKER+JSON.stringify(current)}]}];
  const result=compactMessages(messages,'archive',10000);
  const tool=JSON.parse(result.messages.find(m=>m.role==='tool').content[0].text);
  assert.equal(tool.job.status,'queued');assert.equal(tool.task.feedback_campaign_history.branches[0].state_id,'before');
  assert.equal(taskContext(result.messages).feedback_campaign.branches[0].state_id,'after');
  assert.ok(JSON.stringify(result.messages).length<10000);
});
test('standalone older branch reply retains identity after campaign advances',()=>{
  const old={created_at:1,baseline_state_id:'base',campaign_state_id:'old',branches:[{branch_id:'b',state_id:'before',details:'x'.repeat(25000)}]};
  const messages=[{role:'assistant',content:[{type:'tool-call',id:'c',name:'mp_feedback_branch',arguments:'{}'}]},
    {role:'tool',toolCallId:'c',content:[{type:'text',text:JSON.stringify(old)}]},
    {role:'user',source:{kind:'runtime-context'},content:[{type:'text',text:TASK_MARKER+JSON.stringify({feedback_campaign:{...old,campaign_state_id:'new',branches:[]}})}]}];
  const result=compactMessages(messages,'archive',10000);
  const tool=JSON.parse(result.messages.find(m=>m.role==='tool').content[0].text);
  assert.equal(tool.branches[0].state_id,'before');assert.equal(tool.details_archive,'archive');
});
