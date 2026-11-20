// ARCHIVED pre-core runner; not a supported product entry.
// Dedicated DSH Cordis composition with a domain-specific main-agent loop.
import fs from 'node:fs/promises';
import path from 'node:path';
import {root,bridge,pkg} from './runtime.mjs';
import * as mainPlugin from './main-plugin.mjs';
const {Context}=await pkg('cordis');
const {default:SystemPrompt}=await pkg('dsh-system-prompt');
const {default:Tools}=await pkg('dsh-tools');
const {default:Llm}=await pkg('dsh-llm');
const args=process.argv.slice(2);
const option=(key,fallback)=>{const i=args.indexOf(key);return i<0?fallback:args[i+1];};
const run=path.resolve(option('--run',path.join(root,'runs',`dsh-main-${Date.now()}`)));
const steps=Number(option('--steps','4'));
if(!Number.isInteger(steps)||steps<1||steps>8)throw Error('--steps must be 1..8');
const offline=args.includes('--offline');
const quotaFile=path.join(root,'.cache','dsh-quota.json');
const model=option('--model','gpt-6.1-sol');
const reasoningEffort=option('--reasoning','xhigh');
if(!['low','medium','high','xhigh','max'].includes(reasoningEffort))throw Error('unsupported --reasoning');
if(!offline)await mainPlugin.quotaGuard(quotaFile);
if(!args.includes('--resume'))await bridge({mode:'init',run,case:path.resolve(option('--case','cases/toy/connected_groups.json'))});
const lock=await fs.open(path.join(run,'runner.lock'),'wx');
const ctx=new Context();const fibers=[];
try{
  fibers.push(ctx.plugin(SystemPrompt),ctx.plugin(Tools),ctx.plugin(Llm));
  fibers.push(ctx.plugin(mainPlugin,{run,quotaFile,model,reasoningEffort}));
  await new Promise(r=>setTimeout(r,25));
  if(!ctx.tools||!ctx.llm)throw Error('DSH services not ready');
  await fs.writeFile(path.join(run,'runtime.json'),JSON.stringify({dsh:'0.2.0-rc.2',
    loop:'aieda-domain-main-loop',mode:offline?'offline-fixture':'official-chatgpt-subscription',maker:false},null,2));
  for(let n=0;n<steps;n++){
    let s=await bridge({mode:'state',run});
    if(s.status!=='running')break;
    if(s.counts.actions>=s.contract.max_actions){await bridge({mode:'stop',run,status:'action_budget_exhausted'});break;}
    let pending=s.pending;
    if(!pending){
      // State digest and metrics are queried deterministically, not guessed by LLM.
      // Python owns canonical state hashing; snapshot mode returns exactly that ID.
      const snapshot=await bridge({mode:'snapshot',run});
      const prompt=mainPlugin.context(s,ctx.tools.schemas());
      prompt.state_id=snapshot.state_id;prompt.current_metrics=snapshot.metrics;
      prompt.design_summary=snapshot.summary;
      let action;
      if(offline){
        const sequence=['query_design','retrieve_knowledge','run_fixed_tool','finish'];
        action={tool:sequence[Math.min(s.counts.actions,3)],state_id:snapshot.state_id,reason:'OFFLINE TEST FIXTURE',
          query:s.counts.actions===1?'HPWL fixed grid':'nets',tool_id:s.counts.actions===2?'neighbor_v1':'',offset:0,limit:10};
      }else{
        await mainPlugin.quotaGuard(quotaFile);
        await bridge({mode:'reserve_model',run});
        // Character bound is explicit; not advertised as a measured token count.
        const text=JSON.stringify(prompt);
        if(text.length>24000)throw Error('CONTEXT_BUDGET: bounded prompt exceeds 24000 characters');
        const request={provider:'aieda-chatgpt',model:model||'account-default',messages:[
          {role:'system',content:[{type:'text',text:mainPlugin.system}]},
          {role:'user',content:[{type:'text',text}]}]};
        await fs.appendFile(path.join(run,'model-requests.jsonl'),JSON.stringify(request)+'\n');
        let answer='',finish;
        for await(const chunk of ctx.llm.stream(request)){
          if(chunk.type==='text-delta')answer+=chunk.text;
          if(chunk.type==='finish')finish=chunk.reason;
        }
        if(finish?.kind!=='stop')throw Error(`Model did not complete: ${JSON.stringify(finish)}`);
        action=JSON.parse(answer);
        await fs.appendFile(path.join(run,'model-responses.jsonl'),JSON.stringify(action)+'\n');
      }
      pending={action_id:`action-${s.counts.actions+1}`,action};
      await bridge({mode:'pending',run,pending});
    }
    const {tool,...arguments_}=pending.action;
    const result=await ctx.tools.execute({name:tool,callId:pending.action_id,
      arguments:{...arguments_,action_id:pending.action_id},signal:new AbortController().signal});
    if(result.isError){
      await bridge({mode:'reject_pending',run,error:JSON.stringify(result.content)});
      console.log(JSON.stringify({action:tool,error:result.content}));
      continue;
    }
    console.log(JSON.stringify({action:tool,result:{...result.value,evaluation_records:undefined}}));
  }
  const s=await bridge({mode:'state',run});
  const snapshot=await bridge({mode:'snapshot',run});
  await fs.writeFile(path.join(run,'report.json'),JSON.stringify({status:s.status,counts:s.counts,
    metrics:snapshot.metrics,state_id:snapshot.state_id,maker_calls:0,run,offline},null,2));
  console.log(JSON.stringify({run,status:s.status,counts:s.counts,offline}));
}finally{
  for(const f of fibers.reverse())await f?.dispose?.();
  await lock.close();await fs.unlink(path.join(run,'runner.lock'));
}
