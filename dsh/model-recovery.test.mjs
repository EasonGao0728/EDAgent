import test from 'node:test';
import assert from 'node:assert/strict';
import {modelWithRecovery} from './model-recovery.mjs';
const failure=code=>Object.assign(Error(code),{code});
test('transient connection failure retries with a fresh quota/budget reservation',async()=>{
  let reserved=0,invoked=0;
  const result=await modelWithRecovery({beforeAttempt:async()=>{reserved++;},invoke:async()=>{if(++invoked<3)throw failure('network_error');return 'done';},pause:async()=>{}});
  assert.equal(result,'done');assert.equal(reserved,3);assert.equal(invoked,3);
});
test('quota stop during recovery prevents another model request',async()=>{
  let reserved=0,invoked=0;
  await assert.rejects(modelWithRecovery({beforeAttempt:async()=>{if(++reserved===2)throw Error('QUOTA_STOP');},invoke:async()=>{invoked++;throw failure('network_error');},pause:async()=>{}}),/QUOTA_STOP/);
  assert.equal(invoked,1);
});
test('stream, auth and permanent network failures never loop indefinitely',async()=>{
  for(const [code,expected] of [['stream_interrupted',1],['sign_in_required',1],['network_error',3]]){
    let invoked=0;
    await assert.rejects(modelWithRecovery({beforeAttempt:async()=>{},invoke:async()=>{invoked++;throw failure(code);},pause:async()=>{}}));
    assert.equal(invoked,expected);
  }
});

test('known upstream outages get bounded model-only recovery, unknown stream failures stay paused',async()=>{
  for(const [code,httpStatus,expected] of [['server_error',null,3],['remote_error',503,3],['remote_error',null,1],['remote_error',400,1]]){
    const retries=[];let invoked=0;
    await assert.rejects(modelWithRecovery({beforeAttempt:async()=>{},invoke:async()=>{invoked++;throw Object.assign(Error(code),{code,httpStatus});},
      onRetry:async e=>retries.push(e.nextAttempt),pause:async()=>{}}));
    assert.equal(invoked,expected);assert.deepEqual(retries,expected===3?[2,3]:[]);
  }
});
