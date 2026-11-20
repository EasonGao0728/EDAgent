import test from 'node:test';
import assert from 'node:assert/strict';
import {makeDesktopBridge} from './auth-recovery.mjs';

test('expired authorization opens one recovery window and never replays the failed request',async()=>{
  const calls=[];
  const bridge=makeDesktopBridge(async req=>{
    calls.push(req.mode);
    if(req.mode==='auth_window')return {requested:true};
    throw Object.assign(Error('AUTH_REQUIRED'),{requiresLogin:true,code:'sign_in_required'});
  },()=>100);
  await assert.rejects(bridge({mode:'native_model'}),/登录与连接/);
  await assert.rejects(bridge({mode:'native_model'}),/chatgpt-login.cmd/);
  assert.deepEqual(calls,['native_model','auth_window','native_model']);
});

test('network, quota and Windows permission errors do not trigger login',async()=>{
  for(const code of ['network_error','PermissionError','QUOTA_UNAVAILABLE']){
    const calls=[];
    const bridge=makeDesktopBridge(async req=>{calls.push(req.mode);throw Object.assign(Error(code),{code});});
    await assert.rejects(bridge({mode:'native_model'}),new RegExp(code));
    assert.deepEqual(calls,['native_model']);
  }
});

test('launch failure preserves original error and offers manual entry',async()=>{
  const bridge=makeDesktopBridge(async req=>{
    if(req.mode==='auth_window')throw Error('permission denied');
    throw Object.assign(Error('AUTH_REQUIRED'),{requiresLogin:true,code:'sign_in_required'});
  });
  await assert.rejects(bridge({mode:'models'}),e=>e.code==='sign_in_required' && /启动失败/.test(e.message) && /chatgpt-login.cmd/.test(e.message));
});

test('cancelled request does not open recovery UI',async()=>{
  const calls=[];const controller=new AbortController();controller.abort();
  const bridge=makeDesktopBridge(async req=>{calls.push(req.mode);throw Object.assign(Error('auth'),{requiresLogin:true});});
  await assert.rejects(bridge({mode:'native_model'},controller.signal));
  assert.deepEqual(calls,['native_model']);
});
