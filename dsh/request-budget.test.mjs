import test from 'node:test';
import assert from 'node:assert/strict';
import {turnKey,turnRequestCount,turnRequestLimit} from './request-budget.mjs';
const first=[{role:'user',id:'first',content:[{type:'text',text:'hi'}]}];
const second=[...first,{role:'user',id:'second',content:[{type:'text',text:'hi'}]}];
test('prior rounds including failed requests do not exhaust a new user round',()=>{
  const history=Array.from({length:12},()=>JSON.stringify({event:'request',messages:first})).join('\n');
  assert.equal(turnRequestCount(history,first),12);
  assert.equal(turnRequestCount(history,second),0);
});
test('tool results and assistant continuation retain the current round budget',()=>{
  const history=JSON.stringify({event:'request',turn_key:turnKey(first),messages:first});
  assert.equal(turnRequestCount(history,[...first,{role:'assistant',content:[]},{role:'tool',content:[]}]),1);
});
test('malformed request history cannot silently reset the budget',()=>{
  assert.throws(()=>turnRequestCount('broken',first),/记录损坏/);
});
test('full workflow uses frozen task budget with a hard framework ceiling',()=>{
  assert.equal(turnRequestLimit(null),20);
  assert.equal(turnRequestLimit({contract:{budget:{model_calls:40}}}),40);
  assert.equal(turnRequestLimit({contract:{budget:{model_calls:28}}}),28);
  assert.equal(turnRequestLimit({contract:{budget:{model_calls:999}}}),40);
  for(const value of [undefined,NaN,-1,0,1.2,'40'])assert.throws(()=>turnRequestLimit({contract:{budget:{model_calls:value}}}),/预算/);
});
