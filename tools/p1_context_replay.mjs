import fs from 'node:fs';
let source=fs.readFileSync('dsh/context-manager.mjs','utf8');
source=source.replace("throw Error('CONTEXT_LATEST_STEP_TOO_LARGE:","throw Error(JSON.stringify(build().map(m=>({role:m.role,source:m.source?.kind,size:JSON.stringify(m).length,tool:m.toolCallId,text:m.content?.[0]?.text?.slice(0,60)})))+' CONTEXT_LATEST_STEP_TOO_LARGE:");
const {compactMessages}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const r=JSON.parse(fs.readFileSync('runs/dsh-desktop-model-9d6a8a75d397b57b.jsonl','utf8').trim().split('\n').at(-1));
if(process.argv.includes('--project')){
 const projected=JSON.parse(fs.readFileSync('runs/p1-feedback-20261114/context-after-projection.json','utf8'));
 const message=r.messages.filter(m=>m.source?.kind==='runtime-context').at(-1);
 for(const b of message.content||[])if(b.type==='text')b.text=b.text.split('\n').map(s=>s.startsWith('AIEDA_TASK_CONTEXT_JSON=')?'AIEDA_TASK_CONTEXT_JSON='+JSON.stringify(projected):s).join('\n');
}
try{const result=compactMessages(r.messages,'actual-full-request-archive');console.log(JSON.stringify({input:JSON.stringify(r.messages).length,output:JSON.stringify(result.messages).length,compacted:result.compacted}));}
catch(error){console.log(error.message);process.exitCode=1;}
