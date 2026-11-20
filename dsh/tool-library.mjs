import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {CARD_COPY,ORIGINS,TOOL_COPY} from './tool-catalog-copy.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const row=(id,title,stage,description,tools,options={})=>({id,title,stage,description,tools,version:1,
  summary:CARD_COPY[id][1],origin:{kind:CARD_COPY[id][0],...ORIGINS[CARD_COPY[id][0]]},
  endpoints:tools.map(name=>({name,summary:TOOL_COPY[name]})),
  provider:'iEDA / 主 Agent',status:'registered',execution:'server',
  scope:'登记案例与原有服务器门禁；检索命中不等于当前可执行',...options});
export const CARDS=[
  row('session-control','任务与远程作业','diagnosis',CARD_COPY['session-control'][1],['mp_task_start','mp_task_open','mp_task_observe','mp_task_job_status','mp_task_job_cancel','mp_task_download']),
  row('agent-memory','子目标与反思记忆','diagnosis',CARD_COPY['agent-memory'][1],['mp_agent_subgoal','mp_agent_reflect'],{execution:'local'}),
  row('tool-discovery','工具检索与按需加载','diagnosis',CARD_COPY['tool-discovery'][1],['mp_tools_search','mp_tools_load'],{execution:'local'}),
  row('pre-route-quality','IO / HPWL / hold 成本收益审查','optimization','预布线IO坐标适配、原生与独立HPWL一致性、hold缓冲器时序收益和面积网络代价；复用DRV检查点，候选不满足门禁则保留原结果，不重跑布局或布线。',['mp_quality_inspect','mp_quality_execute'],{status:'conditional',scope:'当前仅已登记SWERV Nangate45；拥塞/DRC/RC时序未测，不能推断通过'}),
  row('local-via-eco','局部过孔质量反馈与修复','optimization','真实DRC热点诊断、固定PDK过孔模板单点调整、原快照iDRC全芯片验证与回退；原快照旧ECO接口失败和官方iECO零替换记录保留，当前动作不是原生ECO或通用局部重布线。',['mp_local_inspect','mp_local_plan','mp_local_execute','mp_local_status'],{status:'conditional',scope:'仅已登记父DEF的AES；一次真实改动候选；服务器4核8GiB；连通性/时序未知则拒绝晋升'}),
  row('workflow-control','流程决策与检查点续接','diagnosis','读取当前状态、选择合格工具、计划与执行下一步；停止任务仅在用户明确要求后续接。',['mp_task_act','mp_task_inspect','mp_task_choices','mp_task_plan','mp_task_execute_plan','mp_task_cancel_plan','mp_task_decision_report','mp_task_resume']),
  row('knowledge-retrieval','物理设计知识检索 RAG','diagnosis','按当前后端版本检索 netlist placement routing validation readback 的知识与来源。',['mp_task_retrieve'],{read_only:true}),
  row('teaching-toy','教学微型布局示例','input','connected_groups blocked_channel 玩具宏布局和固定邻域交换，仅用于教学，不能代表真实芯片PPA。',['mp_start','mp_query','mp_retrieve','mp_optimize','mp_finish','mp_catalog','mp_connectivity','mp_oss_optimize'],{execution:'local',scope:'仅明确选择的toy案例；正式iEDA任务绑定后不可混用'}),
  row('input-profile','输入感知与策略报告','input','读取网表 netlist、LEF Liberty SDC；规模、宏、时序单元、利用率、连接特征和布局布线建议。',['mp_feedback_inspect'],{example:{kind:'input'},execution:'server-read/local-report'}),
  row('physical-query','版图几何与连接查询','diagnosis','读取 net terminals tracks blockages route branches，引脚、障碍物、轨道、网络连接和局部短路证据。',['mp_task_query','mp_task_inspect'],{read_only:true}),
  row('floorplan','iFP 版图规划','floorplan','导入网表、芯片区域、IO和电源规划 floorplan IO PDN。',['mp_task_run'],{native_stages:['import_netlist','floorplan','fanout']}),
  row('macro-place','iMP 宏单元布局','placement','有硬宏 SRAM 的 macro placement，约束、非重叠、固定宏、边界。',['mp_task_discover','mp_task_choices','mp_task_run'],{native_stages:['macro_placement'],requires_hard_macros:true}),
  row('cell-place','iPL 标准单元布局','placement','standard cell placement，优化线长和密度，独立合法性和 DEF 回读。',['mp_task_discover','mp_task_choices','mp_task_run'],{native_stages:['placement','validate','export_def']}),
  row('clock-timing','iCTS / iTO 时钟与时序','clock','clock tree synthesis CTS，DRV、hold 时序优化与合法化。',['mp_task_run'],{native_stages:['cts','to_drv','to_hold','legalization']}),
  row('routing','iRT 全芯片布线','routing','global detailed routing，全芯片布线，在服务器执行、保留持久job_id。不是区域 ECO 接口。',['mp_task_run'],{native_stages:['routing','filler']}),
  row('drc','iDRC 支持规则检查','verification','DRC design rule check 短路、间距、最小面积，区分过滤前候选与最终marker、规则覆盖。',['mp_task_run','mp_feedback_inspect'],{native_stages:['drc'],example:{kind:'quality'}}),
  row('finish-export','时序诊断与最终交付','verification','时序诊断、原生抽象GDS导出、最终 DEF 回读、下载和哈希校验；不代表制造签核。',['mp_task_run','mp_task_download'],{native_stages:['timing','gds_export','routed_readback','finish']}),
  row('stage-observation','阶段观察与风险提示','diagnosis','读取检查点阶段指标、实际工具参数、几何、线长与密度代理，决定继续或回退。',['mp_feedback_inspect'],{read_only:true,example:{kind:'stage'}}),
  row('quality-diagnosis','DRC 热点与局部诊断报告','diagnosis','最终结果的 DRC 区域热点、规则/层分布，根因假设、缺失证据与局部修复能力缺口。DRC不等于拥塞。',['mp_feedback_inspect'],{read_only:true,example:{kind:'quality'}}),
  row('density-branch','独立布局密度候选','optimization','从布局前检查点分支调整已登记全局 iPL 目标密度；阶段暂停、比较、拒绝回退和保存报告。',['mp_feedback_begin','mp_feedback_status','mp_feedback_branch','mp_feedback_continue','mp_feedback_compare','mp_feedback_report','mp_feedback_stop'],{scope:'已登记 full_backend；不是局部ECO；最多两个候选、原预算不变'}),
  row('bounded-short-study','既有局部短路对照','diagnosis','复核已冻结308-net局部短路与met3/met4对照，指定历史作用域、单因素实验；非任意热点自动修复。',['mp_task_choices','mp_task_inspect','mp_task_plan','mp_task_execute_plan','mp_task_cancel_plan','mp_task_decision_report'],{status:'conditional',scope:'必须由实时 decision_catalog 判定 eligible，禁止泛化到其他区域'}),
  row('local-eco','区域布局 / 布线 ECO','optimization','在指定拥塞或DRC区域调整单元、通道、引脚访问或局部重布线，然后验证边界连通与全芯片质量。',[],{status:'capability_gap',scope:'尚无经验证的任意区域执行适配器；不可调用'}),
  row('congestion-map','实际拥塞网格测量','diagnosis','按层和区域测量routing demand capacity overflow，不能用单元密度替代。',[],{status:'capability_gap',scope:'尚未接入有来源的统一拥塞网格，结果为unknown'}),
  row('tool-maker','Algorithm Agent / Tool Maker','evolution','制造和演化新的算法工具，回归测试与审核后入库。',[],{status:'disabled',scope:'当前阶段不启用，检索失败仅记录需求'})
];
export const BOOTSTRAP=new Set(['mp_agent_subgoal','mp_agent_reflect','mp_tools_search','mp_tools_load','mp_task_start','mp_task_open','mp_task_observe','mp_task_job_status','mp_task_job_cancel','mp_task_download','mp_feedback_status','mp_feedback_stop']);
const digest=x=>createHash('sha256').update(JSON.stringify(x)).digest('hex');
export const catalogVersion=digest(CARDS);
export function catalog(){return {version:catalogVersion,cards:CARDS,stages:[...new Set(CARDS.map(c=>c.stage))],
  note:'工具卡表示已接入的能力与缺口，实际可执行性仍由当前任务、工艺、格式、预算和原有门禁确认。',maker_enabled:false};}
export function cosine(a,b){if(a.length!==b.length||!a.length)throw Error('EMBEDDING_DIMENSION_MISMATCH');let x=0,y=0,z=0;for(let i=0;i<a.length;i++){if(!Number.isFinite(a[i])||!Number.isFinite(b[i]))throw Error('INVALID_EMBEDDING');x+=a[i]*b[i];y+=a[i]**2;z+=b[i]**2;}return y&&z?x/Math.sqrt(y*z):0;}
const words=s=>(s.toLowerCase().match(/[a-z0-9_]+|[\u3400-\u9fff]/g)||[]);
function lexical(q,text){const a=new Set(words(q)),b=new Set(words(text));return a.size?[...a].filter(t=>b.has(t)).length/a.size:0;}
let embedderPromise,indexPromise;
async function embedder(){
  if(!embedderPromise)embedderPromise=(async()=>{
    const config=JSON.parse(await fs.readFile(path.join(root,'dsh/embedding-config.json'),'utf8'));
    const {pipeline,env}=await import('../.cache/tool-retrieval/node_modules/@huggingface/transformers/dist/transformers.node.mjs');
    env.cacheDir=path.join(root,'.cache/tool-embeddings');env.allowRemoteModels=true;
    const extractor=await pipeline('feature-extraction',config.model,{dtype:'q8',revision:config.revision,local_files_only:true,device:'cpu',session_options:{intraOpNumThreads:2,interOpNumThreads:1}});
    return {config,async encode(text){const tensor=await extractor(text,{pooling:'mean',normalize:true});return Array.from(tensor.data);}};
  })().catch(e=>{embedderPromise=null;throw e;});return embedderPromise;
}
async function vectors(){
  if(!indexPromise)indexPromise=(async()=>{const e=await embedder(),key=digest({catalogVersion,embedding:e.config}),target=path.join(root,'.cache/tool-embeddings',key+'.json');
    try{const saved=JSON.parse(await fs.readFile(target,'utf8'));if(saved.key===key&&saved.vectors.length===CARDS.length)return {...saved,e};}catch{}
    const rows=[];for(const c of CARDS)rows.push(await e.encode(c.title+' '+c.summary+' '+c.description+' '+c.scope));
    const saved={key,vectors:rows};await fs.mkdir(path.dirname(target),{recursive:true});await fs.writeFile(target,JSON.stringify(saved));return {...saved,e};
  })().catch(e=>{indexPromise=null;throw e;});return indexPromise;
}
export async function searchTools(query,{stage,topK=5,threshold=0.35}={}){
  if(typeof query!=='string'||!query.trim()||query.length>1200)throw Error('QUERY_REQUIRED_MAX_1200');
  if(stage&&!catalog().stages.includes(stage))return {query,stage,error:'UNKNOWN_STAGE',allowed_stages:catalog().stages,candidates:[],disposition:'correct_stage_or_omit',maker_called:false};
  if(!Number.isInteger(topK)||topK<1||topK>5)throw Error('TOP_K_RANGE_1_5');
  let index,queryVector,error;try{index=await vectors();queryVector=await index.e.encode(query);}catch(e){error=e.message.slice(0,180);}
  const ranked=CARDS.map((c,i)=>({...c,lexical_score:lexical(query,c.title+' '+c.summary+' '+c.description),semantic_score:index?cosine(queryVector,index.vectors[i]):null}))
    .filter(c=>!stage||c.stage===stage).map(c=>({...c,ranking_score:index?0.85*c.semantic_score+0.15*c.lexical_score:c.lexical_score}))
    .sort((a,b)=>b.ranking_score-a.ranking_score);
  const selected=ranked.filter(c=>!['disabled','capability_gap'].includes(c.status)&&(index?c.semantic_score>=threshold:c.lexical_score>0)).slice(0,topK);
  return {query,stage:stage||null,catalog_version:catalogVersion,mode:index?'local_embedding_plus_lexical':'lexical_fallback',embedding:index?index.e.config:null,embedding_error:error||null,
    threshold:index?threshold:null,threshold_status:'provisional_retrieval_filter_not_success_probability',top_k:topK,candidates:selected,
    capability_gaps:ranked.filter(c=>['disabled','capability_gap'].includes(c.status)&&(index?c.semantic_score>=threshold:c.lexical_score>0)).slice(0,2),
    disposition:selected.length?'candidates_require_state_and_contract_checks':'not_found',maker_called:false};
}
export const selectionFolder=folder=>path.join(root,'.cache/tool-context',digest(path.resolve(folder)));
export async function loadTools(folder,ids,reason){
  folder=selectionFolder(folder);
  if(!Array.isArray(ids)||ids.length<1||ids.length>5||ids.some(id=>!CARDS.some(c=>c.id===id&&!['disabled','capability_gap'].includes(c.status))))throw Error('INVALID_OR_UNAVAILABLE_TOOL_CARD');
  const cards=CARDS.filter(c=>ids.includes(c.id)),tools=[...new Set(cards.flatMap(c=>c.tools))];
  const record={catalog_version:catalogVersion,card_ids:ids,tools,reason,time:new Date().toISOString()};
  await fs.mkdir(folder,{recursive:true});await fs.writeFile(path.join(folder,'loaded-tool-cards.json'),JSON.stringify(record));
  await fs.appendFile(path.join(folder,'tool-retrieval-history.jsonl'),JSON.stringify(record)+'\n');
  return {loaded:cards,next_turn_tools:tools,scope:'加载定义，不执行工具；原有宿主门禁必须再次验证。'};
}
export async function visibleToolNames(folder){
  folder=selectionFolder(folder);
  const names=new Set(BOOTSTRAP);
  try{const r=JSON.parse(await fs.readFile(path.join(folder,'loaded-tool-cards.json'),'utf8'));if(r.catalog_version===catalogVersion){for(const id of r.card_ids||[]){const c=CARDS.find(c=>c.id===id&&!['disabled','capability_gap'].includes(c.status));for(const n of c?.tools||[])names.add(n);}}}catch{}
  return names;
}
