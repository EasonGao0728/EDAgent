// Two bounded subscription calls: native tool-call and tool-output round trip.
// This is a backend preparation check, not the visible desktop demonstration.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {pkg,root} from './runtime.mjs';
import * as desktop from './desktop-tools.mjs';
import * as provider from './desktop-provider.mjs';
const {Context}=await pkg('cordis');
const {createScope}=await pkg('dsh-scope');
const {default:Tools}=await pkg('dsh-tools');
const {default:SystemPrompt}=await pkg('dsh-system-prompt');
const {default:Llm,BlockAssembler,createSystemMessage,createUserMessage,createAssistantMessage,createToolResultMessage}=await pkg('dsh-llm');
const ctx=new Context();
const effort=process.argv.includes('--medium')?'medium':'xhigh';
const fibers=[ctx.plugin(Tools),ctx.plugin(SystemPrompt),ctx.plugin(Llm),ctx.plugin(provider)];
for(const name of ['dsh-session','dsh-session-projection']){
  const {default:Plugin}=await pkg(name);fibers.push(ctx.plugin(Plugin));
}
await new Promise(r=>setTimeout(r,30));
const id='preflight-'+Date.now(),agent={session:{id}};
let scope;
fibers.push(ctx.plugin({name:'preflight-scope',inject:['tools','systemPrompt'],apply(c){scope=createScope(c,agent);scope.ctx.plugin(desktop);}}));
await new Promise(r=>setTimeout(r,50));
try{
  const tools=scope.ctx.tools.schemas(agent).filter(t=>t.name==='mp_start');
  assert.equal(tools.length,1);
  const messages=[createSystemMessage('这是后台接口连通性检查，不是正式演示。仅调用一次 mp_start 加载 connected_groups。收到工具结果后用一句中文报告返回的 HPWL，然后结束；不再调用工具。'),
    createUserMessage({source:{kind:'user'},content:[{type:'text',text:'开始接口检查。'}]})];
  async function invoke(){
    const assembler=new BlockAssembler();
    for await(const c of ctx.llm.stream({provider:'aieda-chatgpt-desktop',model:'gpt-6.1-sol',reasoningEffort:effort,messages,tools}))assembler.push(c);
    if(!['stop','tool-calls'].includes(assembler.finish.kind))throw Error(JSON.stringify(assembler.finish));
    return assembler.blocks();
  }
  const first=await invoke();
  const calls=first.filter(b=>b.type==='tool-call');assert.equal(calls.length,1);assert.equal(calls[0].name,'mp_start');
  const call=calls[0];
  const result=await scope.ctx.tools.execute({name:call.name,arguments:JSON.parse(call.arguments),callId:call.id,agent,signal:new AbortController().signal});
  assert.ok(!result.isError,JSON.stringify(result));
  messages.push(createAssistantMessage({source:{provider:'aieda-chatgpt-desktop',model:'gpt-6.1-sol'},content:first}),createToolResultMessage({callId:call.id,content:result.content,isError:false}));
  const final=await invoke();assert.ok(final.some(b=>b.type==='text'));assert.ok(!final.some(b=>b.type==='tool-call'));
  const report={kind:'backend_native_protocol_preflight',not_desktop_demo:true,model:'gpt-6.1-sol',reasoning_effort:effort,requests:2,tool:call.name,run:result.value.run,metrics:result.value.metrics,reply:final};
  const outputIndex=process.argv.indexOf('--output');
  const outputFile=path.resolve(root,outputIndex>=0?process.argv[outputIndex+1]:`runs/dsh-desktop-preflight-${effort}.json`);
  if(!outputFile.startsWith(path.join(root,'runs')+path.sep))throw Error('Preflight output must stay in runs');
  await fs.writeFile(outputFile,JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
}finally{await scope?.dispose();for(const f of fibers.reverse())await f.dispose();}
