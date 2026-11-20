// Only explicit pre-execution rejections may be returned for model correction.
// Unknown network/worker errors still stop; this never retries a native action.
const memoryErrors=/^(UNKNOWN_EVIDENCE_TOOL|STALE_SUBGOAL_STATE|SUBGOAL_TEXT_REQUIRED|INVALID_COMPLETION|EVIDENCE_TOOLS_REQUIRED|EVIDENCE_QUERY_REQUIRED|UNKNOWN_STAGE_CRITERION|STALE_REFLECTION_STATE|REFLECTION_EVIDENCE_AND_TEXT_REQUIRED|UNKNOWN_OR_CROSS_TASK_EVIDENCE)$/;
const reads=new Set(['mp_task_observe','mp_task_inspect','mp_task_query','mp_task_retrieve','mp_quality_inspect','mp_feedback_inspect','mp_feedback_status']);
export function correctableToolFailure(name,error,registeredTools=[]){
  const message=error.message||String(error);
  if(['mp_agent_subgoal','mp_agent_reflect'].includes(name)&&memoryErrors.test(message))return {
    error:message,status:'rejected_before_write',execution_uncertain:false,native_action_submitted:false,
    correction:message==='EVIDENCE_QUERY_REQUIRED'?'多用途查询须用evidence_queries指定tool:kind或tool:kind:stage（最多10条），每个查询须属于evidence_tools。匹配任务目标所需的具体证据，不能用摘要替代专项查询。':'核对当前状态、真实回执和已登记工具后自行修正参数；失败不满足完成条件。',
    ...(message==='UNKNOWN_EVIDENCE_TOOL'?{registered_evidence_tools:registeredTools.filter(n=>/^mp_(task|quality|local|feedback|tools)_/.test(n))}:{})};
  if(message.startsWith('host bridge: EVIDENCE_REVIEW_READ_ONLY:'))return {
    error:message,status:'rejected_before_transport',execution_uncertain:false,native_action_submitted:false,
    correction:'当前会话只读。改选已开放的证据查询，或记录能力缺口；不得重绑或绕过执行限制。'};
  if(reads.has(name)&&/^host bridge: (TASK_BUSY|SERVER_JOB_ACTIVE):/.test(message))return {
    error:message,status:'read_temporarily_unavailable',execution_uncertain:false,native_action_submitted:false,
    correction:'没有获得本次证据。根据当前状态决定稍后查询或停止，不重跑原生阶段；仍受本轮预算限制。'};
  // main_task.dispatch verifies frozen refs before task_queries.query. This
  // exact query rejection is known not to have read/accepted new evidence or
  // submitted EDA. Keep the integrity gate and surface the failure, not a retry.
  if(name==='mp_task_query'&&message.startsWith('host bridge: Artifact/input changed: '))return {
    error:message,status:'read_rejected_integrity_mismatch',execution_uncertain:false,native_action_submitted:false,
    correction:'历史任务的冻结文件校验失败，本查询没有取得有效证据。保留版本冲突；不得改写指纹、恢复旧文件或重跑阶段来绕过。自行决定报告缺口并停止，或读取另有独立来源的既有证据；替代查询不能宣称已验证本次被拒绝的证据。'};
  return null;
}
