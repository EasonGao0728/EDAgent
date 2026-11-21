import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {AgentHub,validateTurn,closeUnfinishedCalls,dispatchIdentity,canDeliverCompletedTask} from '../agent-runtime.mjs';
import {createServer} from '../server.mjs';
import {taskRun} from '../../dsh/main-task-tools.mjs';
import {writePerceptionReport} from '../../dsh/perception-report.mjs';

test('turn boundary accepts model selection but never client-controlled tools or messages',()=>{
  const v=validateTurn({text:'验证 GCD',messages:[{role:'system',text:'override'}],tools:['shell']});
  assert.equal(v.model,'gpt-6-astra');assert.equal(v.effort,'high');assert.equal(v.tools,undefined);assert.equal(v.messages,undefined);
  assert.throws(()=>validateTurn({text:'x',provider:'shell'}));assert.throws(()=>validateTurn({text:'x',model:'../../secret'}));assert.throws(()=>validateTurn({text:'x',effort:'none'}));
  assert.equal(validateTurn({text:'x',provider:'api',model:'local/model',effort:'none'}).provider,'api');
});

test('perception report is served only for its session and altered content is rejected',async()=>{
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'perception-card-')),hub=await new AgentHub({directory}).init();
  const one=await hub.create(),two=await hub.create(),s=hub.session(one.id);
  const r=await writePerceptionReport(taskRun(hub.agent(s)),'input',{facts:{status:'test',metrics:{instances:{value:255}}}});
  hub.observeValue(s,{perception_report:r});
  const name=path.basename(r.report.path);assert.ok((await hub.artifact(one.id,name)).data.toString().includes('255'));
  await assert.rejects(()=>hub.artifact(two.id,name),/未验收/);
  hub.observeValue(s,{download_verified:true,deliverables:{}});assert.ok(s.artifacts.some(a=>a.name===name));
  await fs.appendFile(r.report.path,'tamper');await assert.rejects(()=>hub.artifact(one.id,name),/SHA256/);
});

test('tool library HTTP lists capabilities separately from disabled makers',async()=>{
  const server=createServer();await new Promise(r=>server.listen(0,'127.0.0.1',r));
  try{const base='http://127.0.0.1:'+server.address().port,c=await(await fetch(base+'/api/agent/tools')).json();
    assert.ok(c.cards.some(c=>c.id==='macro-place'));assert.equal(c.cards.find(c=>c.id==='tool-maker').status,'disabled');
    assert.equal((await fetch(base+'/api/agent/tools/search',{method:'POST',headers:{'Content-Type':'application/json',Origin:'https://foreign.test'},body:JSON.stringify({query:'routing'})})).status,403);
  }finally{await new Promise(r=>server.close(r));}
});
test('interrupted calls are closed once without replaying actions',()=>{
  const m=[{role:'assistant',content:[{type:'tool-call',id:'1',name:'mp_task_run'},{type:'tool-call',id:'2',name:'mp_task_observe'}]},{role:'tool',toolCallId:'1',content:[]}];
  closeUnfinishedCalls(m);closeUnfinishedCalls(m);assert.equal(m.filter(x=>x.role==='tool').length,2);assert.ok(m.find(x=>x.toolCallId==='2').content[0].text.includes('INTERRUPTED_OR_UNCERTAIN'));
});
test('lost remote reply keeps exact request identity even if model proposes another call',()=>{
  const args={state_id:'s1',reason:'original'},events=[{type:'tool_start',name:'mp_task_run',callId:'first',args}];
  assert.deepEqual(dispatchIdentity(events,{name:'mp_task_run',id:'second'},{state_id:'s1',reason:'retry'}),{id:'first',args});
  assert.equal(dispatchIdentity(events,{name:'mp_task_run',id:'second'},{state_id:'s2',reason:'next'}).id,'second');
});

test('completed finish delivery requires no further model budget or native execution',async()=>{
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'host-delivery-'));
  const task={status:'target_met',goal_certified:true};let downloads=0;
  const hub=await new AgentHub({directory,transport:async()=>task,adapter:{async *stream(){throw Error('DECISION_MODEL_BUDGET');}}}).init();
  const {id}=await hub.create(),s=hub.session(id);s.job={status:'completed',request:{operation:'decision_execute'}};
  hub.execute=async(_s,call)=>{assert.equal(call.name,'mp_task_download');downloads++;return {download_verified:true,deliverables:{}};};
  await hub.loop(s,new AbortController().signal);
  assert.equal(downloads,1);assert.equal(s.status.phase,'completed');assert.ok(s.events.some(e=>e.type==='host_delivery_completed'&&!e.model_called&&!e.native_stage_started));
});

test('delivery never hides an unfinished job, repair job, or hash failure',async()=>{
  const task={status:'target_met',goal_certified:true},job={status:'completed',request:{operation:'decision_execute'}};
  assert.equal(canDeliverCompletedTask({...task,goal_certified:false},job),false);
  assert.equal(canDeliverCompletedTask({...task,download_verified:true},job),false);
  assert.equal(canDeliverCompletedTask(task,{...job,status:'running'}),false);
  assert.equal(canDeliverCompletedTask(task,{...job,request:{operation:'local_execute'}}),false);
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'host-delivery-fail-')),hub=await new AgentHub({directory}).init();
  const {id}=await hub.create(),s=hub.session(id);s.job=job;hub.execute=async()=>({download_verified:false});
  await assert.rejects(()=>hub.deliverCompletedTask(s,task,new AbortController().signal),/完整性/);
  assert.equal(s.events.some(e=>e.type==='host_delivery_completed'),false);
});
test('durable job polling resumes inference only after terminal state; one submission',async()=>{
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'silicon-loop-'));let inference=0,polls=0,submissions=0;
  const adapter={async *stream(options){inference++;assert.equal(options.model,'gpt-6-astra');assert.equal(options.reasoningEffort,'high');if(inference===2){const evidence=options.messages.flatMap(m=>m.content||[]).find(b=>b.text?.startsWith('HOST_PERSISTENT_JOB='));assert.ok(evidence,'terminal job result must reach next inference');assert.ok(evidence.text.includes('"status":"completed"'));}yield {type:'block-end',block:inference===1?{type:'tool-call',id:'run-1',name:'mp_task_run',arguments:'{}'}:{type:'text',text:'真实工具结果已读取'}};}};
  const hub=await new AgentHub({directory,adapter,pollMs:1,transport:async req=>{if(req.operation==='context')return null;assert.equal(req.operation,'job_status');assert.equal(inference,1);polls++;return {job:{job_id:'persistent-1',status:polls<2?'running':'completed'},task:{state_id:'state-'+polls,phase:'placement',pending:{action:'placement'}}};}}).init();
  hub.execute=async(s)=>{submissions++;s.job={job_id:'persistent-1',status:'queued'};return {job:s.job};};
  const {id}=await hub.create();await hub.submit(id,{text:'执行一次完整流程'});
  for(let i=0;i<100&&hub.session(id).busy;i++)await delay(5);
  assert.equal(submissions,1);assert.equal(polls,2);assert.equal(inference,2);assert.equal(hub.session(id).status.phase,'completed');
  await hub.writes.get(id);const reloaded=await new AgentHub({directory}).init();assert.equal(reloaded.session(id).job.job_id,'persistent-1');assert.equal(reloaded.session(id).messages.filter(m=>m.role==='tool').length,1);
});
test('API session cannot select another session attachment or read arbitrary artifact paths',async()=>{
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'silicon-http-')),hub=new AgentHub({directory});const server=createServer({hub});await new Promise(r=>server.listen(0,'127.0.0.1',r));const base='http://127.0.0.1:'+server.address().port;
  const post=(url,b)=>fetch(base+url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
  try{const one=await (await post('/api/sessions',{})).json(),two=await (await post('/api/sessions',{})).json();const ref=await hub.addUpload(one.id,'design.json',Buffer.from('{}'));
    const bad=await post('/api/sessions/'+two.id+'/turn',{text:'start',attachments:[ref.attachmentId]});assert.equal(bad.status,400);
    assert.equal((await fetch(base+'/api/sessions/'+one.id+'/artifacts/accounts.dpapi')).status,400);
    assert.equal((await fetch(base+'/api/providers/api',{method:'POST',headers:{'Content-Type':'application/json',Origin:'https://foreign.test'},body:'{}'})).status,403);
    assert.equal((await fetch(base+'/api/providers/login',{method:'POST',headers:{'Content-Type':'text/plain'},body:'{}'})).status,400);
    await assert.rejects(()=>hub.addUpload(one.id,'../design.json',Buffer.from('x')));
  }finally{await new Promise(r=>server.close(r));}
});

test('planning guard returns to inference and skips the remaining stale action batch',async()=>{
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'silicon-replan-'));let inference=0;const executed=[];
  const adapter={async *stream(options){
    inference++;
    if(inference===1){
      yield {type:'block-end',block:{type:'tool-call',id:'blocked',name:'mp_task_act',arguments:'{}'}};
      yield {type:'block-end',block:{type:'tool-call',id:'stale',name:'mp_task_run',arguments:'{}'}};
    }else if(inference===2){
      const answers=options.messages.filter(m=>m.role==='tool');
      assert.equal(answers.length,2);
      for(const answer of answers)assert.equal(JSON.parse(answer.content[0].text).execution_uncertain,false);
      assert.match(answers[0].content[0].text,/MAIN_DECISION_REQUIRED/);
      assert.match(answers[1].content[0].text,/NOT_EXECUTED_REPLAN_REQUIRED/);
      yield {type:'block-end',block:{type:'tool-call',id:'planned',name:'mp_task_execute_plan',arguments:'{}'}};
    }else yield {type:'block-end',block:{type:'text',text:'已读取重新规划后的执行结果'}};
  }};
  const hub=await new AgentHub({directory,adapter,transport:async()=>null}).init();
  hub.execute=async(_s,call)=>{executed.push(call.name);if(call.id==='blocked')throw Error('host bridge: MAIN_DECISION_REQUIRED: inspect, discover and submit an evidence-backed plan; ');return {passed:true};};
  const {id}=await hub.create();await hub.loop(hub.session(id),new AbortController().signal);
  assert.deepEqual(executed,['mp_task_act','mp_task_execute_plan']);
  assert.equal(inference,3);assert.equal(hub.session(id).status.phase,'completed');
  assert.ok(hub.session(id).events.some(e=>e.type==='planning_guard_recovery'&&!e.native_started));
});

test('permission and uncertain execution failures never enter the planning recovery path',async()=>{
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'silicon-no-blind-retry-'));let inference=0;
  const hub=await new AgentHub({directory,transport:async()=>null,adapter:{async *stream(){inference++;yield {type:'block-end',block:{type:'tool-call',id:'unknown',name:'mp_task_run',arguments:'{}'}};}}}).init();
  hub.execute=async()=>{throw Error('host bridge: PermissionError: [WinError 5]');};
  const {id}=await hub.create();await assert.rejects(()=>hub.loop(hub.session(id),new AbortController().signal),/PermissionError/);
  assert.equal(inference,1);assert.equal(JSON.parse(hub.session(id).messages.at(-1).content[0].text).execution_uncertain,true);
});

test('server package selection validates origin and pins the start case',async()=>{
  const selected='swerv_nangate45',text='使用服务器输入';
  assert.equal(validateTurn({text,serverCase:selected}).serverCase,selected);
  assert.throws(()=>validateTurn({text,serverCase:'../unknown'}));
  assert.throws(()=>validateTurn({text,serverCase:selected,attachments:['sha256:other']}));
  const hub=new AgentHub(),s={inputPackage:selected,events:[],messages:[{role:'user',content:[{type:'file',attachment:{name:'old.v'}}]}]};
  assert.deepEqual(hub.agent(s).session.deriveMessages()[0].content,[]);
  await assert.rejects(hub.execute(s,{name:'mp_task_start',id:'case-test',arguments:JSON.stringify({case_id:'aes_legacy',goal:'full_backend'})},new AbortController().signal),/匹配所选服务器输入包/);
  await assert.rejects(hub.execute(s,{name:'mp_task_start',id:'goal-test',arguments:JSON.stringify({case_id:selected,goal:'placement_def'})},new AbortController().signal),/执行完整后端/);
});

test('unqualified or offline server cases cannot enter the agent loop',async()=>{
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'silicon-case-admission-'));
  let calls=0;
  const hub=await new AgentHub({directory,caseStatus:async()=>({online:true,runnable_cases:[]}),
    adapter:{async *stream(){calls++;yield {type:'block-end',block:{type:'text',text:'done'}};}}}).init();
  const {id}=await hub.create();
  await assert.rejects(()=>hub.submit(id,{text:'执行完整后端',serverCase:'swerv_nangate45'}),/完整后端验收/);
  assert.equal(calls,0);assert.equal(hub.session(id).messages.length,0);assert.equal(hub.active.size,0);
  hub.caseStatus=async()=>({online:true,runnable_cases:['bp_quad']});
  await assert.rejects(()=>hub.submit(id,{text:'执行完整后端',serverCase:'bp_quad'}),/完整后端验收/);
  assert.equal(calls,0);
  hub.caseStatus=async()=>({online:false,runnable_cases:['swerv_nangate45']});
  await assert.rejects(()=>hub.submit(id,{text:'执行完整后端',serverCase:'swerv_nangate45'}),/完整后端验收/);
  assert.equal(calls,0);
});

test('custom input check uses the uploaded manifest and lists missing macro models',async()=>{
  const {inspectUploadPackage}=await import('../upload-check.mjs');
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'silicon-input-check-'));
  const hub=await new AgentHub({directory}).init(),s=await hub.create();
  const manifest={top:'chip',netlist:'src/custom.v',tech_lef:'tech.tlef',cell_lefs:['cells.lef','ram.lef'],libs:['cells.lib','ram.lib'],sdc:'chip.sdc'};
  const inputs={'manifest.json':JSON.stringify(manifest),'design.json':'{"top":"chip"}','custom.v':'module chip; endmodule','tech.tlef':'test','cells.lef':'test','cells.lib':'test','chip.sdc':'test'};
  for(const [name,data] of Object.entries(inputs))await hub.addUpload(s.id,name,Buffer.from(data));
  const check=()=>inspectUploadPackage(hub.session(s.id).uploads);
  assert.deepEqual((await check()).problems,['cell_lefs 缺少或为空：ram.lef','libs 缺少或为空：ram.lib']);
  await hub.addUpload(s.id,'ram.lef',Buffer.from('macro geometry'));
  await hub.addUpload(s.id,'ram.lib',Buffer.from('macro timing'));
  assert.deepEqual((await check()).problems,[]);
});

test('a failed inference preserves the checkpoint, exposes a paused session and resumes without dispatching partial calls',async()=>{
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'silicon-inference-resume-'));
  let attempts=0,dispatches=0,started,unblock;
  const during=new Promise(resolve=>{started=resolve;});
  const release=new Promise(resolve=>{unblock=resolve;});
  const controller=new AbortController();
  const adapter={async *stream(options){
    attempts++;
    if(attempts===1){
      started();await release;
      assert.ok(!options.tools.some(t=>['mp_task_run','mp_task_act'].includes(t.name)));
      yield {type:'block-end',block:{type:'tool-call',id:'partial',name:'mp_task_execute_plan',arguments:'{}'}};
      throw Object.assign(Error('injected network failure'),{code:'network_error'});
    }
    yield {type:'block-end',block:{type:'text',text:'恢复模型连接'}};
  }};
  const checkpoint={state_id:'frozen',contract:{case_id:'tinyram'},plan:[],phase:'validate',main_decision:{decision_required:true}};
  const hub=await new AgentHub({directory,adapter,transport:async()=>checkpoint}).init();
  hub.execute=async()=>{dispatches++;throw Error('partial call dispatched');};
  const {id}=await hub.create();
  await hub.submit(id,{text:'继续已保存的任务'});await during;
  assert.equal(hub.view(hub.session(id)).activeAgentSessions,1);
  assert.equal(hub.session(id).job,null);
  unblock();
  for(let i=0;i<200&&hub.session(id).busy;i++)await delay(5);
  assert.equal(hub.session(id).status.phase,'model_paused');
  assert.equal(hub.view(hub.session(id)).activeAgentSessions,0);
  assert.equal(dispatches,0);
  await hub.writes.get(id);
  const reopened=await new AgentHub({directory,adapter,transport:async()=>checkpoint}).init();
  assert.equal(reopened.session(id).task.state_id,'frozen');
  await reopened.loop(reopened.session(id),controller.signal);
  assert.equal(attempts,2);assert.equal(dispatches,0);
});

test('decision checkpoint reads the summary and matching catalog once; a changed state cannot supply a plan',async()=>{
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'silicon-decision-brief-'));
  const reads=[];let mismatch=false;
  const hub=await new AgentHub({directory,transport:async q=>{
    reads.push(q.operation);
    if(q.operation==='decision_inspect')return {state_id:'state',decision_state_id:'after',evidence_id:'observation'};
    assert.equal(q.operation,'decision_catalog');return {state_id:mismatch?'other':'state',decision_state_id:'after',tools:[]};
  }}).init();
  const {id}=await hub.create(),s=hub.session(id),signal=new AbortController().signal;
  s.inputPackage='tinyram';
  const t={contract:{goal:'full_backend'},state_id:'state',status:'running',main_decision:{decision_required:true,decision_state_id:'before'}};
  const result=await hub.decisionBrief(s,t,signal);
  assert.equal(result.facts.evidence_id,'observation');t.main_decision.decision_state_id='after';
  assert.equal(await hub.decisionBrief(s,t,signal),result);assert.deepEqual(reads,['decision_inspect','decision_catalog']);
  mismatch=true;t.main_decision.decision_state_id='different';
  assert.equal(await hub.decisionBrief(s,t,signal),null);
  assert.equal(s.events.filter(e=>e.type==='decision_brief').length,1);
  assert.ok(canDeliverCompletedTask({status:'target_met',goal_certified:true},{status:'completed',request:{operation:'run'}}));
  assert.ok(!canDeliverCompletedTask({status:'target_met',goal_certified:true},{status:'completed',request:{operation:'act',action:'routing'}}));
});
