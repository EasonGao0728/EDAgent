import test from 'node:test';
import assert from 'node:assert/strict';
import {isCatalogReadError} from './catalog-read-error.mjs';
import {modelWithRecovery} from './model-recovery.mjs';
const root='D:/aiEDA';
const req={mode:'native_model'};
const reply={code:'invalid_json_response',error:'OpenAIError [诊断 abcdef123456，runs/dsh-host-errors.jsonl]'};
const diagnostic={id:'abcdef123456',mode:'native_model',code:'invalid_json_response',frames:[
 {file:root+'/macro_agent/chatgpt_provider.py',function:'models'},
 {file:root+'/macro_agent/openai_http.py',function:'json'}]};
test('only the matching direct model-catalog JSON diagnostic is retryable',()=>{
 assert.equal(isCatalogReadError(req,reply,diagnostic,root),true);
 for(const changed of [{...diagnostic,id:'111111111111'},
  {...diagnostic,frames:[{file:root+'/macro_agent/chatgpt_auth.py',function:'refresh'},diagnostic.frames[1]]},
  {...diagnostic,mode:'task'}])assert.equal(isCatalogReadError(req,reply,changed,root),false);
 assert.equal(isCatalogReadError({mode:'task'},reply,diagnostic,root),false);
});
test('catalog recovery reserves each attempt and remains bounded',async()=>{
 let invoked=0,reserved=0;
 await assert.rejects(modelWithRecovery({beforeAttempt:async()=>{reserved++;},invoke:async()=>{invoked++;throw Object.assign(Error('catalog'),{code:'invalid_json_response',retryableCatalogRead:true});},pause:async()=>{}}));
 assert.equal(invoked,3);assert.equal(reserved,3);
});
test('unclassified invalid JSON is never retried',async()=>{
 let invoked=0;
 await assert.rejects(modelWithRecovery({beforeAttempt:async()=>{},invoke:async()=>{invoked++;throw Object.assign(Error('json'),{code:'invalid_json_response'});},pause:async()=>{}}));
 assert.equal(invoked,1);
});
