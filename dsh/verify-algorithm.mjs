// Opt-in REAL MODEL verification using native DSH AgentLoop; never a desktop demo.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {pkg,root} from './runtime.mjs';
import * as desktop from './desktop-tools.mjs';
import * as provider from './desktop-provider.mjs';
import {quotaGuard} from './main-plugin.mjs';
await quotaGuard(path.join(root,'.cache/dsh-quota.json'));
const {Context}=await pkg('cordis');
const {createUserMessage}=await pkg('dsh-llm');
const ctx=new Context(),fibers=[];
for(const name of ['dsh-tools','dsh-system-prompt','dsh-llm','dsh-session','dsh-session-projection','dsh-agent','dsh-agent-loop']){
  const {default:Plugin}=await pkg(name);fibers.push(ctx.plugin(Plugin));
}
fibers.push(ctx.plugin(provider));await new Promise(r=>setTimeout(r,50));
let handle;
try{
  handle=await ctx.agents.create({sessionId:'algorithm-live-'+Date.now(),agentOptions:{provider:'aieda-chatgpt-desktop',model:'gpt-6.1-sol',reasoningEffort:'xhigh'},setup(c){desktop.apply(c);}});
  handle.agent.followup(createUserMessage({source:{kind:'user'},content:[{type:'text',text:'验证 Algorithm Agent：加载 connected_groups 并查询宏单元，目标为 a,b 的局部 HPWL 改善。请委托 Algorithm Agent 生成可复用的候选排序邻域搜索工具，不直接使用固定或 OR-Tools 工具。用 mp_request_tool 提出任务，再逐次 mp_algorithm_step，交付成功后 mp_run_generated 执行一次，然后 mp_finish 并如实汇报。失败时报告原因，不得伪称交付成功。最多一次工具开发请求。'}]}));
  await handle.agent.whenIdle();
  const messages=handle.agent.session.deriveMessages();
  const toolResults=messages.filter(m=>m.role==='tool');
  const values=toolResults.filter(m=>!m.isError).map(m=>{try{return JSON.parse(m.content[0].text);}catch{return {};}});
  const delivered=values.find(v=>v.status==='delivered');
  const applied=values.find(v=>v.source_hash&&v.evaluated!==undefined);
  const diagnostics=handle.agent.session.log.filter(e=>/error|attempt|end/.test(e.type||'')).slice(-6);
  const report={kind:'real_native_algorithm_loop_backend',not_desktop_demo:true,delivered:!!delivered,applied:!!applied,messages,diagnostics};
  await fs.writeFile(path.join(root,'runs/dsh-algorithm-live-verification.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({delivered:!!delivered,applied:!!applied,final:messages.at(-1),diagnostics:delivered?undefined:diagnostics}));
  assert.ok(delivered&&applied,'Algorithm delivery or application failed; inspect persisted report');
}finally{await handle?.dispose();for(const f of fibers.reverse())await f.dispose();}
