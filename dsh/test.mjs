import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {quotaGuard as liveQuotaGuard,context} from './main-plugin.mjs';
const quotaGuard=file=>liveQuotaGuard(file,{refresh:false});
test('weekly guard refuses unknown, low and stale quota',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'aieda-quota-'));
  const file=path.join(dir,'quota.json');
  try{
    for(const remainingPercent of [19,null,101]){
      await fs.writeFile(file,JSON.stringify({source:'codex_usage_limits',windowDurationMins:10080,checkedAt:Date.now(),remainingPercent}));
      await assert.rejects(quotaGuard(file));
    }
    await fs.writeFile(file,JSON.stringify({source:'codex_usage_limits',windowDurationMins:10080,checkedAt:Date.now(),remainingPercent:20}));
    assert.equal((await quotaGuard(file)).remainingPercent,20);
    await fs.writeFile(file,JSON.stringify({source:'codex_usage_limits',windowDurationMins:10080,checkedAt:0,remainingPercent:99}));
    await assert.rejects(quotaGuard(file),/QUOTA_STALE/);
    await fs.writeFile(file,'null');
    await assert.rejects(quotaGuard(file),/QUOTA_UNKNOWN/);
    await fs.writeFile(file,JSON.stringify({source:'codex_usage_limits',windowDurationMins:10080,checkedAt:Date.now(),remainingPercent:19}));
    await assert.rejects(quotaGuard(file),/QUOTA_STOP/);
  }finally{await fs.rm(dir,{recursive:true});}
});
test('cancelled quota floor preserves the official service gate',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'aieda-quota-'));
  const file=path.join(dir,'quota.json');
  const q={source:'codex_usage_limits',windowDurationMins:10080,checkedAt:Date.now(),remainingPercent:1,stopBelowPercent:null,ordinaryUsageAllowed:true};
  try{
    await fs.writeFile(file,JSON.stringify(q));
    assert.equal((await quotaGuard(file)).remainingPercent,1);
    await fs.writeFile(file,JSON.stringify({...q,ordinaryUsageAllowed:false}));
    await assert.rejects(quotaGuard(file),/QUOTA_STOP/);
    await fs.writeFile(file,JSON.stringify({...q,stopBelowPercent:'disabled'}));
    await assert.rejects(quotaGuard(file),/QUOTA_POLICY_INVALID/);
  }finally{await fs.rm(dir,{recursive:true});}
});

test('context bounds history, keeps contract and strips bulky evaluation records',()=>{
  const s={contract:{fixed:'must retain'},case:{case_id:'c'},counts:{},events:Array.from({length:100},()=>({action:{tool:'query'},result:{evaluation_records:['huge'],state_id:'old'}}))};
  const c=context(s,[]);assert.equal(c.contract.fixed,'must retain');
  assert.equal(c.memory.recent.length,4);assert.equal(c.memory.omitted_older_actions,96);
  assert.equal(c.memory.recent[0].result.evaluation_records,undefined);
});
