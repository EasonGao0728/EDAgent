import test from 'node:test';
import assert from 'node:assert/strict';
import {correctableToolFailure as classify} from './tool-failure.mjs';
import {randomUUID} from 'node:crypto';

test('unknown subgoal evidence names become a correctable rejection, not success',()=>{
 const r=classify('mp_agent_subgoal',Error('UNKNOWN_EVIDENCE_TOOL'),['mp_quality_inspect','mp_agent_reflect']);
 assert.equal(r.error,'UNKNOWN_EVIDENCE_TOOL');assert.equal(r.status,'rejected_before_write');
 assert.deepEqual(r.registered_evidence_tools,['mp_quality_inspect']);assert.equal(r.native_action_submitted,false);
});
test('stale memory state and missing evidence remain rejections',()=>{
 for(const code of ['STALE_SUBGOAL_STATE','UNKNOWN_OR_CROSS_TASK_EVIDENCE'])assert.equal(classify('mp_agent_reflect',Error(code)).execution_uncertain,false);
});

test('only known read-query integrity rejection becomes failed observation; execution still stops',()=>{
 const error=Error('host bridge: Artifact/input changed: /authorized/task/controller.py; ');
 const r=classify('mp_task_query',error);
 assert.equal(r.status,'read_rejected_integrity_mismatch');assert.equal(r.native_action_submitted,false);assert.equal(r.error,error.message);
 for(const name of ['mp_task_run','mp_task_act','mp_quality_execute','mp_task_inspect'])assert.equal(classify(name,error),null);
 assert.equal(classify('mp_task_query',Error('host bridge: REMOTE_REPLY_UNKNOWN')),null);
});
test('read busy and pretransport policy failures are observations; native and unknown errors still stop',()=>{
 assert.equal(classify('mp_feedback_inspect',Error('host bridge: TASK_BUSY: server action is running; ')).status,'read_temporarily_unavailable');
 assert.equal(classify('mp_quality_execute',Error('host bridge: EVIDENCE_REVIEW_READ_ONLY: execution disabled')).native_action_submitted,false);
 for(const [name,message] of [['mp_quality_execute','host bridge: TASK_BUSY: failed'],['mp_task_inspect','host bridge: REMOTE_REPLY_UNKNOWN'],['mp_agent_reflect','disk full'],['mp_task_run','network failure']])assert.equal(classify(name,Error(message)),null);
});

test('registered subgoal tool returns real failure receipt for model correction without calling server',async()=>{
 const {registerTaskTools,taskRun}=await import('./main-task-tools.mjs');
 const {readMemory}=await import('./decision-context.mjs');const registry=new Map();
 registerTaskTools({tools:{register:t=>registry.set(t.name,t)},on(){}});
 const agent={session:{id:'validation-rejection-'+randomUUID()}};
 const r=await registry.get('mp_agent_subgoal').execute({state_id:'unused',objective:'diagnose',reason:'evidence',completion:'evidence_received',evidence_tools:['invented_tool']},{agent});
 assert.equal(r.error,'UNKNOWN_EVIDENCE_TOOL');assert.equal(r.execution_uncertain,false);assert.ok(r.decision_receipt_id);
 const memory=await readMemory(taskRun(agent));assert.equal(memory.goals.length,0);
 assert.equal(memory.receipts.at(-1).ok,false);assert.equal(memory.receipts.at(-1).id,r.decision_receipt_id);
});
