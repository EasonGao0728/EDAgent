import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {existsSync,readFileSync,statSync} from 'node:fs';
import {isCatalogReadError} from './catalog-read-error.mjs';
import {resourceTransport} from './resource-transport.mjs';
export const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const base=new URL('../.cache/dsh-runtime/dsh/node_modules/@deepseek-ai/',import.meta.url);
export async function pkg(name){
  if(!/^[a-z][a-z0-9-]*$/.test(name))throw Error('Invalid DSH package name');
  const bundled=new URL(`${name}/lib/index.js`,base);
  return existsSync(bundled)?import(bundled):import('@deepseek-ai/'+name);
}
export function bridge(request, signal){
  return new Promise((resolve,reject)=>{
    const remote=['task','ieda_status','ieda_run'].includes(request.mode);
    const transport=remote?{args:['-m','macro_agent.remote_client'],taskTimeoutMs:150000}:resourceTransport(root,request);
    const child=spawn(path.join(root,'.venv-agent/Scripts/python.exe'),transport.args,
      {cwd:root,windowsHide:true,stdio:['pipe','pipe','pipe'],env:{...process.env,PYTHONIOENCODING:'utf-8'}});
    let out='',err='';
    const cancel=()=>child.kill();
    signal?.addEventListener('abort',cancel,{once:true});
    // Remote requests only submit/query durable jobs. Aborting SSH does not
    // cancel server computation; cancellation requires the scoped job API.
    const timer=setTimeout(cancel,remote?(request.operation==='download'?660000:150000):210000);
    child.stdout.on('data',d=>{out+=d;if(out.length>4000000)cancel();});
    child.stderr.on('data',d=>{err=(err+d).slice(-1000);});
    child.on('error',reject);
    child.on('close',()=>{
      clearTimeout(timer);signal?.removeEventListener('abort',cancel);
      try{const r=JSON.parse(out);if(!r.ok){
        const e=Error(r.error);e.code=r.code;e.requiresLogin=r.requires_login===true;
        if(r.code==='invalid_json_response'){
          try{
            const file=path.join(root,'runs','dsh-host-last-error.json');
            if(statSync(file).size<=32768)e.retryableCatalogRead=isCatalogReadError(request,r,JSON.parse(readFileSync(file,'utf8')),root);
          }catch{/* Missing, changed or malformed diagnostics fail closed. */}
        }
        throw e;
      }resolve(r.value);}
      catch(e){const wrapped=Error(`host bridge: ${e.message}; ${err}`);wrapped.code=e.code;wrapped.requiresLogin=e.requiresLogin;wrapped.retryableCatalogRead=e.retryableCatalogRead===true;reject(wrapped);}
    });
    child.stdin.end(JSON.stringify(request));
    if(signal?.aborted)cancel();
  });
}
