import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pkg,root} from './runtime.mjs';
import {desktopBridge as bridge} from './auth-recovery.mjs';
import {quotaGuard} from './main-plugin.mjs';
import {turnKey,turnRequestCount,turnRequestLimit} from './request-budget.mjs';
import {modelWithRecovery} from './model-recovery.mjs';
import {compactMessages,taskContext} from './context-manager.mjs';
import {guardFinal} from './final-consistency.mjs';
const {LlmAdapter}=await pkg('dsh-llm');
export const name='aieda-desktop-openai';
export const inject=['llm'];
export function apply(ctx){
  class Adapter extends LlmAdapter {
    providerInfo(id){return {id,name:'aiEDA · OpenAI 订阅'};}
    async listModels(provider){
      const models=await bridge({mode:'models'});
      return models.filter(m=>/^gpt-6/.test(m.slug)).map(m=>({provider,id:m.slug,name:m.display_name}));
    }
    async resolveModel(provider,model){
      if(!/^gpt-6[\w.-]*$/.test(model))throw Error('unsupported model; select a model from the account catalog');
      return {provider,id:model,name:model,inputModalities:['text'],
        reasoning:{efforts:['low','medium','high','xhigh','max'].map(id=>({id,name:id==='xhigh'?'Extra high':id})),defaultEffort:'xhigh'}};
    }
    async *stream(options){
      if(!options.tools?.length||options.tools.some(t=>!t.name.startsWith('mp_')))
        throw Error('布局工具列表不符合预设：'+JSON.stringify(options.tools?.map(t=>t.name)||[]));
      const id=createHash('sha256').update(options.messages.find(m=>m.role==='user')?.id||JSON.stringify(options.messages[0])).digest('hex').slice(0,16);
      const log=path.join(root,'runs',`dsh-desktop-model-${id}.jsonl`);
      // Preserve failed assembly inputs too, so a recovery never refers to a
      // historical snapshot that was omitted from the request-only archive.
      await fs.appendFile(log,JSON.stringify({event:'assembly_input',turn_key:turnKey(options.messages),messages:options.messages})+'\n');
      const assembled=compactMessages(options.messages,log);
      const task=taskContext(options.messages);
      const effort=options.reasoningEffort||'xhigh';
      let currentQuota=null;
      const r=await modelWithRecovery({signal:options.signal,beforeAttempt:async attempt=>{
        currentQuota=await quotaGuard(path.join(root,'.cache/dsh-quota.json'));
        const history=await fs.readFile(log,'utf8').catch(e=>{if(e.code==='ENOENT')return '';throw e;});
        const requestLimit=turnRequestLimit(task);
        if(turnRequestCount(history,options.messages)>=requestLimit)throw Error(`MODEL_BUDGET: 本轮达到 ${requestLimit} 次模型请求限制，检查点已保留。`);
        if(task)await bridge({mode:'task',operation:'reserve_model',run:task.run},options.signal);
        await fs.appendFile(log,JSON.stringify({event:'request',attempt,turn_key:turnKey(options.messages),model:options.model,reasoning_effort:effort,messages:options.messages,assembled_messages:assembled.messages,compaction:assembled.summary||null,tools:options.tools})+'\n');
      },invoke:()=>bridge({mode:'native_model',model:options.model,reasoning_effort:effort,messages:[...assembled.messages,{role:'system',content:[{type:'text',text:'HOST_QUOTA_STATUS='+JSON.stringify({availability:currentQuota.availability,remainingPercent:currentQuota.remainingPercent,checkedAt:currentQuota.checkedAt,stopBelowPercent:currentQuota.stopBelowPercent,budgetCheckEnforced:currentQuota.budgetCheckEnforced,providerAuthorizationRequired:true,note:currentQuota.note})}]}],tools:options.tools},options.signal)});
      await fs.appendFile(log+'.responses',JSON.stringify(r)+'\n');
      // Workbench guards both providers at its publication boundary; native
      // DSH guards here before any final text is yielded to its conversation.
      if(!options.hostFinalGuard&&task?.run&&!r.blocks.some(b=>b.type==='tool-call')){
        const checked=await guardFinal(task.run,task,r.blocks);
        await fs.appendFile(log+'.final-checks',JSON.stringify(checked.check)+'\n');
        r.blocks=checked.blocks;
      }
      for(let i=0;i<r.blocks.length;i++){
        yield {type:'block-start',index:i,blockType:r.blocks[i].type};
        yield {type:'block-end',index:i,block:r.blocks[i]};
      }
      yield {type:'finish',reason:{kind:r.blocks.some(b=>b.type==='tool-call')?'tool-calls':'stop'}};
    }
  }
  ctx.llm.registerAdapter(['aieda-chatgpt-desktop'],new Adapter());
}
