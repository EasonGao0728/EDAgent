import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';

const esc=v=>String(v??'未知').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names={instances:'逻辑实例数',hard_macros:'硬宏数',cell_area:'单元面积',macro_area:'宏面积',core_area:'核心面积',nominal_area_utilization:'名义面积利用率',sequential_instances:'时序单元数',net_degree_p95:'网络端点数 P95',net_degree_max:'最大网络端点数',electrical_fanout:'电气扇出'};
export function inputAdvice(facts){
  const m=facts.metrics||{},v=k=>m[k]?.value,features=[],advice=[];
  if(v('hard_macros')===0){features.push('已解析输入中未发现硬宏');advice.push({direction:'标准单元布局',basis:'hard_macros=0',action:'跳过不必要的宏布局选择，核验标准单元布局工具的格式、约束和当前阶段资格。',validation:'合法性、实际密度、线长及后续布线反馈'});}
  else if(v('hard_macros')>0){features.push(`包含 ${v('hard_macros')} 个硬宏`);advice.push({direction:'宏规划与可布线性',basis:'hard_macros>0',action:'先检查宏尺寸、固定约束、引脚朝向、宏间通道和障碍物，再选择已验证的宏布局流程。',validation:'宏重叠/越界、通道与引脚可达性；不能仅以总利用率判定'});}
  if(typeof v('nominal_area_utilization')==='number'){features.push(`单元面积/核心面积约 ${(v('nominal_area_utilization')*100).toFixed(2)}%（估计）`);advice.push({direction:'密度与空间预算',basis:'nominal_area_utilization；未扣除阻塞和不可用行',action:'将名义面积比作为可行性线索；排除明显过低目标，核对工具实际采用的密度。不得由单个比值直接推断拥塞。',validation:'请求值/原生日志值/DEF变化；再测量实际拥塞'});}
  if(v('sequential_instances')>0)advice.push({direction:'时钟与时序',basis:'Liberty ff/latch 单元识别',action:'核对时钟约束、CTS 后缓冲与偏斜、hold/setup 和 RC 口径。时序单元多不等于已确定设计功能。',validation:'同场景时序报告；缺少SPEF时保持诊断范围'});
  if(v('net_degree_max')!=null)advice.push({direction:'连接结构',basis:`最大网络端点数 ${v('net_degree_max')}`,action:'检查高端点数网络是否属于时钟、复位或数据；取得引脚方向后再判断电气扇出和缓冲需求。',validation:'网络分类、驱动/负载方向、扇出与拥塞实测'});
  return {version:'input-advice-v1',features,advice,policy:'证据驱动的规则建议；不是已校准的成功率模型，不自动改变冻结参数',unknowns:[...(facts.unknowns||[]),'输入画像不能直接测出布线拥塞或最终 DRC','设计类型来自声明，未验证逻辑功能'],evolution:'记录输入画像、动作、实际结果和适用范围；后续以独立验证集评估建议，不自动从一次成功推广。'};
}
export function qualityAdvice(facts){
  const usable=facts.count_consistent===true,hotspots=usable?(facts.hotspots||[]):[];
  return {version:'quality-diagnosis-v1',status:usable?'diagnosis_only':'evidence_review_required',
    final_marker_count:usable?facts.count:null,measured_congestion:null,
    regions:hotspots.map(h=>({bbox_um:[h.tile_10um[0]*10,h.tile_10um[1]*10,(h.tile_10um[0]+1)*10,(h.tile_10um[1]+1)*10],markers:h.markers,
      cause:'unknown',hypotheses:['局部线距/短路、引脚访问或电源/信号几何交互，需按该区域实际规则类型区分'],
      required_evidence:['该区域完整marker及网络/层','DEF线段/过孔、LEF引脚/OBS和轨道','同一工艺的规则参数','若判断拥塞，必须有实际容量/需求或overflow网格'],
      actions:[{id:'regional_diagnosis',available:true,effect:'只读定位，不修改版图'},
        {id:'local_reroute_or_placement_eco',available:false,reason:'尚无已验证的区域ECO/局部重布线适配器；不能将全局目标密度分支冒称为局部修复'}]})),
    iteration_protocol:['定位热点并保留基线','核对几何与规则，列出可检验根因假设','检索具备区域作用范围的合格工具；无工具则记录能力缺口','独立检查点分支只改一个因素，记录受影响阶段','同输入/同检查器比较局部及全芯片DRC、连通性、时序与成本','有回退则拒绝，改善且通过门禁才进入复核；预算耗尽或无改善停止'],
    capability_gap:'当前支持全局密度候选与限定历史局部实验；尚不支持任意热点的自动局部修复。',
    automatic_local_repair_enabled:false,algorithm_agent_enabled:false,signoff_clean:false};
}
export function renderPerception(kind,facts,analysis){
  const title=kind==='input'?'输入感知与布局布线建议':'结果反馈与局部诊断';
  const metrics=Object.entries(facts.metrics||{}).map(([k,m])=>`<tr><td>${esc(names[k]||k)}</td><td>${esc(m.value)}</td><td>${esc(m.unit)}</td><td>${esc(m.kind)} · ${esc(m.scope||'')}</td></tr>`).join('');
  const distribution=(title,rows)=>`<h2>${title}</h2><table><tr><th>类别</th><th>marker 数</th></tr>${Object.entries(rows||{}).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join('')}</table>`;
  const body=kind==='input'?`<h2>指标与测量口径</h2><table><tr><th>指标</th><th>值</th><th>单位</th><th>性质与范围</th></tr>${metrics}</table><h2>感知到的特征</h2><ul>${analysis.features.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><h2>后续策略建议</h2>${analysis.advice.map(a=>`<article><h3>${esc(a.direction)}</h3><p>依据：${esc(a.basis)}</p><p>${esc(a.action)}</p><p>验证：${esc(a.validation)}</p></article>`).join('')}<h2>未知与下一步补测</h2><ul>${analysis.unknowns.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><p>${esc(analysis.evolution)}</p>`:
    `<p>最终 marker：${esc(analysis.final_marker_count)}；实际拥塞：未知。DRC 热点不能直接等同于拥塞。</p>${distribution('规则分布',facts.by_rule)}${distribution('层分布',facts.by_layer)}<h2>热点区域</h2>${analysis.regions.map(r=>`<article><h3>${esc(r.bbox_um.join(', '))} μm · ${r.markers} markers</h3><p>根因：未知；需核验以下证据。</p><ul>${r.required_evidence.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></article>`).join('')||'<p>没有可据此定位的 marker；不推测坐标。</p>'}<h2>受控迭代流程</h2><ol>${analysis.iteration_protocol.map(x=>`<li>${esc(x)}</li>`).join('')}</ol><p class="warning">${esc(analysis.capability_gap)}</p>`;
  return `<!doctype html><meta charset="utf-8"><title>${title}</title><style>body{font:16px system-ui;color:#183047;max-width:1080px;margin:40px auto;padding:0 24px;line-height:1.7}table{border-collapse:collapse;width:100%}td,th{border:1px solid #d5dfe8;padding:10px;text-align:left}article{background:#f3f7fa;border-left:4px solid #287e91;padding:12px 20px;margin:16px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}.warning{color:#995516}</style><h1>${title}</h1><p>状态：${esc(facts.status)}；版本：${esc(analysis.version)}。实测、声明、估计和未知分开呈现；建议不代表已执行优化。</p>${body}<details><summary>完整事实与来源</summary><pre>${esc(JSON.stringify(facts,null,2))}</pre></details>`;
}
export async function writePerceptionReport(folder,kind,record){
  const facts=record.facts||record,analysis=kind==='input'?inputAdvice(facts):qualityAdvice(facts);
  const hash=createHash('sha256').update(JSON.stringify({kind,facts,analysis})).digest('hex').slice(0,16),name=`${kind}-perception-${hash}`;
  await fs.mkdir(folder,{recursive:true});
  const files=[];
  for(const [ext,data] of [['json',JSON.stringify({kind,evidence_id:record.evidence_id,facts,analysis},null,2)],['html',renderPerception(kind,facts,analysis)]]){
    const file=path.join(folder,name+'.'+ext);await fs.writeFile(file,data);files.push({path:file,sha256:createHash('sha256').update(data).digest('hex'),bytes:Buffer.byteLength(data)});
  }
  return {report:files[1],data:files[0],analysis};
}
