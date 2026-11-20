// Thin batch/inspection client of the SAME task core used by DSH.
// --baseline is deterministic backend validation, not a second autonomous Agent.
import path from 'node:path';
import {bridge,root} from './runtime.mjs';
const args=process.argv.slice(2);
const option=(name,fallback)=>{const i=args.indexOf(name);return i<0?fallback:args[i+1];};
const run=path.resolve(option('--run',path.join(root,'runs','main-task-'+Date.now())));
let state=await bridge({mode:'task',operation:option('--operation','start'),run,case_id:option('--case','sky130_gcd'),goal:option('--goal','placement_def'),
  ...(args.includes('--job')?{job_id:option('--job')}:{}),reason:option('--reason','Explicit batch client request')});
if(args.includes('--baseline')){
  state=await bridge({mode:'task',operation:'run',run,action_id:'registered-baseline-v1',
    state_id:state.state_id,reason:'Deterministic server baseline using shared task core'});
  console.log('Submitted durable server job. This client exits; query with --operation observe.');
}
console.log(JSON.stringify(state,null,2));
if(state.action_error||state.status==='failed')process.exitCode=1;
