import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {assembleDecisionContext,recordReceipt,setSubgoal,reflect,readMemory,goalStatus} from './decision-context.mjs';
import {taskContext,TASK_MARKER,compactMessages} from './context-manager.mjs';
const task={run:'remote-fixed',state_id:'s1',contract:{case_id:'swerv',backend_version:'v1',goal:'full_backend'},completed:['placement'],plan:['placement','cts'],download_verified:false};
test('seven sections preserve authoritative task and legacy extraction after compaction',async()=>{
 const run='test-context-'+randomUUID();const v=await assembleDecisionContext(run,task,{tools:[{name:'read',description:'observe'}],messages:[{id:'u',role:'user',content:[{type:'text',text:'保留旧结果'}]}]});
 assert.equal(Object.keys(v.sections).length,7);assert.equal(v.sections.goal_constraints.maker_enabled,false);
 const messages=[{role:'user',source:{kind:'runtime-context'},content:[{type:'text',text:TASK_MARKER+JSON.stringify(v)}]}];
 assert.deepEqual(taskContext(compactMessages(messages,'archive').messages),task);
 assert.equal(v.sections.goal_constraints.user_requirements[0].text,'保留旧结果');
});
test('evidence subgoal needs an actual post-goal tool receipt; failure is not completion',async()=>{
 const run='test-goal-'+randomUUID();await assembleDecisionContext(run,task);
 await recordReceipt(run,'mp_quality_inspect',{}, {status:'old'});
 const g=await setSubgoal(run,task,{state_id:'s1',objective:'读取候选质量',reason:'完成前检查',completion:'evidence_received',evidence_tools:['mp_quality_inspect']});
 assert.equal(g.status,'active');await recordReceipt(run,'mp_quality_inspect',{},null,'network failed');
 let m=await readMemory(run);assert.equal(goalStatus(g,task,m.receipts).status,'active');
 await recordReceipt(run,'mp_quality_inspect',{}, {status:'review_required'});m=await readMemory(run);
 assert.equal(goalStatus(g,task,m.receipts).status,'criteria_met');assert.equal(task.download_verified,false);
 await assert.rejects(()=>setSubgoal(run,task,{state_id:'stale'}),/STALE/);
});
test('summary success cannot satisfy a specific comparison query; failures and old receipts cannot either',async()=>{
 const run='test-query-goal-'+randomUUID();await assembleDecisionContext(run,task);
 await recordReceipt(run,'mp_task_inspect',{kind:'prior_comparison'},{status:'ok'});
 const args={state_id:'s1',objective:'取得可比较的历史布线对照',reason:'摘要不替代对照',completion:'evidence_received',evidence_tools:['mp_task_inspect']};
 await assert.rejects(()=>setSubgoal(run,task,args),/EVIDENCE_QUERY_REQUIRED/);
 const g=await setSubgoal(run,task,{...args,evidence_queries:['mp_task_inspect:prior_comparison']});
 await recordReceipt(run,'mp_task_inspect',{kind:'summary'},{status:'ok'});
 await recordReceipt(run,'mp_task_inspect',{kind:'prior_comparison'},{error:'EXPERIMENT_CAPABILITY_GAP'});
 let m=await readMemory(run),state=goalStatus(g,task,m.receipts);
 assert.equal(state.status,'active');assert.deepEqual(state.missing_evidence,['mp_task_inspect:prior_comparison']);
 await recordReceipt(run,'mp_task_inspect',{kind:'prior_comparison'},{status:'ok'});
 m=await readMemory(run);assert.equal(goalStatus(g,task,m.receipts).status,'criteria_met');
});
test('query predicates also bind the stage and reject unrelated or malformed selectors',async()=>{
 const run='test-query-stage-'+randomUUID();await assembleDecisionContext(run,task);
 const args={state_id:'s1',objective:'读布线证据',reason:'阶段隔离',completion:'evidence_received',evidence_tools:['mp_task_query']};
 await assert.rejects(()=>setSubgoal(run,task,{...args,evidence_queries:['mp_task_inspect:summary']}),/EVIDENCE_QUERY_REQUIRED/);
 const g=await setSubgoal(run,task,{...args,evidence_queries:['mp_task_query:evidence:routing']});
 await recordReceipt(run,'mp_task_query',{kind:'evidence',stage:'placement'},{status:'ok'});
 let m=await readMemory(run);assert.equal(goalStatus(g,task,m.receipts).status,'active');
 await recordReceipt(run,'mp_task_query',{kind:'evidence',stage:'routing'},{status:'ok'});
 m=await readMemory(run);assert.equal(goalStatus(g,task,m.receipts).status,'criteria_met');
});
test('reflection needs real same-scope evidence and remains a hypothesis across restarts',async()=>{
 const run='test-memory-'+randomUUID();await assembleDecisionContext(run,task);
 const receipt=await recordReceipt(run,'mp_quality_inspect',{}, {status:'review_required'});
 const args={state_id:'s1',evidence_ids:[receipt.id],lesson:'当前候选仍需诊断',next_action:'保留原结果'};
 const r=await reflect(run,task,args);assert.equal(r.validation,'unverified');assert.equal(r.evidence[0].status,'review_required');
 await assert.rejects(()=>reflect(run,task,{...args,evidence_ids:['invented']}),/UNKNOWN/);
 const newTask={...task,run:'other-task'};await assert.rejects(()=>reflect(run,newTask,args),/CROSS_TASK/);
 const restored=await assembleDecisionContext(run,task);assert.equal(restored.sections.attempts_feedback.reflections.length,1);
 const other=await assembleDecisionContext(run,newTask);assert.equal(other.sections.attempts_feedback.reflections.length,0);
});
test('stage and delivery predicates require host facts, not model assertions',async()=>{
 const run='test-predicate-'+randomUUID();const a={state_id:'s1',objective:'交付',reason:'核验',completion:'delivery_verified'};
 const g=await setSubgoal(run,task,a);assert.equal(goalStatus(g,task,[]).status,'active');assert.equal(goalStatus(g,{...task,download_verified:true},[]).status,'criteria_met');
 await assert.rejects(()=>setSubgoal(run,task,{...a,completion:'stage_completed',stage:'invented'}),/UNKNOWN_STAGE/);
 const live={...task,completed:undefined,plan:[{stage:'placement',status:'validated'},{stage:'cts',status:'pending'}]};
 const stage=await setSubgoal(run,live,{...a,completion:'stage_completed',stage:'placement'});
 assert.equal(stage.status,'criteria_met');assert.equal(goalStatus({...stage,stage:'cts'},live,[]).status,'active');
});
