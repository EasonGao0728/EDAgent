import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import {resourceTransport} from './resource-transport.mjs';
const root=path.resolve('.');
const run=path.join(root,'runs/dsh-desktop-4247ed3bc3eefbe0/main-task');
const deps=state=>({stat:()=>({size:1000}),read:()=>JSON.stringify(state)});
test('ordinary tasks and model calls keep the original transport',()=>{
  assert.equal(resourceTransport(root,{mode:'native_model',run}).taskTimeoutMs,21630000);
  assert.equal(resourceTransport(root,{mode:'task',run:path.join(root,'runs/other')}).args[0],'-m');
  assert.equal(resourceTransport(root,{mode:'task',run},deps({})).args[0],'-m');
});
test('only the approved Core state selects the extended task worker',()=>{
  const r=resourceTransport(root,{mode:'task',run},deps({resource_continuation:{routing_seconds:64800,continuation_seconds:72000}}));
  assert.deepEqual(r,{args:['tools/dsh_resource_host.py'],taskTimeoutMs:64830000});
});
test('malformed or enlarged resource requests fail closed',()=>{
  assert.throws(()=>resourceTransport(root,{mode:'task',run},deps({resource_continuation:{routing_seconds:999999}})));
  assert.throws(()=>resourceTransport(root,{mode:'task',run},{stat:()=>({size:9*1024*1024})}));
});
