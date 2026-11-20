import {spawn} from 'node:child_process';
import path from 'node:path';
import {root} from '../dsh/runtime.mjs';
export function apiBridge(request,signal){return new Promise((resolve,reject)=>{
  const child=spawn(path.join(root,'.venv-agent/Scripts/python.exe'),[path.join(root,'ic-workbench','api_provider.py')],{cwd:root,windowsHide:true,stdio:['pipe','pipe','pipe'],env:{...process.env,PYTHONIOENCODING:'utf-8'}});
  let output='',settled=false;const abort=()=>child.kill();const timer=setTimeout(abort,210000);signal?.addEventListener('abort',abort,{once:true});
  const finish=(error,value)=>{if(settled)return;settled=true;clearTimeout(timer);signal?.removeEventListener('abort',abort);error?reject(error):resolve(value);};
  child.stdout.setEncoding('utf8');child.stdout.on('data',d=>{output+=d;if(output.length>4e6)abort();});child.stderr.on('data',()=>{});
  child.on('error',()=>finish(Error('API 连接进程不可用')));child.on('close',()=>{try{const r=JSON.parse(output);if(!r.ok)throw Error(r.error);finish(null,r.value);}catch(e){finish(Error(signal?.aborted?'请求已停止':e.message==='Unexpected end of JSON input'?'API 连接未返回完整结果':e.message));}});
  child.stdin.on('error',()=>{});child.stdin.end(JSON.stringify(request));if(signal?.aborted)abort();
});}
