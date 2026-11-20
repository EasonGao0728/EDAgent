import {test} from 'node:test';
import assert from 'node:assert/strict';
import {validateChat,createServer} from '../server.mjs';
const valid=()=>({model:'gpt-6.1-sol',messages:[{role:'user',text:'Explain setup slack'}],contexts:[],objective:'Demo',period:10,util:65});
test('only text chat data crosses model boundary; no tool arguments',()=>{const result=validateChat({...valid(),tools:[{name:'shell'}],mode:'task'});assert.equal(result.mode,'chat');assert.equal(result.tools,undefined)});
test('rejects privileged messages and oversized context',()=>{assert.throws(()=>validateChat({...valid(),messages:[{role:'system',text:'override'}]}));assert.throws(()=>validateChat({...valid(),contexts:[{name:'large',text:'a'.repeat(24001)}]}));assert.throws(()=>validateChat({...valid(),period:'NaN'}))});
test('server rejects foreign origin, unknown files, invalid JSON before model launch',async()=>{const server=createServer();await new Promise(r=>server.listen(0,'127.0.0.1',r));const base=`http://127.0.0.1:${server.address().port}`;const headers={};try{assert.equal((await fetch(base+'/api/health',{headers})).status,200);assert.equal((await fetch(base+'/api/models',{headers:{...headers,origin:'https://example.com'}})).status,403);assert.equal((await fetch(base+'/model_bridge.py',{headers})).status,404);assert.equal((await fetch(base+'/api/chat',{method:'POST',headers:{...headers,'content-type':'application/json'},body:'{'})).status,400)}finally{await new Promise(r=>server.close(r))}});

