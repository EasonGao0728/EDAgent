// Real iEDA through the native DSH tool registry; no LLM calls or GUI claims.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {pkg,root} from './runtime.mjs';
import * as desktop from './desktop-tools.mjs';
const {Context}=await pkg('cordis');
const {createScope}=await pkg('dsh-scope');
const {default:Tools}=await pkg('dsh-tools');
const {default:SystemPrompt}=await pkg('dsh-system-prompt');
const ctx=new Context(),fibers=[ctx.plugin(Tools),ctx.plugin(SystemPrompt)];
const agent={session:{id:'ieda-native-verification-'+Date.now()}};
let scope;
fibers.push(ctx.plugin({name:'ieda-verify-scope',inject:['tools','systemPrompt'],apply(c){scope=createScope(c,agent);scope.ctx.plugin(desktop);}}));
try{
  await new Promise(r=>setTimeout(r,60));
  const call=async(name,args,id)=>{
    const result=await scope.ctx.tools.execute({name,arguments:args,callId:id,agent,signal:new AbortController().signal});
    assert.ok(!result.isError,JSON.stringify(result));return result.value;
  };
  const status=await call('mp_ieda_status',{},'ieda-status');
  assert.equal(status.available,true);
  const result=await call('mp_ieda_run',{case_id:'sky130_gcd'},'ieda-run');
  assert.equal(result.status,'completed');
  assert.equal(result.placement.placement_checks_passed,true);
  assert.equal(result.placement.hard_macros,0);
  const repeat=await call('mp_ieda_run',{case_id:'sky130_gcd'},'ieda-repeat');
  assert.deepEqual(repeat,result);
  const evidence={kind:'native_DSH_tool_registry_real_execution',llm_calls:0,desktop_demo:false,status,result,idempotency_verified:true};
  await fs.writeFile(path.join(root,'runs/dsh-ieda-tool-verification.json'),JSON.stringify(evidence,null,2));
  console.log(JSON.stringify({status:result.status,placement:result.placement,run:result.run,idempotency_verified:true}));
}finally{
  if(scope)await scope.dispose();
  for(const f of fibers.reverse())await f.dispose();
}
