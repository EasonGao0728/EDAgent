import {packages,auditCase} from './remote-status.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID,createHash} from 'node:crypto';
import {setTimeout as delay} from 'node:timers/promises';
import {root,bridge,pkg} from '../dsh/runtime.mjs';
import {apply as registerDesktop} from '../dsh/desktop-tools.mjs';
import {apply as registerProvider} from '../dsh/desktop-provider.mjs';
import {taskRun,taskToolNames} from '../dsh/main-task-tools.mjs';
import {TASK_MARKER,compactMessages} from '../dsh/context-manager.mjs';
import {turnKey,turnRequestCount,turnRequestLimit} from '../dsh/request-budget.mjs';
import {apiBridge} from './provider.mjs';
import {visibleToolNames} from '../dsh/tool-library.mjs';
import {assembleDecisionContext} from '../dsh/decision-context.mjs';
import {guardFinal} from '../dsh/final-consistency.mjs';

const {validateJsonSchemaValue}=await pkg('dsh-tools');
export const DEFAULT_MODEL='gpt-6-astra';
export const DEFAULT_EFFORT='high';
export const sessionRoot=path.join(root,'runs','silicon-sessions');
const terminal=new Set(['completed','failed','cancelled','lost']);
const textBlock=text=>({type:'text',text});
const definitions=new Map(),hooks=new Map(),guards=[];
let systemPrompt='',subscription;
// Bind the existing DSH capability plugin to a small web session adapter.
// Definitions, guards, prompt, attachments and native actions stay in DSH.
const ctx={tools:{schemas:()=>[],restrict(){},guard:g=>guards.push(g),register:t=>definitions.set(t.name,t)},
  systemPrompt:{section:s=>{systemPrompt+=s.text+'\n';}},on:(event,fn)=>hooks.set(event,fn),
  get:()=>({fileHostPath:ref=>ref.hostPath}),
  sessionProjections:{stateOf:()=>({openTurnStartSeq:0,lastTurn:0})}};
registerDesktop(ctx);
registerProvider({llm:{registerAdapter:(_names,adapter)=>{subscription=adapter;}}});

export function validateTurn(body){
  if(!body||typeof body.text!=='string'||!body.text.trim()||body.text.length>16000)throw Error('请输入 1–16000 字的任务描述');
  if(!['subscription','api'].includes(body.provider||'subscription'))throw Error('无效模型连接');
  const model=body.model||DEFAULT_MODEL;
  if(!/^[\w./:-]{1,100}$/.test(model))throw Error('无效模型名称');
  const effort=body.effort||DEFAULT_EFFORT;
  if(!['low','medium','high','xhigh','max','none'].includes(effort))throw Error('无效推理强度');
  if((body.provider||'subscription')==='subscription'&&(!/^gpt-6[\w.-]*$/.test(model)||effort==='none'))throw Error('请选择订阅目录内的 GPT-6 模型及支持的推理强度');
  if(!Array.isArray(body.attachments||[])||(body.attachments||[]).length>16)throw Error('附件数量超限');
  if(typeof (body.context||'')!=='string'||(body.context||'').length>20000)throw Error('上下文超限');
  const serverCase=body.serverCase||null;
  if(serverCase && (!packages.some(p=>p.id===serverCase) || body.attachments?.length))throw Error('请选择一个登记案例或一组本地文件');
  return {serverCase,text:body.text.trim(),model,effort,provider:body.provider||'subscription',attachments:body.attachments||[],context:body.context||''};
}
export function closeUnfinishedCalls(messages){
  const answered=new Set(messages.filter(m=>m.role==='tool').map(m=>m.toolCallId));
  // Insert missing replies immediately after the corresponding assistant turn.
  // These are uncertainty records, never claims that an action was executed.
  for(let i=messages.length-1;i>=0;i--){const m=messages[i];if(m.role!=='assistant')continue;
    const missing=m.content.filter(b=>b.type==='tool-call'&&!answered.has(b.id));
    if(missing.length)messages.splice(i+1,0,...missing.map(b=>({id:randomUUID(),role:'tool',name:b.name,toolCallId:b.id,content:[textBlock(JSON.stringify({error:'INTERRUPTED_OR_UNCERTAIN',note:'前次进程中断，未确认执行结果。先查询同一任务状态，不得自动重新提交动作。'}))]})));
  }
}
export function dispatchIdentity(events,call,args){
  if(!['mp_task_run','mp_task_act'].includes(call.name))return {id:call.id,args};
  const prior=events.findLast(e=>e.type==='tool_start'&&e.name===call.name&&e.args.state_id===args.state_id&&e.args.action===args.action);
  // A model may propose a new call ID after a lost SSH reply. Preserve the exact
  // first request and idempotency key, including reason, so the server can replay.
  return prior?{id:prior.executionId||prior.callId,args:prior.args}:{id:call.id,args};
}

export function canDeliverCompletedTask(task,job){
  // Only a completed main-task finish can trigger automatic delivery. A
  // quality/repair job on an already completed parent still needs its review.
  return task?.goal_certified===true&&task.status==='target_met'&&!task.download_verified
    &&job?.status==='completed'&&job.request?.operation==='decision_execute';
}

export class AgentHub{
  constructor({directory=sessionRoot,transport=bridge,adapter=subscription,pollMs=15000}={}){this.directory=directory;this.transport=transport;this.adapter=adapter;this.pollMs=pollMs;this.sessions=new Map();this.active=new Map();this.writes=new Map();}
  async init(){await fs.mkdir(this.directory,{recursive:true});for(const name of await fs.readdir(this.directory)){
    if(!/^silicon-[a-f0-9-]+\.json$/.test(name))continue;
    const s=JSON.parse(await fs.readFile(path.join(this.directory,name),'utf8'));
    if(s.busy){s.busy=false;s.status={phase:'interrupted',title:'工作台服务已重启',detail:'检查点已保留。可查询持久作业，再发送消息继续；不会自动重新提交。',at:Date.now()};}
    this.sessions.set(s.id,s);
  }return this;}
  session(id){const s=this.sessions.get(id);if(!s)throw Error('会话不存在');return s;}
  async create(){const s={id:'silicon-'+randomUUID(),title:'新设计会话',created:Date.now(),updated:Date.now(),revision:0,messages:[],events:[],uploads:[],task:null,job:null,artifacts:[],busy:false,model:DEFAULT_MODEL,effort:DEFAULT_EFFORT,provider:'subscription',status:{phase:'idle',title:'准备就绪',detail:'描述你的设计目标，或添加登记案例的输入文件。',at:Date.now()}};this.sessions.set(s.id,s);await this.save(s);return this.view(s);}
  save(s){s.updated=Date.now();s.revision++;const json=JSON.stringify(s,null,2);const target=path.join(this.directory,s.id+'.json');const next=(this.writes.get(s.id)||Promise.resolve()).then(async()=>{await fs.writeFile(target+'.tmp',json);for(let attempt=0;;attempt++){try{await fs.rename(target+'.tmp',target);break;}catch(e){if(!['EPERM','EACCES','EBUSY'].includes(e.code)||attempt>=6)throw e;await delay(25*(attempt+1));}}});this.writes.set(s.id,next.catch(()=>{}));return next;}
  view(s){return {...s,messages:s.messages.filter(m=>['user','assistant'].includes(m.role)).map(m=>({id:m.id,role:m.role,text:m.content.filter(b=>b.type==='text').map(b=>b.text).join('\n'),attachments:m.content.filter(b=>b.type==='file').map(b=>({name:b.attachment.name,bytes:b.attachment.bytes})),model:m.model,effort:m.effort})).filter(m=>m.text||m.attachments.length),uploads:s.uploads.map(({hostPath,...ref})=>ref)};}
  list(){return [...this.sessions.values()].sort((a,b)=>b.created-a.created).map(s=>({id:s.id,title:s.title,busy:s.busy,status:s.status,model:s.model,updated:s.updated}));}
  async event(s,type,data={}){const e={seq:s.events.length+1,at:Date.now(),type,...data};s.events.push(e);await this.save(s);return e;}
  async status(s,phase,title,detail){s.status={phase,title,detail,at:Date.now()};await this.event(s,'status',s.status);}
  agent(s){return {session:{id:s.id,deriveMessages:()=>s.messages.map(m=>m.role==='user'?{...m,content:s.inputPackage?[]:m.content.filter(b=>b.type==='file')}:m),requestHeader:()=>({config:{model:s.model,reasoningEffort:s.effort}}),append:async(type,data)=>this.event(s,type,data)}};}
  async addUpload(id,name,data){const s=this.session(id);if(s.busy)throw Error('运行中不能修改冻结输入');if(!/^[A-Za-z0-9_.-]{1,140}$/.test(name)||name==='.'||name==='..')throw Error('无效文件名');
    const hash=createHash('sha256').update(data).digest('hex'),dir=path.join(this.directory,id,'uploads',hash);await fs.mkdir(dir,{recursive:true});const hostPath=path.join(dir,name);await fs.writeFile(hostPath,data);
    const ref={name,bytes:data.length,attachmentId:'sha256:'+hash,hostPath};s.uploads=s.uploads.filter(f=>f.name!==name);s.uploads.push(ref);await this.save(s);return {name,bytes:data.length,attachmentId:ref.attachmentId};}
  async submit(id,body){const s=this.session(id);if(s.busy)throw Error('本会话仍在运行');if(this.active.size)throw Error('另一个会话正在使用主 Agent，请等待或先停止回复');const turn=validateTurn(body);
    if(turn.serverCase && s.task?.contract?.case_id && s.task.contract.case_id!==turn.serverCase)throw Error('当前会话已绑定其他设计，请新建会话');
    if(turn.serverCase)turn.text+='\n\n服务器输入包：'+turn.serverCase;
    const files=turn.attachments.map(id=>{const f=s.uploads.find(f=>f.attachmentId===id);if(!f)throw Error('附件不属于此会话');return {type:'file',attachment:f};});
    const controller=new AbortController();this.active.set(id,controller);
    closeUnfinishedCalls(s.messages);
    if(turn.serverCase || files.length)s.inputPackage=turn.serverCase;
    Object.assign(s,{model:turn.model,effort:turn.effort,provider:turn.provider,context:turn.context,busy:true});if(!s.messages.length)s.title=turn.text.slice(0,38);
    s.messages.push({id:randomUUID(),role:'user',content:[textBlock(turn.text),...files]});try{await this.save(s);}catch(e){s.busy=false;this.active.delete(id);throw e;}
    const selected=packages.find(p=>p.id===turn.serverCase);
    const operation=selected?.goal==='input_audit'?this.auditInputs(s,selected,controller.signal):this.loop(s,controller.signal);
    operation.catch(async e=>{await this.status(s,controller.signal.aborted?'cancelled':'failed',controller.signal.aborted?'回复已停止':'执行需要处理',controller.signal.aborted?'已保留检查点；远程作业需单独取消。':e.message);}).finally(async()=>{s.busy=false;this.active.delete(id);await this.save(s);});
    return this.view(s);
  }
  async auditInputs(s,p,signal){
    await this.status(s,'acting','正在服务器核验输入',p.id+' · 检查设计清单、网表与 SDC 的 SHA-256');
    const result=await auditCase(p.id,signal);
    await this.event(s,'case_input_audit',{case_id:p.id,result});
    const lines=[
      '### '+p.id+' · 服务器输入核验通过',
      '顶层 `'+result.top+'`，工艺 `'+result.pdk+'`。与当前网表哈希对应的清单统计为 '+p.cells.toLocaleString('en-US')+' 个标准单元、'+p.macros+' 个宏实例。',
      ...Object.entries(p.assets).map(([key,asset])=>'- `'+asset.file+'` · '+asset.bytes.toLocaleString('en-US')+' B · SHA-256 `'+result.hashes[key]+'`'),
      'SDC 中的建钟命令数为 '+result.clocks+'。设计声明的库文件为 '+result.libraries.map(v=>'`'+v+'`').join('、')+'。',
      '本次交付为输入核验。运行布局布线还需登记并验证该工艺的库、约束和执行适配。'
    ];
    s.messages.push({id:randomUUID(),role:'assistant',source:{kind:'case-audit'},content:[textBlock(lines.join('\n\n'))]});
    await this.status(s,'completed','输入核验完成',p.id+' · 3 个服务器文件通过内容校验');
  }
  async execute(s,call,signal){
    const tool=definitions.get(call.name);if(!tool)throw Error('未登记的工具：'+call.name);
    let args=JSON.parse(call.arguments);const violations=validateJsonSchemaValue(tool.parameters,args);
    if(violations.length||Object.keys(args).some(k=>!Object.hasOwn(tool.parameters.properties,k)))throw Error('工具参数校验失败');
    const identity=dispatchIdentity(s.events,call,args);args=identity.args;
    if(call.name==='mp_task_start' && s.inputPackage && args.case_id!==s.inputPackage)throw Error('启动案例必须匹配所选服务器输入包 '+s.inputPackage);
    const exec={name:call.name,arguments:args,callId:identity.id,agent:this.agent(s),signal};
    for(const guard of guards){const denied=guard(exec);if(denied)throw Error(denied);}
    await this.status(s,'acting','正在调用 '+call.name,args.reason||tool.description.slice(0,100));
    await this.event(s,'tool_start',{name:call.name,callId:call.id,executionId:identity.id,args});
    const started=Date.now();
    try{const value=await tool.execute(args,exec);await hooks.get('tools/result')?.(exec,{value,isError:false});
      this.observeValue(s,value);await this.event(s,'tool_end',{name:call.name,callId:call.id,value,durationMs:Date.now()-started});return value;
    }catch(e){await this.event(s,'tool_error',{name:call.name,callId:call.id,error:e.message,durationMs:Date.now()-started});throw e;}
  }
  observeValue(s,value){const task=value?.task||value;if(task?.state_id&&task.contract&&task.plan)s.task=task;if(value?.job)s.job=value.job;if(task?.job)s.job=task.job;
    if(value?.perception_report){for(const ref of [value.perception_report.report,value.perception_report.data]){
      if(ref?.path&&ref.sha256&&path.dirname(path.resolve(ref.path))===path.resolve(taskRun(this.agent(s)))){
        const name=path.basename(ref.path);s.artifacts=s.artifacts.filter(a=>a.name!==name);s.artifacts.push({kind:ref.path.endsWith('.html')?'report':'perception_data',name,sha256:ref.sha256,bytes:ref.bytes,url:`/api/sessions/${s.id}/artifacts/${encodeURIComponent(name)}`});
      }
    }}
    if(task?.download_verified&&task.deliverables){s.artifacts=s.artifacts.filter(a=>/^(input|quality)-perception-/.test(a.name));for(const [kind,ref]of Object.entries(task.deliverables)){const r=kind==='preview'?ref.preview:ref;if(r?.path&&r?.sha256&&path.dirname(path.resolve(r.path))===path.resolve(taskRun(this.agent(s))))s.artifacts.push({kind,name:path.basename(r.path),sha256:r.sha256,bytes:r.bytes,url:`/api/sessions/${s.id}/artifacts/${encodeURIComponent(path.basename(r.path))}`});}}
  }
  async deliverCompletedTask(s,task,signal){
    if(!canDeliverCompletedTask(task,s.job))return false;
    const value=await this.execute(s,{name:'mp_task_download',id:'host-delivery-'+randomUUID(),arguments:'{}'},signal);
    const delivery=value?.task||value;
    if(delivery?.download_verified!==true)throw Error('交付尚未通过文件完整性验证');
    s.messages.push({id:randomUUID(),role:'assistant',source:{kind:'host-delivery'},content:[textBlock('宿主交付完成：服务器已验收当前任务，交付文件已下载并通过 SHA256 校验。流程执行与版图质量分别判定，具体质量结论见验收报告。本次文件交付未额外调用模型。')]});
    await this.event(s,'host_delivery_completed',{download_verified:true,model_called:false,native_stage_started:false});
    await this.status(s,'completed','交付已完成','报告、版图预览和设计文件已下载校验；质量结论见报告。');
    return true;
  }
  async refresh(id){
    const s=this.session(id);if(s.busy)return this.view(s);
    const value=s.job?await this.transport({mode:'task',operation:'job_status',run:taskRun(this.agent(s)),job_id:s.job.job_id}):await this.transport({mode:'task',operation:'context',run:taskRun(this.agent(s))});
    this.observeValue(s,value);await this.event(s,'remote_refresh',{value});
    if(!this.active.size&&canDeliverCompletedTask(value?.task||value,s.job)){
      s.busy=true;
      try{await this.deliverCompletedTask(s,value?.task||value,new AbortController().signal);}
      catch(e){await this.status(s,'failed','交付需要处理',e.message);throw e;}
      finally{s.busy=false;await this.save(s);}
    }
    return this.view(s);
  }
  async monitor(s,signal){let failures=0;while(s.job&&!terminal.has(s.job.status)){
    signal.throwIfAborted();let v;
    try{v=await this.transport({mode:'task',operation:'job_status',run:taskRun(this.agent(s)),job_id:s.job.job_id},signal);failures=0;}
    catch(e){signal.throwIfAborted();if(++failures>=3)throw e;await this.event(s,'job_query_error',{job_id:s.job.job_id,error:e.message});await this.status(s,'waiting','正在重连服务器作业',s.job.job_id+' · 只重试状态查询，不重新提交');await delay(5000,undefined,{signal});continue;}
    this.observeValue(s,v);
    await this.event(s,'job_status',{job:v.job,task:v.task});
    if(terminal.has(s.job.status)){s.messages.push({id:randomUUID(),role:'system',content:[textBlock('宿主持久作业查询结果（没有新增用户指令）：'+JSON.stringify(v))],source:{kind:'runtime-context'}});await this.save(s);break;}
    const pending=s.task?.pending;await this.status(s,'waiting','服务器正在执行 '+(s.job.request?.operation==='quality_execute'?'hold 成本收益审查':s.job.request?.operation==='local_execute'?'局部过孔候选与质量验证':pending?.action||pending?.stage||s.task?.phase||'iEDA'),'job '+s.job.job_id+' · 宿主查询作业进度，不消耗模型轮询');
    await delay(this.pollMs,undefined,{signal});
  }}
  async loop(s,signal){
    if(s.job&&!terminal.has(s.job.status))await this.monitor(s,signal);
    for(let i=0;i<40;i++){
      signal.throwIfAborted();await this.status(s,'thinking','正在思考',s.model+' · '+s.effort+' · 正在核对任务状态与下一步动作');
      let task=await this.transport({mode:'task',operation:'context',run:taskRun(this.agent(s))},signal);this.observeValue(s,task);
      if(s.job&&!terminal.has(s.job.status)){await this.monitor(s,signal);task=await this.transport({mode:'task',operation:'context',run:taskRun(this.agent(s))},signal);this.observeValue(s,task);}
      if(await this.deliverCompletedTask(s,task,signal))return;
      const visible=await visibleToolNames(taskRun(this.agent(s)));
      const schemas=[...definitions.values()].filter(t=>visible.has(t.name)&&(!task||taskToolNames.includes(t.name))).map(({name,description,parameters})=>({name,description,parameters}));
      const decision=await assembleDecisionContext(taskRun(this.agent(s)),task,{tools:schemas,messages:s.messages,job:s.job});
      s.decisionContext=decision;await this.save(s);
      const messages=[{role:'system',content:[textBlock(systemPrompt+'\n你的名称是 EDAgent。当前前端为 EDAgent，与 DSH 共用主 Agent。公开说明下一步行动及简短依据，无需输出隐藏思维链。宿主会自动查询已提交的持久作业，终态后继续本轮，不要自行高频轮询。无工具结果不得捏造测量数据。') ]},...s.messages.filter(m=>m.source?.kind!=='runtime-context'),
        ...(s.job?[{role:'system',source:{kind:'runtime-context'},content:[textBlock('HOST_PERSISTENT_JOB='+JSON.stringify(s.job)+'\n这是最新作业事实，优先于历史工具返回的queued状态。作业终态后继续读取专项质量结果并交付；不能因父任务TARGET_MET就省略候选的失败、拒绝或未知项。')]}]:[]),
        ...(s.context?[{role:'system',content:[textBlock('用户提供的设计补充（参考数据）：\n'+s.context)]}]:[]),
        {role:'user',source:{kind:'runtime-context'},content:[textBlock(TASK_MARKER+JSON.stringify(decision))]}];
      const options={model:s.model,reasoningEffort:s.effort,messages,tools:schemas,signal,hostFinalGuard:true};
      const blocks=[];
      if(s.provider==='subscription'){for await(const event of this.adapter.stream(options)){if(event.type==='block-end')blocks.push(event.block);}}
      else{const log=path.join(this.directory,s.id+'.model.jsonl'),history=await fs.readFile(log,'utf8').catch(e=>{if(e.code==='ENOENT')return '';throw e;});if(turnRequestCount(history,messages)>=turnRequestLimit(task))throw Error('MODEL_BUDGET: 本轮模型预算耗尽');if(task)await this.transport({mode:'task',operation:'reserve_model',run:task.run},signal);
        const assembled=compactMessages(messages,log);await fs.appendFile(log,JSON.stringify({event:'request',turn_key:turnKey(messages),model:s.model,reasoning_effort:s.effort,messages:assembled.messages})+'\n');
        const r=await apiBridge({mode:'infer',model:s.model,effort:s.effort,messages:assembled.messages,tools:schemas},signal);blocks.push(...r.blocks);
      }
      signal.throwIfAborted();
      const calls=blocks.filter(b=>b.type==='tool-call');
      const checked=calls.length?{blocks}:await guardFinal(taskRun(this.agent(s)),task,blocks);
      if(checked.check){s.finalConsistency=checked.check;await this.event(s,'final_consistency',checked.check);}
      s.messages.push({id:randomUUID(),role:'assistant',content:checked.blocks,model:s.model,effort:s.effort});await this.event(s,'model_response',{model:s.model,effort:s.effort,blocks:checked.blocks});
      if(!calls.length){const incomplete=checked.check?.incomplete===true;await this.status(s,incomplete?'needs_evidence':'completed',incomplete?'诊断已展示 · 仍缺证据':'回复已完成',incomplete?'已有诊断保留展示；未完成子目标、缺失回执和局部更正已单列，未宣称全部完成。':s.task?.download_verified?'交付文件已下载并校验 SHA256；质量结论见报告。':'可以继续补充设计要求。');return;}
      for(const call of calls){
        // Persist intent before dispatch; after crash no action is replayed automatically.
        try{const value=await this.execute(s,call,signal);s.messages.push({id:randomUUID(),role:'tool',name:call.name,toolCallId:call.id,content:[textBlock(JSON.stringify(value))]});await this.save(s);
        }catch(e){s.messages.push({id:randomUUID(),role:'tool',name:call.name,toolCallId:call.id,content:[textBlock(JSON.stringify({error:e.message,execution_uncertain:true,note:'保留检查点；查询同一任务，不自动重新提交。'}))]});await this.save(s);throw e;}
        if(s.job&&!terminal.has(s.job.status))await this.monitor(s,signal);
      }
    }throw Error('MODEL_BUDGET: 已达到本轮主循环上限，检查点已保存');
  }
  async stop(id){const s=this.session(id);this.active.get(id)?.abort();return this.view(s);}
  async cancelJob(id){const s=this.session(id);if(!s.job||terminal.has(s.job.status))throw Error('没有可取消的远程作业');this.active.get(id)?.abort();
    const v=await this.transport({mode:'task',operation:'job_cancel',run:taskRun(this.agent(s)),job_id:s.job.job_id,reason:'用户在 EDAgent 工作台明确点击取消远程作业'});this.observeValue(s,v);await this.event(s,'job_cancel',{value:v});return this.view(s);}
  async artifact(id,name){const s=this.session(id),ref=s.artifacts.find(a=>a.name===name);if(!ref)throw Error('未验收的产物');const file=path.join(taskRun(this.agent(s)),ref.name);const data=await fs.readFile(file);if(createHash('sha256').update(data).digest('hex')!==ref.sha256)throw Error('产物 SHA256 校验失败');return {data,ref};}
}
