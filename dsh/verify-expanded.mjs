// Real native AgentLoop integration; separate from visible desktop verification.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {pkg,root} from './runtime.mjs';
import * as desktop from './desktop-tools.mjs';
import * as provider from './desktop-provider.mjs';
import * as policy from 'file:///C:/Users/example-user/.dsh/plugins/request-reasoning-policy.mjs';
const {Context}=await pkg('cordis');
const {createUserMessage}=await pkg('dsh-llm');
const ctx=new Context(),fibers=[];
for(const name of ['dsh-tools','dsh-system-prompt','dsh-llm','dsh-session','dsh-session-projection','dsh-agent','dsh-agent-loop']){
  const {default:Plugin}=await pkg(name);fibers.push(ctx.plugin(Plugin));
}
fibers.push(ctx.plugin(provider),ctx.plugin(policy));
await new Promise(r=>setTimeout(r,50));
let handle;
try{
  handle=await ctx.agents.create({sessionId:'expanded-live-'+Date.now(),agentOptions:{provider:'aieda-chatgpt-desktop',model:'gpt-6.1-sol',reasoningEffort:'xhigh'},setup(c){desktop.apply(c);}});
  handle.agent.followup(createUserMessage({content:[{type:'text',text:'进行开源工具接口验收。严格按顺序各调用一次 mp_start(connected_groups)、mp_catalog、mp_connectivity、mp_oss_optimize(tool_id=ortools_cpsat)、mp_finish。不要调用其他工具。最后简要报告实际 HPWL 与 iEDA 的可用性。'}],source:{kind:'user'}}));
  await handle.agent.whenIdle();
  const messages=handle.agent.session.deriveMessages();
  const results=messages.filter(m=>m.role==='tool');
  assert.equal(results.length,5,JSON.stringify(messages.at(-1)));
  assert.ok(results.every(m=>!m.isError));
  const report={kind:'real_native_loop_backend',not_desktop_demo:true,messages};
  await fs.writeFile(path.join(root,'runs/dsh-expanded-live-verification.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(messages.at(-1)));
}finally{await handle?.dispose();for(const f of fibers.reverse())await f.dispose();}
