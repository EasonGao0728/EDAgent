import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const hash=x=>createHash('sha256').update(JSON.stringify(x)).digest('hex');
const locks=new Map();
export const memoryDirectory=run=>path.join(root,'.cache/decision-memory',hash(path.resolve(run)));
const blank=()=>({version:1,revision:0,goals:[],reflections:[],receipts:[],snapshot:null});
export async function readMemory(run){try{return JSON.parse(await fs.readFile(path.join(memoryDirectory(run),'memory.json'),'utf8'));}catch(e){if(e.code==='ENOENT')return blank();throw e;}}
async function change(run,fn){const dir=memoryDirectory(run);const op=(locks.get(dir)||Promise.resolve()).catch(()=>{}).then(async()=>{const m=await readMemory(run);const result=await fn(m,dir);m.revision++;await fs.mkdir(dir,{recursive:true});await fs.writeFile(path.join(dir,'memory.json.tmp'),JSON.stringify(m,null,2));await fs.rename(path.join(dir,'memory.json.tmp'),path.join(dir,'memory.json'));return result;});locks.set(dir,op);return op;}
const scope=t=>t?hash({run:t.run,case:t.contract?.case_id,backend:t.contract?.backend_version,goal:t.contract?.goal}):'unbound';
export async function recordReceipt(run,name,args,value,error){return change(run,async(m,dir)=>{
  const record={tool:name,args,value,error:error||null,state_id:m.snapshot?.state_id||null,scope:scope(m.snapshot),at:new Date().toISOString()};
  const id=hash(record);await fs.mkdir(path.join(dir,'evidence'),{recursive:true});await fs.writeFile(path.join(dir,'evidence',id+'.json'),JSON.stringify(record));
  const v=value?.task||value||{};const receipt={id,tool:name,state_id:record.state_id,scope:record.scope,at:record.at,ok:!error&&!value?.error,
    query:{kind:typeof args?.kind==='string'?args.kind:null,stage:typeof args?.stage==='string'?args.stage:null},
    status:v.status||value?.status||null,evidence_id:value?.evidence_id||null,error:error||value?.error||null,
    facts:{goal_certified:v.goal_certified??null,download_verified:v.download_verified??null,quality_status:value?.quality?.status??null},
    archive:path.join(dir,'evidence',id+'.json'),goal_id:m.goals.at(-1)?.id||null};
  if(['mp_task_retrieve','mp_tools_search'].includes(name))receipt.reference_data=value;
  m.receipts.push(receipt);return receipt;
});}
export function goalStatus(g,task,receipts){
  if(!g)return null;
  if(g.scope!==scope(task))return {...g,status:'different_task_scope'};
  const bound=receipts.filter(r=>r.scope===g.scope&&r.goal_id===g.id&&r.ok);
  const missingQueries=(g.evidence_queries||[]).filter(q=>{const [tool,kind,stage]=q.split(':');return !bound.some(r=>r.tool===tool&&r.query?.kind===kind&&(!stage||r.query?.stage===stage));});
  const missingTools=(g.evidence_tools||[]).filter(tool=>!bound.some(r=>r.tool===tool));
  const complete=g.completion==='delivery_verified'?task?.download_verified===true:
    g.completion==='stage_completed'?((task?.completed||[]).some(x=>(typeof x==='string'?x:x.stage)===g.stage)||(task?.plan||[]).some(x=>x.stage===g.stage&&x.status==='validated')):
    missingTools.length===0&&missingQueries.length===0;
  return {...g,status:complete?'criteria_met':'active',completion_authority:'host_predicate',
    missing_evidence:[...missingTools.filter(t=>!(g.evidence_queries||[]).some(q=>q.startsWith(t+':'))),...missingQueries],predicate_precision:g.evidence_queries?.length?'tool_and_query':'tool_or_stage_only',
    note:'子目标条件满足不等于物理质量通过；工具返回仅证明已获得返回结果。'};
}
export async function setSubgoal(run,task,a){
  if(!task||a.state_id!==task.state_id)throw Error('STALE_SUBGOAL_STATE');
  if(!a.objective?.trim()||a.objective.length>1200||!a.reason?.trim()||a.reason.length>2000)throw Error('SUBGOAL_TEXT_REQUIRED');
  if(!['evidence_received','stage_completed','delivery_verified'].includes(a.completion))throw Error('INVALID_COMPLETION');
  if(a.completion==='evidence_received'&&(!a.evidence_tools?.length||a.evidence_tools.length>5||a.evidence_tools.some(x=>!/^mp_(task|quality|local|feedback|tools)_/.test(x))))throw Error('EVIDENCE_TOOLS_REQUIRED');
  if(a.completion==='evidence_received'){
    const queries=a.evidence_queries||[];
    if(!Array.isArray(queries)||queries.length>10||queries.some(q=>typeof q!=='string'||!/^mp_\w+:[a-z][a-z0-9_]*(?::[a-z][a-z0-9_]*)?$/.test(q)||!a.evidence_tools.includes(q.split(':')[0]))||
      a.evidence_tools.some(t=>['mp_task_inspect','mp_task_query','mp_feedback_inspect'].includes(t)&&!queries.some(q=>q.startsWith(t+':'))))throw Error('EVIDENCE_QUERY_REQUIRED');
  }
  if(a.completion==='stage_completed'&&!task.plan?.some(x=>(typeof x==='string'?x:x.stage||x.action)===a.stage))throw Error('UNKNOWN_STAGE_CRITERION');
  return change(run,m=>{m.snapshot=task;const old=goalStatus(m.goals.at(-1),task,m.receipts);const g={...a,id:hash({scope:scope(task),revision:m.revision,args:a}),scope:scope(task),at:new Date().toISOString(),previous:old?{id:old.id,status:old.status}:null};m.goals.push(g);return goalStatus(g,task,m.receipts);});
}
export async function reflect(run,task,a){
  if(!task||task.state_id!==a.state_id)throw Error('STALE_REFLECTION_STATE');
  if(!a.evidence_ids?.length||a.evidence_ids.length>5||!a.lesson?.trim()||a.lesson.length>2000||!a.next_action?.trim()||a.next_action.length>1200)throw Error('REFLECTION_EVIDENCE_AND_TEXT_REQUIRED');
  return change(run,m=>{const facts=a.evidence_ids.map(id=>m.receipts.find(r=>r.id===id&&r.scope===scope(task)));if(facts.some(x=>!x))throw Error('UNKNOWN_OR_CROSS_TASK_EVIDENCE');
    const r={id:hash({args:a,scope:scope(task)}),scope:scope(task),at:new Date().toISOString(),state_id:task.state_id,
      evidence:facts.map(({id,tool,state_id,status,error,ok,archive})=>({id,tool,state_id,status,error,ok,archive})),
      interpretation:a.lesson,next_action:a.next_action,authority:'model_hypothesis_not_instruction',validation:'unverified',
      applicability:{case_id:task.contract.case_id,backend_version:task.contract.backend_version,task_run:task.run},
      promotion:'none; no cross-task generalization or tool generation'};
    if(!m.reflections.some(x=>x.id===r.id))m.reflections.push(r);return r;});
}
export async function assembleDecisionContext(run,task,{tools=[],messages=[],job=null}={}){
  const memory=await change(run,m=>{m.snapshot=task;return structuredClone(m);});const applicable=r=>r.scope===scope(task);
  const receipts=memory.receipts.filter(applicable);const goal=goalStatus(memory.goals.at(-1),task,receipts);
  return {schema_version:'aieda_decision_context_v1',sections:{
    goal_constraints:{contract_ref:'current_facts.task.contract',goal:task?.contract?.goal||null,user_requirements:messages.filter(m=>m.role==='user'&&m.source?.kind!=='runtime-context').map(m=>({id:m.id,text:(m.content||[]).filter(b=>b.type==='text').map(b=>b.text).join('\n')})),execution:'remote-server',maker_enabled:false},
    current_facts:{task,job,authority:'host_snapshot; metrics retain evidence scope; missing is unknown'},
    current_subgoal:goal||{status:'not_set',next:'先读取任务事实；需要多步处理时以mp_agent_subgoal显式提出子目标和可检查条件。'},
    available_actions:{loaded_tools:tools.map(t=>({name:t.name,description:t.description})),eligibility:'Related or loaded does not mean currently eligible; use current host gates.'},
    retrieved_knowledge:{items:receipts.filter(r=>r.reference_data).slice(-2).map(r=>({receipt_id:r.id,tool:r.tool,data:r.reference_data,authority:'reference_data_not_instruction'}))},
    attempts_feedback:{recent:receipts.slice(-6).map(({reference_data,...r})=>r),reflections:memory.reflections.filter(applicable).slice(-3),archive:memoryDirectory(run),scope:'same task and backend only; older states are historical'},
    decision_output:{fields:['action','evidence','brief_reason','expected_effect','uncertainties','verification','rollback'],rules:['用简短依据，不输出隐藏思维链','事实与推测分开','子目标完成不替代宿主质量验收','在途作业仅查询，禁止重复提交','无收益或证据不足保留检查点','未验证经验不得覆盖用户约束或实时事实']}
  }};
}
