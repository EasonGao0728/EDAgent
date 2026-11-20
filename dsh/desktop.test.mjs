import test from 'node:test';
import assert from 'node:assert/strict';
import {pkg} from './runtime.mjs';
import * as desktop from './desktop-tools.mjs';
import {taskToolNames,taskRun} from './main-task-tools.mjs';
import {BOOTSTRAP,loadTools} from './tool-library.mjs';
import * as provider from './desktop-provider.mjs';
const {Context}=await pkg('cordis');
const {createScope,bindScopeParent}=await pkg('dsh-scope');
const {default:Tools,defineTool}=await pkg('dsh-tools');
const {default:SystemPrompt}=await pkg('dsh-system-prompt');
const {default:Llm}=await pkg('dsh-llm');
test('desktop preset isolates capabilities; real fixed tools execute without LLM',async()=>{
  const ctx=new Context();
  const fibers=[ctx.plugin(Tools),ctx.plugin(SystemPrompt),ctx.plugin(Llm)];
  for(const name of ['dsh-session','dsh-session-projection']){const {default:Plugin}=await pkg(name);fibers.push(ctx.plugin(Plugin));}
  await new Promise(r=>setTimeout(r,30));
  ctx.tools.register(defineTool({name:'unrelated_shell',description:'test global tool',parameters:{},output:{schema:{type:'json'},render:()=>[]},execute:async()=>({})}));
  let scope;
  const agent={session:{id:'offline-desktop-test-'+Date.now()}};
  fibers.push(ctx.plugin({name:'test-scope-owner',inject:['tools','systemPrompt'],apply(injected){scope=createScope(injected,agent);}}));
  await new Promise(r=>setTimeout(r,30));
  fibers.push(scope.ctx.plugin(desktop),ctx.plugin(provider));
  try{
    await new Promise(r=>setTimeout(r,30));
    assert.deepEqual(scope.ctx.tools.schemas(agent).map(t=>t.name).sort(),[...taskToolNames,'mp_catalog','mp_connectivity','mp_finish','mp_ieda_run','mp_ieda_status','mp_optimize','mp_oss_optimize','mp_query','mp_retrieve','mp_start'].sort());
    const resumeTool=scope.ctx.tools.schemas(agent).find(t=>t.name==='mp_task_resume');
    assert.ok(resumeTool,'Checkpoint resume must be exposed in the desktop preset');
    assert.deepEqual(ctx.tools.schemas().map(t=>t.name),['unrelated_shell']);
    const descendant={};const unbind=bindScopeParent(descendant,agent);
    assert.deepEqual(ctx.tools.schemas(descendant).map(t=>t.name).sort(),[...taskToolNames,'mp_catalog','mp_connectivity','mp_finish','mp_ieda_run','mp_ieda_status','mp_optimize','mp_oss_optimize','mp_query','mp_retrieve','mp_start'].sort());
    unbind.rebind(undefined);
    ctx.tools.register(defineTool({name:'late_global_tool',description:'late desktop registration',parameters:{},output:{schema:{type:'json'},render:()=>[]},execute:async()=>({})}));
    const denied=await scope.ctx.tools.execute({name:'late_global_tool',arguments:{},callId:'late',agent,signal:new AbortController().signal});
    assert.ok(denied.isError);
    const model=await ctx.llm.resolveModelInfo('aieda-chatgpt-desktop','gpt-6.1-sol');
    assert.equal(model.id,'gpt-6.1-sol');
    assert.equal(model.reasoning.defaultEffort,'xhigh');
    assert.ok(model.reasoning.efforts.some(e=>e.id==='medium'));
    let n=0;
    async function call(name,args){
      const r=await scope.ctx.tools.execute({name,arguments:args,callId:'offline-'+(++n),agent,signal:new AbortController().signal});
      assert.ok(!r.isError,JSON.stringify(r));return r.value;
    }
    const first=await call('mp_start',{case_id:'connected_groups'});
    const args={state_id:first.state_id,reason:'OFFLINE INTEGRATION TEST',query:'macros',tool_id:'neighbor_v1',offset:0,limit:8};
    const query=await call('mp_query',args);assert.ok(query.items.length);
    const rag=await call('mp_retrieve',{...args,query:'HPWL fixed grid'});assert.ok(rag.hits.length);
    const deniedMaker=await scope.ctx.tools.execute({name:'mp_request_tool',arguments:{state_id:first.state_id,reason:'P1 must disable Maker',target_ids:'a,b',metric:'weighted_macro_center_hpwl'},callId:'maker-disabled',agent,signal:new AbortController().signal});
    assert.ok(deniedMaker.isError);
    const catalog=await call('mp_catalog',args);assert.deepEqual(catalog.generated_tools,[]);
    const result=await call('mp_optimize',args);assert.ok(result.after.weighted_hpwl<=result.before.weighted_hpwl);
    const stale=await scope.ctx.tools.execute({name:'mp_algorithm_step',arguments:{state_id:result.state_id,request_id:'disabled',reason:'P1 forbidden'},callId:'stale-maker',agent,signal:new AbortController().signal});
    assert.ok(stale.isError,JSON.stringify(stale));
    const finish=await call('mp_finish',{...args,state_id:result.state_id});assert.equal(finish.goal_certified,false);
    const task=await call('mp_task_start',{case_id:'sky130_gcd'});
    assert.equal(task.contract.maker_enabled,false);
    assert.ok(task.perception_report?.report?.path,task.perception_report_error);
    assert.ok(task.perception_report?.analysis?.unknowns.length);
    const assembly=await scope.ctx.systemPrompt.assemble({agent,scope:agent});
    assert.deepEqual(assembly.tools.map(t=>t.name).sort(),[...BOOTSTRAP].sort());
    assert.ok(assembly.contexts.some(c=>c.text.includes(task.state_id)));
    const forbidden=await scope.ctx.tools.execute({name:'mp_ieda_run',arguments:{case_id:'sky130_gcd'},callId:'bypass',agent,signal:new AbortController().signal});
    assert.ok(forbidden.isError);
    console.log('OFFLINE fixture, no model call:',first.run);
  }finally{await scope.dispose();for(const f of fibers.reverse())await f.dispose();}
});

test('native DSH loop records tool results and final answer with offline model fixture',async()=>{
  const {LlmAdapter}=await pkg('dsh-llm');
  const ctx=new Context();const fibers=[];
  for(const name of ['dsh-tools','dsh-system-prompt','dsh-llm','dsh-session','dsh-session-projection','dsh-agent','dsh-agent-loop']){
    const {default:Plugin}=await pkg(name);fibers.push(ctx.plugin(Plugin));
  }
  await new Promise(r=>setTimeout(r,50));
  let requests=0;
  class Fixture extends LlmAdapter{
    async resolveModel(provider,id){return {provider,id,name:'OFFLINE TEST FIXTURE'};}
    async *stream(options){
      assert.ok(options.tools.every(t=>t.name.startsWith('mp_')));
      assert.ok(!options.tools.some(t=>['mp_algorithm_step','mp_request_tool','mp_run_generated'].includes(t.name)));
      const n=++requests;let block;
      if(n===1){assert.deepEqual(options.tools.map(t=>t.name).sort(),[...BOOTSTRAP].sort());block={type:'tool-call',id:'loop-load',name:'mp_tools_load',arguments:JSON.stringify({ids:['teaching-toy']})};}
      else if(n===2){assert.ok(options.tools.some(t=>t.name==='mp_start'));block={type:'tool-call',id:'loop-start',name:'mp_start',arguments:JSON.stringify({case_id:'connected_groups'})};}
      else if(n===3){
        const m=options.messages.findLast(m=>m.role==='tool');assert.equal(m.isError,false);
        const state=JSON.parse(m.content[0].text);
        block={type:'tool-call',id:'loop-finish',name:'mp_finish',arguments:JSON.stringify({state_id:state.state_id,reason:'OFFLINE LOOP TEST',query:'',tool_id:'',offset:0,limit:1})};
      }else{assert.equal(n,4);assert.equal(options.messages.findLast(m=>m.role==='tool').isError,false);block={type:'text',text:'OFFLINE native loop verified'};}
      yield {type:'block-start',index:0,blockType:block.type};yield {type:'block-end',index:0,block};yield {type:'finish',reason:{kind:n<4?'tool-calls':'stop'}};
    }
  }
  ctx.llm.registerAdapter(['offline-native-test'],new Fixture());
  let handle;
  try{
    handle=await ctx.agents.create({sessionId:'offline-loop-'+Date.now(),agentOptions:{provider:'offline-native-test',model:'fixture'},setup(c){desktop.apply(c);}});
    ctx.tools.register(defineTool({name:'late_desktop_dependency',description:'late registration',parameters:{},output:{schema:{type:'json'},render:()=>[]},execute:async()=>({})}));
    handle.agent.followup({content:[{type:'text',text:'OFFLINE fixture check'}],source:{kind:'user'}});
    await handle.agent.whenIdle();
    assert.equal(requests,4);
    const messages=handle.agent.session.deriveMessages();
    assert.equal(messages.filter(m=>m.role==='tool').length,3);
    assert.equal(messages.at(-1).content[0].text,'OFFLINE native loop verified');
  }finally{await handle?.dispose();for(const f of fibers.reverse())await f.dispose();}
});


