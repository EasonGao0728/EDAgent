import test from 'node:test';
import assert from 'node:assert/strict';
import {ensureDockerReady,requiresDocker,probeDocker,probeWithRecovery} from './docker-readiness.mjs';
test('only native stages require an engine; recovery and evidence remain usable',()=>{
  for(const action of ['routing','gds_export','import_netlist'])assert.equal(requiresDocker('act',action),true);
  for(const action of ['stop','recover','finish','validate'])assert.equal(requiresDocker('act',action),false);
  for(const op of ['start','observe','query','retrieve','discover'])assert.equal(requiresDocker(op,'routing'),false);
});
test('concurrent readiness requests share one check and later requests check again',async()=>{
  let calls=0;const check=async()=>{calls++;await new Promise(r=>setTimeout(r,15));return {ready:true};};
  await Promise.all([ensureDockerReady(check),ensureDockerReady(check)]);assert.equal(calls,1);
  await ensureDockerReady(check);assert.equal(calls,2);
});
test('startup failure propagates before a stage and permits later recovery',async()=>{
  await assert.rejects(ensureDockerReady(async()=>{throw Error('DOCKER_ENGINE_UNAVAILABLE');}),/DOCKER_ENGINE_UNAVAILABLE/);
  assert.deepEqual(await ensureDockerReady(async()=>({ready:true})),{ready:true});
});
test('host timeout records cause and recovery invokes a non-launching probe once',async()=>{
  const args=[];
  const run=(exe,argv,options,callback)=>{
    args.push(argv);
    if(args.length===1){const e=Object.assign(Error('timeout'),{killed:true,signal:'SIGTERM'});callback(e,'','');}
    else callback(null,JSON.stringify({ready:true,engine:'linux/test'}),'');
  };
  const result=await probeWithRecovery(options=>probeDocker({...options,run}));
  assert.equal(result.ready,true);assert.match(result.recovered_after_preflight_error,/"killed":true/);
  assert.equal(args.length,2);assert.equal(args[0].includes('-ProbeOnly'),false);assert.equal(args[1].includes('-ProbeOnly'),true);
});
test('a confirmed unavailable engine does not enter recovery or pass',async()=>{
  let calls=0;
  await assert.rejects(probeWithRecovery(async()=>{calls++;throw Object.assign(Error('engine down'),{code:'DOCKER_ENGINE_UNAVAILABLE'});}),/engine down/);
  assert.equal(calls,1);
});
test('failed readonly recheck keeps both failures and never passes',async()=>{
  let calls=0;
  await assert.rejects(probeWithRecovery(async()=>{calls++;throw Object.assign(Error(calls===1?'host timeout':'engine down'),{code:calls===1?'DOCKER_PREFLIGHT_FAILED':'DOCKER_ENGINE_UNAVAILABLE'});}),/host timeout; readonly recheck: engine down/);
  assert.equal(calls,2);
});
