import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {checkFinal,correctStatusClaims} from './final-consistency.mjs';
import {CARDS} from './tool-library.mjs';
import {taskToolNames} from './main-task-tools.mjs';
import {taskRun} from './main-task-tools.mjs';
import {memoryDirectory} from './decision-context.mjs';
import {AgentHub} from '../ic-workbench/agent-runtime.mjs';
const fixture=new URL('../runs/autonomous-context-20261116/',import.meta.url);
const load=async name=>JSON.parse(await fs.readFile(new URL(name,fixture),'utf8'));
const context=await load('decision-context.json'),memory=await load('decision-memory.json');
const task=context.sections.current_facts.task;
const falseClaim=[{type:'text',text:'相关查询已返回；这满足证据接收条件。全部完成。'}];

test('actual SWERV failure corrects false completion without altering evidence',()=>{
  const before=JSON.stringify(memory),r=checkFinal(falseClaim,task,memory);
  assert.equal(r.check.disposition,'diagnosis_with_gaps');
  assert.ok(r.check.goals.some(g=>g.missing_tools.includes('mp_task_inspect')));
  assert.match(r.blocks[0].text,/EXPERIMENT_CAPABILITY_GAP/);
  assert.doesNotMatch(r.blocks.map(b=>b.text).join('\n'),/这满足证据接收条件/);
  assert.ok(r.check.corrections.length>0);
  assert.equal(JSON.stringify(memory),before);
});
test('a success from another goal/scope never fills the missing receipt',()=>{
  const m=structuredClone(memory);m.receipts.push({ok:true,tool:'mp_task_inspect',goal_id:'wrong',scope:'wrong'});
  assert.equal(checkFinal(falseClaim,task,m).check.disposition,'diagnosis_with_gaps');
});
test('genuine matching receipt satisfies predicate, not physical quality',()=>{
  const m=structuredClone(memory),g=m.goals.at(-1);
  m.receipts.push({ok:true,tool:'mp_task_inspect',goal_id:g.id,scope:g.scope});
  const r=checkFinal([{type:'text',text:'证据已收到，质量仍待验证。'}],task,m);
  assert.equal(r.check.disposition,'predicates_met');assert.equal(r.check.quality_certified,false);
});
test('new goal cannot hide earlier unresolved goal; scope mismatch remains incomplete',()=>{
  const m=structuredClone(memory),g=structuredClone(m.goals[0]);g.id='new';g.completion='stage_completed';g.stage='missing';m.goals.push(g);
  assert.equal(checkFinal(falseClaim,task,m).check.disposition,'diagnosis_with_gaps');
  assert.equal(checkFinal(falseClaim,{...task,run:'other'},memory).check.scope_mismatch,true);
});
test('tool turns and no-goal conversations are unaffected',()=>{
  const calls=[{type:'tool-call',name:'mp_task_inspect'}];assert.deepEqual(checkFinal(calls,task,memory).blocks,calls);
  assert.equal(checkFinal(falseClaim,null,{goals:[],receipts:[]}).check.disposition,'no_subgoal');
});
test('catalog covers every main tool with short purpose and explicit provenance',()=>{
  const names=new Set();for(const c of CARDS){assert.ok(c.summary?.length>15);assert.ok(c.origin?.kind);assert.ok(c.origin?.detail);for(const e of c.endpoints){assert.ok(e.summary?.length>10,e.name);names.add(e.name);}}
  for(const n of taskToolNames)assert.ok(names.has(n),n);
  assert.equal(CARDS.find(c=>c.id==='macro-place').origin.kind,'upstream');
  assert.equal(CARDS.find(c=>c.id==='local-via-eco').origin.kind,'adapted');
});

test('workbench publication boundary keeps diagnosis and corrects archived false final; no EDA submission',async()=>{
  const calls=[];
  const draft=await fs.readFile(new URL('agent-final-response.txt',fixture),'utf8');
  const adapter={async *stream(){yield {type:'block-end',block:{type:'text',text:draft}};}};
  const hub=await new AgentHub({directory:await fs.mkdtemp(path.join(os.tmpdir(),'final-boundary-')),adapter,
    transport:async request=>{calls.push(request.operation);assert.equal(request.operation,'context');return task;}}).init();
  const created=await hub.create(),s=hub.session(created.id),run=taskRun(hub.agent(s)),dir=memoryDirectory(run);
  await fs.mkdir(dir,{recursive:true});await fs.writeFile(path.join(dir,'memory.json'),JSON.stringify(memory));
  s.messages.push({id:'replay',role:'user',content:[{type:'text',text:'离线回放上次最终回复，不运行任何工具。'}]});
  await hub.loop(s,new AbortController().signal);
  assert.equal(s.status.phase,'needs_evidence');assert.equal(s.finalConsistency.disposition,'diagnosis_with_gaps');
  assert.doesNotMatch(hub.view(s).messages.at(-1).text,/这满足证据接收条件/);
  assert.match(await fs.readFile(s.finalConsistency.audit,'utf8'),/这满足证据接收条件/);
  assert.equal(s.events.filter(e=>e.type==='tool_start').length,0);assert.deepEqual(calls,['context']);
});

const currentFixture=new URL('../runs/online-autonomy-20261117/',import.meta.url);
test('truthful unfinished real-case diagnosis remains intact with explicit missing evidence',async()=>{
  const m=JSON.parse(await fs.readFile(new URL('decision-memory.json',currentFixture),'utf8'));
  const t=JSON.parse(await fs.readFile(new URL('decision-context.json',currentFixture),'utf8')).sections.current_facts.task;
  const draft=await fs.readFile(new URL('agent-raw-final.md',currentFixture),'utf8');
  const r=checkFinal([{type:'text',text:draft}],t,m);
  assert.equal(r.check.incomplete,true);assert.equal(r.check.corrections.length,0);
  assert.equal(r.blocks[1].text,draft);
  assert.match(r.blocks[0].text,/缺少成功回执：mp_task_inspect/);
  assert.match(r.blocks[1].text,/149,846/);assert.match(r.blocks[1].text,/0.132/);
  assert.match(r.blocks[1].text,/EXPERIMENT_CAPABILITY_GAP/);
});
test('status correction is local, preserves numerical facts and truthful negative assertions',()=>{
  const input='DRC 为 149,846，全部完成。\n子目标尚未完成；所有任务已经完成。\n不能宣称质量通过。\n版图质量已通过。';
  const r=correctStatusClaims(input,{incomplete:true});
  assert.match(r.text,/DRC 为 149,846/);assert.match(r.text,/子目标尚未完成/);
  assert.match(r.text,/不能宣称质量通过/);assert.doesNotMatch(r.text,/所有任务已经完成|版图质量已通过|全部完成。/);
  assert.equal(r.corrections.length,3);
});
test('meeting evidence predicates does not certify physical signoff',()=>{
  const r=correctStatusClaims('所有任务已经完成。制造签核通过。',{incomplete:false});
  assert.match(r.text,/所有任务已经完成/);assert.doesNotMatch(r.text,/制造签核通过/);
  assert.equal(r.corrections.length,1);
});
test('unfinished investigation does not invalidate completed physical stages or zero-count measurements',()=>{
  const text='原始物理任务已经完成。已完成11个阶段。支持规则下的 DRC 为0，尚不能证明签核通过。';
  assert.equal(correctStatusClaims(text,{incomplete:true}).text,text);
});
test('quoted distinction of flow and quality from the actual online answer is not a pass assertion',()=>{
  const text='合同明确将“流程复现验收”和“物理质量合格”分开。';
  assert.equal(correctStatusClaims(text,{incomplete:true}).text,text);
  const r=correctStatusClaims(text+'但本版图质量已通过。',{incomplete:true});
  assert.match(r.text,/合同明确/);assert.doesNotMatch(r.text,/本版图质量已通过/);
});
test('long negated list from the online answer stays visible; contrast cannot shield a false claim',()=>{
  const text='不能扩张为 DRC-clean、提取寄生后的时序通过、制造签核通过或整体 P1 完成。';
  assert.equal(correctStatusClaims(text,{incomplete:true}).text,text);
  assert.doesNotMatch(correctStatusClaims('虽然尚未核实但是全部任务已经完成。',{incomplete:true}).text,/全部任务已经完成/);
});
