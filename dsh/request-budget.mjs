import {createHash} from 'node:crypto';

export function turnRequestLimit(task){
  if(!task)return 20;
  const value=task.contract?.budget?.model_calls;
  if(!Number.isInteger(value)||value<1)throw Error('MODEL_BUDGET: 任务模型预算缺失或无效。');
  // The task core also reserves against the total task budget. This turn ceiling
  // cannot expand that budget or reset it when a user continues a conversation.
  return Math.min(value,40);
}

export function turnKey(messages){
  const user=messages.filter(m=>m.role==='user'&&m.source?.kind!=='runtime-context').at(-1);
  if(!user)throw Error('MODEL_BUDGET: 当前请求没有用户轮次。');
  return createHash('sha256').update(user.id||JSON.stringify(user)).digest('hex').slice(0,24);
}

export function turnRequestCount(history,messages){
  const key=turnKey(messages);
  let count=0;
  for(const line of history.split('\n').filter(Boolean)){
    let entry;
    try{entry=JSON.parse(line);}catch{throw Error('MODEL_BUDGET: 请求记录损坏，无法确认本轮预算。');}
    if(entry.event!=='request')continue;
    if((entry.turn_key||turnKey(entry.messages))===key)count++;
  }
  return count;
}
