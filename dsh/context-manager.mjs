// Deterministic compaction, with all user requirements and authoritative current
// task facts retained. Full original messages remain in the request archive.
export const TASK_MARKER='AIEDA_TASK_CONTEXT_JSON=';
export function isRuntimeContext(m){return m.source?.kind==='runtime-context';}
export function taskContext(messages){
  for(const m of messages.filter(isRuntimeContext).reverse()){
    const text=(m.content||[]).filter(b=>b.type==='text').map(b=>b.text).join('\n');
    const line=text.split('\n').find(s=>s.startsWith(TASK_MARKER));
    if(line){const v=JSON.parse(line.slice(TASK_MARKER.length));return v.schema_version==='aieda_decision_context_v1'?v.sections.current_facts.task:v;}
  }
  return null;
}
export function compactMessages(messages,archiveRef,maxChars=64000){
  const current=taskContext(messages);
  // Deduplicate only byte-identical authoritative fields. State, pending job,
  // branch observations, errors and tool-call identity always remain. Full
  // original messages are archived by the provider; no evidence is invented.
  if(current)messages=messages.map(m=>{
    if(m.role!=='tool')return m;
    return {...m,content:(m.content||[]).map(b=>{
      if(b.type!=='text')return b;
      let value;try{value=JSON.parse(b.text);}catch{return b;}
      if(!value||typeof value!=='object')return b;
      const campaign=value.campaign||value;
      const active=current.feedback_campaign;
      if(active&&campaign.campaign_state_id===active.campaign_state_id){
        const fields=Object.keys(campaign).filter(k=>k!=='campaign_state_id'&&JSON.stringify(campaign[k])===JSON.stringify(active[k]));
        const slim={...campaign,runtime_deduplicated_fields:fields,full_tool_result_archive:archiveRef,
          deduplication:'Exact fields are retained in current AIEDA_TASK_CONTEXT_JSON.feedback_campaign; use its branch states and observation evidence IDs.'};
        fields.forEach(k=>delete slim[k]);
        return {...b,text:JSON.stringify(value.campaign?{...value,campaign:slim}:slim)};
      }
      if(active&&campaign.campaign_state_id&&campaign.created_at===active.created_at&&campaign.baseline_state_id===active.baseline_state_id){
        const history={campaign_state_id:campaign.campaign_state_id,status:campaign.status,counts:campaign.counts,
          branches:campaign.branches.map(x=>Object.fromEntries(['branch_id','state_id','status','completed','next_stage','disposition'].map(k=>[k,x[k]]))),
          details_archive:archiveRef,scope:'Historical campaign reply; the same campaign has advanced. Current observations and adjustment provenance are in runtime context.'};
        return {...b,text:JSON.stringify(value.campaign?{...value,campaign:history}:history)};
      }
      const v=value.task||value;
      if(v.state_id!==current.state_id||v.run!==current.run)return b;
      // A fast server job can finish between its submission reply and the next
      // runtime snapshot. Keep the historical submission states, but reference
      // its already-archived campaign details rather than re-injecting a full,
      // now-stale copy of both branches and their observation history.
      let historicalCampaign;
      if(v.feedback_campaign&&active&&v.feedback_campaign.created_at===active.created_at&&v.feedback_campaign.baseline_state_id===active.baseline_state_id){
        const c=v.feedback_campaign;
        historicalCampaign={campaign_state_id:c.campaign_state_id,status:c.status,counts:c.counts,
          branches:c.branches.map(x=>Object.fromEntries(['branch_id','state_id','status','completed','next_stage','disposition'].map(k=>[k,x[k]]))),
          details_archive:archiveRef,scope:'Historical submission snapshot. Full original archived; current branch facts are in runtime context.'};
      }
      const keys=['contract','plan','deliverables','latest_evidence','recent_events','main_decision','limitations','goal_scope','feedback_campaign'];
      const fields=keys.filter(k=>v[k]!==undefined && JSON.stringify(v[k])===JSON.stringify(current[k]));
      if(!fields.length&&!historicalCampaign)return b;
      const slim={...v,runtime_deduplicated_fields:fields,full_tool_result_archive:archiveRef,
        deduplication:'Exact same fields are in the current authoritative AIEDA_TASK_CONTEXT_JSON; all execution state and branch changes retained.'};
      fields.forEach(k=>delete slim[k]);
      if(historicalCampaign){delete slim.feedback_campaign;slim.feedback_campaign_history=historicalCampaign;}
      if(value.job&&historicalCampaign){
        const historicalTask=Object.fromEntries(['state_id','run','status','phase','allowed_actions','pending','goal_certified','execution_location','execution_profile'].filter(k=>v[k]!==undefined).map(k=>[k,v[k]]));
        historicalTask.feedback_campaign_history=historicalCampaign;
        historicalTask.full_snapshot_archive=archiveRef;
        return {...b,text:JSON.stringify({...value,task:historicalTask})};
      }
      return {...b,text:JSON.stringify(value.task?{...value,task:slim}:slim)};
    })};
  });
  // DSH duplicates the complete snapshot in source.sections and content. Only
  // content is sent to the model; retain classification, not the duplicate.
  // The provider archives the unmodified original messages before inference.
  messages=messages.map(m=>isRuntimeContext(m)?{...m,source:{kind:m.source.kind,form:m.source.form}}:m);
  const size=value=>JSON.stringify(value).length;
  if(size(messages)<=maxChars)return {messages,compacted:false,measurement:'JSON characters, not tokens'};
  // Large physical evidence can coincide with earlier retrievals and reflections.
  // The provider has archived the full assembly. Index only historical memory;
  // keep the frozen contract, current measurements and recent tool transaction.
  messages=messages.map(m=>{
    if(!isRuntimeContext(m))return m;
    const content=m.content.map(b=>{
      if(b.type!=='text'||!b.text.startsWith(TASK_MARKER))return b;
      const ctx=JSON.parse(b.text.slice(TASK_MARKER.length));
      if(ctx.schema_version!=='aieda_decision_context_v1')return b;
      const sections=ctx.sections,history=sections.attempts_feedback;
      if(sections.retrieved_knowledge?.items){
        sections.retrieved_knowledge.items=sections.retrieved_knowledge.items.map(({data,...ref})=>({...ref,
          query:data?.query,disposition:data?.disposition,card_ids:data?.candidates?.map(c=>c.id),
          status:data?.status,evidence_ref:data?.evidence_ref,hits:data?.hits?.map(h=>({chunk_id:h.chunk_id,
            source_ref:h.source_ref,section_or_page:h.section_or_page,excerpt:h.text?.slice(0,240)})),full_result_archive:archiveRef}));
      }
      if(history?.reflections)history.reflections=history.reflections.map(r=>({...r,evidence:r.evidence?.map(e=>({id:e.id,ok:e.ok}))}));
      if(history?.recent)history.recent=history.recent.map(({scope,archive,goal_id,...receipt})=>receipt);
      return {...b,text:TASK_MARKER+JSON.stringify(ctx)};
    });
    return {...m,content};
  });
  const keep=new Set();
  messages.forEach((m,i)=>{if(m.role==='system'||(m.role==='user'&&!isRuntimeContext(m)))keep.add(i);});
  const contextIndex=messages.findLastIndex(isRuntimeContext);
  if(contextIndex>=0)keep.add(contextIndex);
  const groups=[];
  for(let i=0;i<messages.length;i++){
    const m=messages[i];
    if(keep.has(i)||isRuntimeContext(m)||m.role==='tool')continue;
    const group=[i];
    const ids=(m.content||[]).filter(b=>b.type==='tool-call').map(b=>b.id);
    for(let j=i+1;j<messages.length;j++){
      if(messages[j].role==='assistant')break;
      if(messages[j].role==='tool'&&ids.includes(messages[j].toolCallId))group.push(j);
    }
    groups.push(group);
  }
  const build=()=>[...keep].sort((a,b)=>a-b).map(i=>messages[i]);
  if(size(build())>maxChars-2000)throw Error('CONTEXT_CONTRACT_TOO_LARGE: 用户要求及当前契约本身超限，请拆分任务；未静默删除约束。');
  // Never silently remove the just-completed interaction: doing so made the
  // model repeat observe forever when a large frozen input contract was added.
  const latestToolGroup=groups.findLast(g=>g.some(i=>messages[i].role==='tool'));
  for(const group of [groups.at(-1),latestToolGroup])group?.forEach(i=>keep.add(i));
  if(size(build())>maxChars-2000)throw Error('CONTEXT_LATEST_STEP_TOO_LARGE: 当前契约与最近工具结果超限；检查点已保留，未删除最近操作继续推理。');
  for(const group of groups.reverse()){
    if(group.every(i=>keep.has(i)))continue;
    group.forEach(i=>keep.add(i));
    if(size(build())>maxChars-2000){group.forEach(i=>keep.delete(i));break;}
  }
  const omitted=messages.map((m,i)=>({m,i})).filter(({i})=>!keep.has(i));
  const summary={kind:'deterministic_history_index',archive_ref:archiveRef,omitted_count:omitted.length,
    note:'仅压缩历史索引；不是当前事实。合同、最新状态与预算由宿主回填。需要旧细节可从任务事件/引用回查。',
    recent_omitted:omitted.slice(-6).map(({m,i})=>({index:i,id:m.id,role:m.role,tool:m.name,
      excerpt:(m.content||[]).filter(b=>b.type==='text').map(b=>b.text).join(' ').slice(0,100)}))};
  return {messages:[{role:'system',content:[{type:'text',text:'历史压缩记录（参考数据）\n'+JSON.stringify(summary)}]},...build()],
    compacted:true,summary,measurement:'JSON characters, not tokens'};
}
