import test from 'node:test';
import assert from 'node:assert/strict';
import {checkRequestQuota} from './quota-request-policy.mjs';
const unavailable = () => {throw Error('host bridge: ValueError: QUOTA_UNAVAILABLE: connection failed');};
const run = (threshold, refresh, record) => checkRequestQuota({readPolicy:async()=>({stopBelowPercent:threshold}),refresh,record});

test('cancelled percentage floor exposes unknown quota without a success snapshot',async()=>{
  let recorded;
  const q=await run(null,unavailable,async value=>{recorded=value;});
  assert.equal(q.source,'unavailable');assert.equal(q.remainingPercent,null);
  assert.equal(q.checkedAt,null);assert.equal(q.ordinaryUsageAllowed,null);
  assert.equal(q.providerAuthorizationRequired,true);assert.equal(q.budgetCheckEnforced,false);
  assert.deepEqual(recorded,q);
});
test('active or omitted percentage budget still fails closed on unavailable quota',async()=>{
  for(const threshold of [undefined,0,20,100])await assert.rejects(run(threshold,unavailable),/QUOTA_UNAVAILABLE/);
});
test('account, known service denial, login and unexpected errors are never softened',async()=>{
  for(const code of ['QUOTA_ACCOUNT_MISMATCH','QUOTA_STOP','QUOTA_UNKNOWN','QUOTA_POLICY_INVALID','QUOTA_LAUNCH_FAILED','sign_in_required','AbortError'])
    await assert.rejects(run(null,()=>{throw Error(code+': no');}),new RegExp(code));
  await assert.rejects(run(null,async()=>({ordinaryUsageAllowed:false})),/QUOTA_STOP/);
  await assert.rejects(run(20,async()=>({remainingPercent:11,ordinaryUsageAllowed:true})),/QUOTA_STOP/);
  await assert.rejects(run(20,async()=>({remainingPercent:null,ordinaryUsageAllowed:true})),/QUOTA_UNKNOWN/);
});
test('invalid policy refuses a request before calling its reader',async()=>{
  for(const threshold of ['disabled',NaN,-1,101])await assert.rejects(run(threshold,()=>{assert.fail('reader called');}),/QUOTA_POLICY_INVALID/);
});
test('successful live snapshot preserves true values and policy state',async()=>{
  const live={source:'codex_usage_limits',remainingPercent:11,checkedAt:123,ordinaryUsageAllowed:true};
  const q=await run(null,async()=>live);assert.equal(q.remainingPercent,11);assert.equal(q.availability,'available');
  assert.equal((await run(20,async()=>({...live,remainingPercent:70}))).budgetCheckEnforced,true);
});
test('missing policy and audit storage failure stay visible',async()=>{
  await assert.rejects(checkRequestQuota({readPolicy:()=>{throw Error('missing policy');},refresh:unavailable}),/missing policy/);
  await assert.rejects(run(null,unavailable,()=>{throw Error('audit write failed');}),/audit write/);
});
