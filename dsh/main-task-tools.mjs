import {createHash} from 'node:crypto';
import path from 'node:path';
import fs from 'node:fs/promises';
import {pkg,root} from './runtime.mjs';
import {desktopBridge as bridge} from './auth-recovery.mjs';
import {conversationAttachments} from './task-attachments.mjs';
import {writePerceptionReport} from './perception-report.mjs';
import {searchTools,loadTools,catalog} from './tool-library.mjs';
import {recordReceipt,setSubgoal,reflect} from './decision-context.mjs';
import {correctableToolFailure} from './tool-failure.mjs';
const {defineTool}=await pkg('dsh-tools');
export const taskToolNames=['mp_task_start','mp_task_observe','mp_task_resume','mp_task_act','mp_task_retrieve','mp_task_query','mp_task_discover','mp_task_run','mp_task_job_status','mp_task_job_cancel','mp_task_download','mp_task_open','mp_task_inspect','mp_task_choices','mp_task_plan','mp_task_execute_plan','mp_task_cancel_plan','mp_task_decision_report'];
taskToolNames.push('mp_feedback_begin','mp_feedback_status','mp_feedback_inspect','mp_feedback_branch','mp_feedback_continue','mp_feedback_compare','mp_feedback_report','mp_feedback_stop');
taskToolNames.push('mp_local_inspect','mp_local_plan','mp_local_execute','mp_local_status');
taskToolNames.push('mp_quality_inspect','mp_quality_execute');
taskToolNames.push('mp_tools_search','mp_tools_load','mp_agent_subgoal','mp_agent_reflect');
export function taskRun(agent){
  const id=agent?.session?.id;
  if(!id)throw Error('DSH session identity missing');
  return path.join(root,'runs','dsh-desktop-'+createHash('sha256').update(id).digest('hex').slice(0,16),'main-task');
}
export function registerTaskTools(ctx){
  const pending=new WeakMap();
  const register=tool=>ctx.tools.register({...tool,async execute(args,exec){
    let value;
    try{value=await tool.execute(args,exec);}
    catch(error){
      const observation=correctableToolFailure(tool.name,error,taskToolNames);
      const receipt=await recordReceipt(taskRun(exec.agent),tool.name,args,observation,error.message).catch(()=>null);
      if(observation)return {...observation,decision_receipt_id:receipt?.id||null};
      throw error;
    }
    try{const receipt=await recordReceipt(taskRun(exec.agent),tool.name,args,value);if(value&&typeof value==='object')value.decision_receipt_id=receipt.id;}
    catch(error){if(value&&typeof value==='object')value.memory_write_error=error.message;}
    return value;
  }});
  const output={schema:{type:'json'},render:(_a,v)=>[{type:'text',text:JSON.stringify(v)}]};
  register(defineTool({name:'mp_tools_search',description:'检索工具库；stage只能使用所列枚举，不确定时省略。按阶段过滤、embedding/关键词召回少量候选，自动加载候选定义到下一轮。相似度不是成功率，调用前仍须核对当前任务资格；没有工具时报告缺口，不启动Tool Maker。',parameters:{query:{type:'string',required:true},stage:{type:'string',enum:catalog().stages},top_k:{type:'number'}},output,async execute(args,exec){
    const result=await searchTools(args.query,{stage:args.stage,topK:args.top_k??5});
    if(result.candidates.length)result.loaded=await loadTools(taskRun(exec.agent),result.candidates.map(c=>c.id),'retrieval: '+args.query);
    return result;
  }}));
  register(defineTool({name:'mp_tools_load',description:'按工具卡ID加载最多5个已登记能力的参数定义。只加载不执行，适用于已知卡ID或检索候选不足；缺口/禁用卡不能加载。',parameters:{ids:{type:'array',items:{type:'string'},required:true}},output,execute:(args,exec)=>loadTools(taskRun(exec.agent),args.ids,'explicit selection')}));
  for(const [name,fn,description,parameters] of [
    ['mp_agent_subgoal',setSubgoal,'记录子目标及宿主可检查条件，不执行EDA。evidence_received仅证明收到指定证据，不代表质量通过。对mp_task_inspect/mp_task_query/mp_feedback_inspect必须用evidence_queries列明所需查询，格式tool:kind或tool:kind:stage，可多条；摘要不能替代专项对照。先从工具schema确认kind，不得放宽用户条件。',{
      state_id:{type:'string',required:true},objective:{type:'string',required:true},reason:{type:'string',required:true},completion:{type:'string',enum:['evidence_received','stage_completed','delivery_verified'],required:true},evidence_tools:{type:'array',items:{type:'string'}},evidence_queries:{type:'array',items:{type:'string'}},stage:{type:'string'}}],
    ['mp_agent_reflect',reflect,'记录有宿主工具回执支持的经验假设。evidence_ids使用当前七部分上下文中的receipt ID，不是原生evidence_id；解释保持未验证，不能覆盖事实或跨任务泛化。',{
      state_id:{type:'string',required:true},evidence_ids:{type:'array',items:{type:'string'},required:true},lesson:{type:'string',required:true},next_action:{type:'string',required:true}}]
  ])register(defineTool({name,description,parameters,output,async execute(args,exec){
    if(args.evidence_tools?.some(n=>!taskToolNames.includes(n)))throw Error('UNKNOWN_EVIDENCE_TOOL');
    const run=taskRun(exec.agent),task=await bridge({mode:'task',operation:'context',run},exec.signal);
    return fn(run,task,args);
  }}));
  const defs=[
    ['mp_quality_inspect','quality_inspect','审查已登记SWERV预布线检查点：IO适配后的原生/独立HPWL一致性，hold候选预算及完成后的时序、面积、网络、边际收益。返回evidence_id；不得把成功退出当作质量通过。未测拥塞和DRC为unknown。',{}],
    ['mp_quality_execute','quality_execute','依据当前evidence_id，在服务器复用已验证的DRV检查点执行无hold与5/10/20%上限候选；只做hold、合法化、诊断STA，不重跑布局或布线。持久job完成后再次inspect并download审查报告；review_required表示候选未满足门禁，保留原结果。',{evidence_id:{type:'string',required:true},reason:{type:'string',required:true}}],
    ['mp_local_inspect','local_inspect','诊断已登记AES原版图的真实过孔热点；返回区域、规则、证据及候选预算。只读，不运行布局布线。',{}],
    ['mp_local_plan','local_plan','依据最新热点evidence_id规划一次限定区域的固定PDK过孔模板调整。只创建独立候选计划，不执行。保留原生ECO失败和零替换证据。',{evidence_id:{type:'string',required:true},reason:{type:'string',required:true}}],
    ['mp_local_execute','local_execute','在服务器执行固定适配器的单过孔模板候选，并用原iDRC全芯片复核、接受门禁或拒绝。这不是原生iECO生成；原生旧接口失败和官方零替换已保留。返回持久job_id，禁止重复提交。未知连通性或时序阻止晋升。',{state_id:{type:'string',required:true},plan_id:{type:'string',required:true}}],
    ['mp_local_status','local_status','查看局部修复计划与候选真实结果；不重跑。',{}],
    ['mp_feedback_begin','feedback_begin','开始有共享预算的质量调整活动。冻结当前原任务，不重置旧任务；后续仅在独立候选分支执行，Algorithm Agent 关闭。',{reason:{type:'string',required:true}}],
    ['mp_feedback_status','feedback_status','读取调整分支状态、阶段观察和剩余共享预算，不启动原生工具。',{}],
    ['mp_feedback_inspect','feedback_inspect','输入感知(input)、已接受阶段观察(stage)、最终DRC空间分布(quality)。指标区分实测、估计和未知，返回evidence_id；branch_id省略时读取原任务。',{kind:{type:'string',enum:['input','stage','quality'],required:true},branch_id:{type:'string'},stage:{type:'string'}}],
    ['mp_feedback_branch','feedback_branch','基于当前证据建立独立检查点分支，仅修改既有iPL目标密度。复用布局前的已验证阶段；布局及其下游被明确作废并在候选重算。不会执行原生作业，不覆盖原成果。source_branch可选择已有候选进行中途回退。',{campaign_state_id:{type:'string',required:true},evidence_id:{type:'string',required:true},density:{type:'number',required:true},source_branch:{type:'string'},reason:{type:'string',required:true},expected_effect:{type:'string',required:true},uncertainties:{type:'string'}}],
    ['mp_feedback_continue','feedback_continue','执行指定候选的下一段服务器iEDA阶段，到布局验证后、布线前、DRC后或最终交付处暂停，再由你根据观察选择继续/回退/停止。需要最新branch state_id和基于观察的理由；返回job_id后结束本轮，不反复轮询。',{branch_id:{type:'string',required:true},state_id:{type:'string',required:true},reason:{type:'string',required:true}}],
    ['mp_feedback_compare','feedback_compare','核验同原始输入、同规则覆盖下候选的实际DRC和布局指标，回退/不可比则拒绝采用。没有自动晋升，不能把零DRC视为签核。',{branch_id:{type:'string',required:true}}],
    ['mp_feedback_report','feedback_report','生成输入感知—阶段观察—参数调整—质量比较报告；download可展示报告卡片，原始成果不变。',{}],
    ['mp_feedback_stop','feedback_stop','停止新增调整并保存原成果、候选和比较证据，不删除文件；运行中原生作业需先job_cancel。',{reason:{type:'string',required:true}}],
    ['mp_task_open','open','打开用户指定的已完成远程任务。只复盘既有证据用purpose=evidence_review：本会话20次模型调用/1小时，接口禁止执行、改参、取消及重新绑定，不改变旧审查预算。需要实际新质量实验才用quality_review；它不会续期已过期的历史审查预算。',{task_id:{type:'string',required:true},purpose:{type:'string',enum:['quality_review','evidence_review']}}],
    ['mp_task_inspect','decision_inspect','读取当前事实或有来源的历史证据，返回可供计划引用的 evidence_id。local_short 是同一父DEF的局部几何，prior_comparison 是已做过的对照，不会重复布线。terminals 与 route_branches 用 name 指定网络，支持续页。episodes 为同案例同后端版本的历史经验，不能当当前测量。',{kind:{type:'string',enum:['summary','terminals','tracks','blockages','route_branches','local_short','prior_comparison','experiment_result','episodes'],required:true},name:{type:'string'},cursor:{type:'number'},limit:{type:'number'}}],
    ['mp_task_choices','decision_catalog','按当前状态、范围、证据与预算给出合格工具卡；主Agent负责选择，不由宿主替模型排名。',{}],
    ['mp_task_plan','decision_plan','主Agent提交结构化选择：工具、当前证据、依据、预期效果和未知项。宿主拒绝过期证据及不合格工具。预期效果只是待验证假设。',{decision_state_id:{type:'string',required:true},tool_id:{type:'string',required:true},evidence_id:{type:'string',required:true},reason:{type:'string',required:true},expected_effect:{type:'string',required:true},uncertainties:{type:'string',required:true}}],
    ['mp_task_execute_plan','decision_execute','执行已选择的计划。原生iEDA只在服务器持久作业中运行，返回job_id后结束当前轮等待结果；只读工具直接返回结果。实验不覆盖生产结果，不重跑已完成阶段。',{plan_id:{type:'string',required:true}}],
    ['mp_task_cancel_plan','decision_cancel','取消尚未执行的计划以便重新选择；运行中任务必须用job_cancel。',{plan_id:{type:'string',required:true},reason:{type:'string',required:true}}],
    ['mp_task_decision_report','decision_report','生成可下载的主Agent感知、选择、工具执行和质量反馈轨迹报告，不声明整体P1通过。随后download显示交付卡片。',{}],
    ['mp_task_run','run','在服务器后台执行当前已登记合同剩余的全流程。只运行唯一允许的下一阶段，保留全部验证门槛与预算，遇错即停。返回 job_id 仅表示提交，不表示完成。此任务不依赖 DSH 窗口存活；禁止重复提交。',{state_id:{type:'string',required:true},reason:{type:'string',required:true}}],
    ['mp_task_job_status','job_status','查询服务器持久作业及已验收阶段。运行中不要循环调用模型轮询；向用户报告 job_id，稍后查询。completed 只表示作业完成，只有 task.goal_certified=true 才表示案例目标完成。',{job_id:{type:'string',required:true}}],
    ['mp_task_job_cancel','job_cancel','用户明确要求停止时取消本任务指定的服务器作业，保留日志、已验收阶段和未完成阶段的 pending 证据。不会停止其他用户或其他任务。',{job_id:{type:'string',required:true},reason:{type:'string',required:true}}],
    ['mp_task_download','download','目标已验收后下载服务器最终报告、版图预览、DEF、可用的GDS及网表；逐文件校验SHA256并显示本地交付卡片。',{}],
    ['mp_task_start','start','冻结用户明确选择的登记网表和工艺/约束，创建服务器任务并返回真实合同、阶段依赖、资源预算、支持范围与输入感知报告。只支持枚举中的已登记案例；full_backend是否合格由当前服务器门禁决定，不按历史提示推断。输入不匹配不得绕过；Maker关闭，禁止本地Docker或其他EDA回退。',{case_id:{type:'string',enum:['sky130_gcd','ibench_gcd_legacy','sky130_sram_pair','aes_sky130_t','aes_legacy','aes_core_sky130_t','swerv_nangate45','bp_fe','s35932_nangate45_t'],required:true},goal:{type:'string',enum:['placement_def','routed_def','full_backend']}}],
    ['mp_task_observe','observe','读取当前事实、计划、允许动作和预算；也用于断点恢复。',{}],
    ['mp_task_resume','resume','用户要求继续、基础设施问题已修复后，从明确停止的已验收检查点继续。宿主核验全部冻结输入与历史阶段凭据、剩余原预算、磁盘容量及无在途原生作业。不会重置预算、修改验收门槛或把失败阶段记为完成；下一步仍是首个未完成阶段。不能用于绕过用户停止指令或额度限制。',{state_id:{type:'string',required:true},reason:{type:'string',required:true}}],
    ['mp_task_act','act','向服务器提交一个允许阶段，返回持久 job_id；用 job_status 获取结果。禁止跳步；finish 只有回读验证通过才认证目标，之后 download 获取本地交付。',{
      action:{type:'string',enum:['import_netlist','floorplan','macro_placement','fanout','placement','validate','export_def','cts','to_drv','to_hold','legalization','routing','filler','drc','timing','gds_export','routed_readback','recover','finish','stop'],required:true},
      state_id:{type:'string',required:true},reason:{type:'string',required:true}}],
    ['mp_task_retrieve','retrieve','检索有版本与来源的真实后端知识，保存引用快照；版本不兼容返回明确状态。',{
      query:{type:'string',required:true},backend_version:{type:'string',required:true}}],
    ['mp_task_query','query','分页查询当前已验收数据库的实例/网络/引脚，或回读历史事件和阶段证据。不接受任意文件路径。',{
      kind:{type:'string',enum:['instances','nets','pins','events','evidence'],required:true},
      cursor:{type:'number'},limit:{type:'number'},stage:{type:'string'}}],
    ['mp_task_discover','discover','按实时设计特征、工具验证记录、格式、约束和资源过滤工具。无宏返回 skip，无合格工具返回 capability_gap；保存选择证据。',{
      stage:{type:'string',enum:['macro_placement','standard_cell_placement'],required:true}}]
  ];
  for(const [name,operation,description,parameters] of defs){
    register(defineTool({name,description,parameters,output,async execute(args,exec){
      exec.signal?.throwIfAborted();
      const attachment_inputs=operation==='start'?await conversationAttachments(ctx,exec.agent):undefined;
      const value=await bridge({mode:'task',operation,run:taskRun(exec.agent),action_id:exec.callId,...args,
        ...(attachment_inputs===undefined?{}:{attachment_inputs})},exec.signal);
      if(operation==='start'||(operation==='feedback_inspect'&&['input','quality'].includes(args.kind))){
        const kind=operation==='start'?'input':args.kind;
        try{
          const record=operation==='start'?await bridge({mode:'task',operation:'feedback_inspect',kind:'input',run:taskRun(exec.agent)},exec.signal):value;
          const report=await writePerceptionReport(taskRun(exec.agent),kind,record);
          value.perception_report=report;
          const boundary=ctx.sessionProjections.stateOf(exec.agent.session,'turnBoundary');
          if(boundary?.openTurnStartSeq!=null)pending.set(exec,{session:exec.agent.session,turn:boundary.lastTurn,
            files:[{path:report.report.path,description:kind==='input'?'输入感知与布局布线建议':'结果反馈与局部诊断'},{path:report.data.path,description:'感知事实、建议与来源 JSON'}]});
        }catch(error){value.perception_report_error=String(error.message);}
      }
      if(value.download_verified && value.deliverables){
        const boundary=ctx.sessionProjections.stateOf(exec.agent.session,'turnBoundary');
        if(boundary?.openTurnStartSeq!=null){
          const files=[];
          for(const [key,description] of [['quality_review_report','IO / HPWL 与 hold 成本收益审查报告'],['local_repair_report','局部质量反馈与修复闭环报告'],['feedback_report','主 Agent 检查点调整与质量反馈报告'],['decision_report','主 Agent 感知—选择—质量反馈报告'],['final_def','最终 DEF'],['report','本次 iEDA 运行报告'],['preview','最终 DEF 派生的放置预览'],['final_gds','原生 iDB 抽象 GDS（非制造签核）'],['final_netlist','最终网表']]){
            if(!value.deliverables[key])continue;
            const ref=key==='preview'?value.deliverables.preview.preview:value.deliverables[key];
            if(path.dirname(path.resolve(ref.path))!==path.resolve(taskRun(exec.agent)))throw Error('Deliverable outside task directory');
            const bytes=await fs.readFile(ref.path);
            if(createHash('sha256').update(bytes).digest('hex')!==ref.sha256)throw Error('Deliverable hash mismatch');
            files.push({path:ref.path,description});
          }
          pending.set(exec,{session:exec.agent.session,turn:boundary.lastTurn,files});
        }
      }
      return value;
    }}));
  }
  // Same durable presentation protocol as DSH's built-in present tool.
  ctx.on('tools/result',(exec,result)=>{
    const delivery=pending.get(exec);pending.delete(exec);
    if(delivery && !result.isError)delivery.session.append('deliverables/presented',{turn:delivery.turn,callId:exec.callId,files:delivery.files});
  });
}
