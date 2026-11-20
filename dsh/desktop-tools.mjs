import fs from 'node:fs/promises';
import {existsSync} from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pkg,root} from './runtime.mjs';
import {desktopBridge as bridge} from './auth-recovery.mjs';
import {registerTaskTools,taskToolNames,taskRun} from './main-task-tools.mjs';
import {TASK_MARKER} from './context-manager.mjs';
import {assembleDecisionContext} from './decision-context.mjs';
import {MAIN_INSTRUCTIONS} from './main-instructions.mjs';
import {visibleToolNames} from './tool-library.mjs';
const {defineTool}=await pkg('dsh-tools');
export const name='aieda-desktop-main-tools';
export const inject=['tools','systemPrompt','sessionProjections'];
export function apply(ctx){
  // Presets mount in an ancestor scope. An empty allow-list would also hide
  // these tools from descendant Agents. Deny only the inherited global names.
  const inherited=ctx.tools.schemas().map(t=>t.name).filter(n=>n!=='run_code');
  if(inherited.length)ctx.tools.restrict({deny:inherited});
  registerTaskTools(ctx);
  // Desktop plugins may register additional global tools after preset loading.
  // Filter the logged model-facing assembly and deny unrelated execution too.
  const allowed=new Set([...taskToolNames,'mp_start','mp_query','mp_retrieve','mp_optimize','mp_finish','mp_catalog','mp_connectivity','mp_oss_optimize','mp_ieda_status']);
  ctx.on('system-prompt/assemble',async (_draft,_context,next)=>{
    const assembly=await next();
    const task=_context.agent ? await bridge({mode:'task',operation:'context',run:taskRun(_context.agent)},_context.signal):null;
    const visible=_context.agent?await visibleToolNames(taskRun(_context.agent)):allowed;
    const tools=assembly.tools.filter(t=>allowed.has(t.name)&&visible.has(t.name)&&(!task||taskToolNames.includes(t.name)));
    const decision=_context.agent?await assembleDecisionContext(taskRun(_context.agent),task,{tools,messages:_context.agent.session.deriveMessages?.()||[]}):null;
    return {...assembly,tools,contexts:decision?[...assembly.contexts,{name:'aieda-task',text:TASK_MARKER+JSON.stringify(decision)}]:assembly.contexts};
  },{prepend:true});
  ctx.tools.guard(exec=>{
    if(!allowed.has(exec.name))return 'Tool outside placement capability scope';
    if(exec.agent?.session?.id && ['task.json','remote-task.json'].some(n=>existsSync(path.join(taskRun(exec.agent),n))) && !taskToolNames.includes(exec.name))
      return 'Stage-one task only permits registered task tools; Maker and legacy bypasses are disabled';
  });
  ctx.systemPrompt.section({name:'aieda-main',order:0,complete:true,interpolate:false,text:MAIN_INSTRUCTIONS});
  const runFor=exec=>{
    const id=exec.agent?.session?.id;
    if(!id)throw Error('DSH session identity missing');
    return path.join(root,'runs','dsh-desktop-'+createHash('sha256').update(id).digest('hex').slice(0,16));
  };
  const queues=new Map();
  const serial=(run,fn)=>{const result=(queues.get(run)||Promise.resolve()).catch(()=>{}).then(fn);queues.set(run,result);return result;};
  const output={schema:{type:'json'},render:(_a,v)=>[{type:'text',text:JSON.stringify(v)}]};
  ctx.tools.register(defineTool({name:'mp_ieda_status',description:'检查服务器固定iEDA二进制与执行配置；不使用本机Docker，不需要教学案例。',parameters:{},output,
    async execute(_args,exec){return bridge({mode:'ieda_status'},exec.signal);}}));
  ctx.tools.register(defineTool({name:'mp_ieda_run',description:'运行固定公开 Sky130 GCD 的 iEDA iFP+iPL 流程，返回真实 DEF、布局报告和日志。无硬宏，不是 toy 优化或完整 PPA 签核。',
    parameters:{case_id:{type:'string',enum:['sky130_gcd'],required:true}},output,
    async execute(args,exec){
      if(args.case_id!=='sky130_gcd')throw Error('Unsupported iEDA fixture');
      const run=path.join(runFor(exec),'ieda-sky130-gcd');
      return serial(run,()=>bridge({mode:'ieda_run',run,case_id:args.case_id},exec.signal));
    }}));
  const routeFor=exec=>{
    const config=exec.agent?.session?.requestHeader?.()?.config;
    return {model:config?.model||'gpt-6.1-sol',reasoning_effort:config?.reasoningEffort||'xhigh'};
  };
  for(const definition of [
    {name:'mp_request_tool',tool:'request_tool',description:'委托独立 Algorithm Agent 开发新工具；不改变布局。target_ids 为逗号分隔的可移动宏ID。reason 写明确的能力缺口。',parameters:{state_id:{type:'string',required:true},reason:{type:'string',required:true},target_ids:{type:'string',required:true},metric:{type:'string',enum:['weighted_macro_center_hpwl'],required:true}}},
    {name:'mp_algorithm_step',tool:'algorithm_step',description:'推进一次建模、代码生成或沙箱测试。读取返回的状态与证据；delivered后再执行工具。',parameters:{state_id:{type:'string',required:true},request_id:{type:'string',required:true},reason:{type:'string',required:true}}},
    {name:'mp_run_generated',tool:'run_generated_tool',description:'执行已经由宿主验证交付的工具；使用当前布局重新评价并接受合法改进。',parameters:{state_id:{type:'string',required:true},tool_id:{type:'string',required:true},reason:{type:'string',required:true}}}
  ]){
    if(!allowed.has(definition.name))continue; // Phase one never registers Maker tools.
    ctx.tools.register(defineTool({name:definition.name,description:definition.description,parameters:definition.parameters,output,
      async execute(args,exec){const run=runFor(exec);return serial(run,async()=>{
        const action={tool:definition.tool,...args};
        if(definition.tool==='request_tool')action.target_ids=args.target_ids.split(',').map(x=>x.trim()).filter(Boolean);
        const result=await bridge({mode:'act',run,action_id:exec.callId,action,route:routeFor(exec)},exec.signal);
        const {evaluation_records,...compact}=result;
        return {...compact,run,full_evaluation_ref:evaluation_records?path.join(run,'checkpoint.json'):null};
      });}}));
  }
  ctx.tools.register(defineTool({name:'mp_start',description:'加载教学宏布局案例，返回当前状态与真实基线指标。',
    parameters:{case_id:{type:'string',enum:['connected_groups','blocked_channel'],required:true}},output,
    async execute(args,exec){const run=runFor(exec);return serial(run,async()=>{
      if(!['connected_groups','blocked_channel'].includes(args.case_id))throw Error('unknown case');
      const existing=await fs.readFile(path.join(run,'checkpoint.json'),'utf8').then(JSON.parse).catch(e=>{if(e.code==='ENOENT')return null;throw e;});
      if(existing&&existing.case.case_id!==args.case_id)throw Error('会话已有不同案例，请新建会话');
      if(!existing)await bridge({mode:'init',run,case:path.join(root,'cases/toy',args.case_id+'.json')},exec.signal);
      return {...await bridge({mode:'snapshot',run},exec.signal),run};
    });}}));
  const definitions=[
    ['mp_catalog','tool_catalog','查看开源工具来源、版本与真实可执行状态。'],
    ['mp_connectivity','analyze_connectivity','用开源 NetworkX 进行网表关联图分析，不修改布局。'],
    ['mp_oss_optimize','run_oss_tool','使用 OR-Tools CP-SAT 求解小型教学布局，tool_id=ortools_cpsat，限时5秒，由宿主独立验证。'],
    ['mp_query','query_design','查询当前布局，query 选 macros 或 nets，offset 从 0 开始、limit 为 1..20。'],
    ['mp_retrieve','retrieve_knowledge','按英文关键词检索工具说明和评价知识，返回来源。'],
    ['mp_optimize','run_fixed_tool','选择 neighbor_v1 单宏邻域或 swap_v1 双宏交换，由宿主检查并接受合法改进。'],
    ['mp_finish','finish','结束本次任务并返回实际测量摘要，不宣称全局最优。']];
  for(const [name,tool,description] of definitions){
    ctx.tools.register(defineTool({name,description,parameters:{
      state_id:{type:'string',required:true},reason:{type:'string',required:true},
      query:{type:'string',required:true},tool_id:{type:'string',required:true},
      offset:{type:'integer',required:true},limit:{type:'integer',required:true}},output,
      async execute(args,exec){const run=runFor(exec);return serial(run,async()=>{
        const r=await bridge({mode:'act',run,action_id:exec.callId,action:{tool,...args}},exec.signal);
        const {evaluation_records,...compact}=r;
        return {...compact,run,full_evaluation_ref:evaluation_records?path.join(run,'checkpoint.json'):null};
      });}}));
  }
}
