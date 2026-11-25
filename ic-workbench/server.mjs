import {inspectUploadPackage} from './upload-check.mjs';
import {placementView} from './placement-preview.mjs';
import {packages, remoteStatus} from './remote-status.mjs';
import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {AgentHub} from './agent-runtime.mjs';
import {bridge as dshBridge} from '../dsh/runtime.mjs';
import {apiBridge} from './provider.mjs';
import {modelWithRecovery} from '../dsh/model-recovery.mjs';
import {catalog,searchTools} from '../dsh/tool-library.mjs';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.dirname(here);
const port=Number(process.env.SILICON_PORT||4173);
const python=process.env.SILICON_PYTHON||path.join(root,'.venv-agent','Scripts','python.exe');
let active=false;
export function validateChat(body){
  if(!body||typeof body!=='object'||typeof body.model!=='string'||!/^gpt-[\w.-]{1,70}$/.test(body.model))throw Error('invalid_model');
  if(!Array.isArray(body.messages)||!body.messages.length||body.messages.length>16)throw Error('invalid_messages');
  if(body.messages.some(m=>!['user','assistant'].includes(m.role)||typeof m.text!=='string'||m.text.length>16000))throw Error('invalid_message');
  if(!Array.isArray(body.contexts)||body.contexts.some(c=>typeof c.name!=='string'||typeof c.text!=='string')||body.contexts.reduce((n,c)=>n+c.text.length,0)>24000)throw Error('context_too_large');
  if(typeof body.objective!=='string'||body.objective.length>3000)throw Error('invalid_objective');
  if(!Number.isFinite(Number(body.period))||Number(body.period)<=0||Number(body.period)>10000)throw Error('invalid_period');
  if(!Number.isFinite(Number(body.util))||Number(body.util)<10||Number(body.util)>95)throw Error('invalid_utilization');
  return {mode:'chat',model:body.model,messages:body.messages,contexts:body.contexts,objective:body.objective,period:body.period,util:body.util};
}
const json=(res,status,data)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(data))};
function bridge(req,res,body,stream){
  if(active)return json(res,409,{error:'已有模型请求进行中，请稍候'});
  active=true;
  const child=spawn(python,[path.join(here,'model_bridge.py')],{cwd:root,windowsHide:true,stdio:['pipe','pipe','pipe'],env:{...process.env,PYTHONIOENCODING:'utf-8'}});
  let output='',terminal=false,finished=false;
  const finish=()=>{if(finished)return;finished=true;active=false;clearTimeout(timer)};
  const timer=setTimeout(()=>{terminal=true;if(stream){res.write(JSON.stringify({type:'error',error:'request_timeout'})+'\n');res.end()}else json(res,504,{error:'request_timeout'});child.kill();finish()},195000);
  if(stream)res.writeHead(200,{'Content-Type':'application/x-ndjson; charset=utf-8','Cache-Control':'no-store','X-Accel-Buffering':'no'});
  child.stdout.setEncoding('utf8');
  child.stdout.on('data',data=>{if(res.destroyed)return;if(stream)res.write(data);else{output+=data;if(output.length>200000){child.kill();json(res,502,{error:'catalog_too_large'});finish()}}});
  child.stderr.on('data',()=>{}); // Never forward internal diagnostics or credentials.
  child.on('error',()=>{if(!terminal&&!res.destroyed){if(stream)res.end(JSON.stringify({type:'error',error:'model_runtime_unavailable'})+'\n');else json(res,503,{error:'model_runtime_unavailable'})}finish()});
  child.on('close',()=>{if(finished)return;if(!res.destroyed&&!terminal){if(stream)res.end();else{try{const value=JSON.parse(output.trim());json(res,value.error?502:200,value)}catch{json(res,502,{error:'invalid_model_response'})}}}finish()});
  res.on('close',()=>{if(!finished){child.kill();finish()}});
  child.stdin.on('error',()=>{});
  child.stdin.end(JSON.stringify(body));
}
export function createServer({hub=new AgentHub()}={}){let ready;return http.createServer(async(req,res)=>{
  const listeningPort=req.socket.localPort;
  const allowedHosts=new Set([`127.0.0.1:${listeningPort}`,`localhost:${listeningPort}`]);
  if(!allowedHosts.has(req.headers.host))return json(res,403,{error:'invalid_host'});
  if(req.headers.origin&&!new Set([`http://127.0.0.1:${listeningPort}`,`http://localhost:${listeningPort}`]).has(req.headers.origin))return json(res,403,{error:'cross_origin_denied'});
  res.setHeader('X-Content-Type-Options','nosniff');
  res.setHeader('Referrer-Policy','no-referrer');
  const url=new URL(req.url,`http://127.0.0.1:${port}`);
  if(url.pathname==='/api/health')return json(res,200,{ok:true,edaConnected:null,source:'shared-dsh-main-agent',execution:'remote-server',defaultModel:'gpt-6-astra',defaultEffort:'high'});
  if(req.method==='GET' && url.pathname==='/api/remote-status'){
    const remote=await remoteStatus();
    return json(res,200,{...remote,native_jobs:remote.jobs,active_agent_sessions:hub.active.size});
  }
  if(req.method==='GET' && url.pathname==='/api/case-packages')return json(res,200,{packages});
  if(url.pathname.startsWith('/api/agent')||url.pathname.startsWith('/api/sessions')||url.pathname.startsWith('/api/providers')){
    try{
      ready??=hub.init();await ready;
      const body=async(limit=180000)=>{if(!req.headers['content-type']?.startsWith('application/json'))throw Error('json_required');let size=0,parts=[];for await(const c of req){size+=c.length;if(size>limit)throw Error('request_too_large');parts.push(c);}return JSON.parse(Buffer.concat(parts).toString('utf8'));};
      if(url.pathname==='/api/agent/models'&&req.method==='GET'){const models=await modelWithRecovery({beforeAttempt:async()=>{},invoke:()=>dshBridge({mode:'models'})});return json(res,200,{models:models.filter(m=>/^gpt-6/.test(m.slug))});}
      if(url.pathname==='/api/agent/tools'&&req.method==='GET')return json(res,200,catalog());
      if(url.pathname==='/api/agent/tools/search'&&req.method==='POST'){const b=await body(6000);return json(res,200,await searchTools(b.query,{stage:b.stage||undefined,topK:b.top_k??5}));}
      if(url.pathname==='/api/providers'&&req.method==='GET')return json(res,200,await apiBridge({mode:'status'}));
      if(url.pathname==='/api/providers/login'&&req.method==='POST'){await body();return json(res,200,await dshBridge({mode:'auth_window'}));}
      if(url.pathname==='/api/providers/api'&&req.method==='POST'){const b=await body(12000);if(hub.active.size)throw Error('请在所有模型请求结束后修改连接');return json(res,200,await apiBridge({mode:'save',base_url:b.base_url,protocol:b.protocol,key:b.key,models:b.models}));}
      if(url.pathname==='/api/providers/check'&&req.method==='POST'){await body();return json(res,200,await apiBridge({mode:'check'}));}
      if(url.pathname==='/api/sessions'&&req.method==='GET')return json(res,200,{sessions:hub.list()});
      if(url.pathname==='/api/sessions'&&req.method==='POST'){await body();return json(res,201,await hub.create());}
      const match=url.pathname.match(/^\/api\/sessions\/(silicon-[a-f0-9-]+)(?:\/(turn|upload|input-check|refresh|short-quality|stop|cancel-job|artifacts)(?:\/([^/]+))?)?$/);
      if(!match)return json(res,404,{error:'not_found'});
      const [,id,action,name]=match;
      if(!action&&req.method==='GET')return json(res,200,hub.view(hub.session(id)));
      if(action==='artifacts'&&name&&req.method==='GET'){
        const {data,ref}=await hub.artifact(id,decodeURIComponent(name));const inline=/\.(svg|html)$/.test(ref.name)&&!url.searchParams.has('download');
        res.writeHead(200,{'Content-Type':ref.name.endsWith('.svg')?'image/svg+xml':ref.name.endsWith('.html')?'text/html; charset=utf-8':'application/octet-stream','Content-Disposition':`${inline?'inline':'attachment'}; filename="${ref.name}"`,'Content-Security-Policy':"sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'self'",'Cache-Control':'no-store'});return res.end(inline && ref.kind==='preview' && ref.name==='placement.svg' && url.searchParams.get('view')==='compact' ? placementView(data) : data);
      }
      if(req.method!=='POST')return json(res,405,{error:'method_not_allowed'});
      if(action==='upload'){
        if(req.headers['content-type']!=='application/octet-stream')throw Error('binary_required');const file=url.searchParams.get('name');const max=file==='sky130_fd_sc_hs__tt_025C_1v80.lib'?80*1024*1024:20*1024*1024;let size=0,parts=[];
        for await(const chunk of req){size+=chunk.length;if(size>max)return json(res,413,{error:'附件超过大小限制'});parts.push(chunk);}
        return json(res,201,await hub.addUpload(id,file,Buffer.concat(parts)));
      }
      const b=await body();
      if(action==='input-check'){
        if(!Array.isArray(b.attachments)||b.attachments.length>16)throw Error('每轮最多 16 个文件');
        const uploads=hub.session(id).uploads;
        const files=b.attachments.map(key=>{const ref=uploads.find(f=>f.attachmentId===key);if(!ref)throw Error('文件不属于当前会话');return ref;});
        return json(res,200,await inspectUploadPackage(files));
      }
      if(action==='turn')return json(res,202,await hub.submit(id,b));
      if(action==='refresh')return json(res,200,await hub.refresh(id));
      if(action==='short-quality')return json(res,200,await hub.shortQuality(id,b.action));
      if(action==='stop')return json(res,200,await hub.stop(id));
      if(action==='cancel-job')return json(res,200,await hub.cancelJob(id));
      return json(res,404,{error:'not_found'});
    }catch(e){return json(res,400,{error:e instanceof SyntaxError?'invalid_json':e.message});}
  }
  if(url.pathname==='/api/models'&&req.method==='GET')return bridge(req,res,{mode:'models'},false);
  if(url.pathname==='/api/chat'&&req.method==='POST'){
    if(!req.headers['content-type']?.startsWith('application/json'))return json(res,415,{error:'json_required'});
    try{let size=0;const chunks=[];for await(const c of req){size+=c.length;if(size>180000)return json(res,413,{error:'request_too_large'});chunks.push(c)}const body=validateChat(JSON.parse(Buffer.concat(chunks).toString('utf8')));return bridge(req,res,body,true)}catch(e){return json(res,400,{error:e instanceof SyntaxError?'invalid_json':e.message})}
  }
  const files={'/':'agent.html','/index.html':'agent.html','/markdown.js':'markdown.js','/agent-app.js':'agent-app.js','/agent.css':'agent.css','/prototype':'index.html','/app.js':'app.js','/style.css':'style.css','/chat.css':'chat.css','/session-seed.json':'session-seed.json'};
  if(req.method!=='GET'||!files[url.pathname])return json(res,404,{error:'not_found'});
  try{const file=files[url.pathname],data=await readFile(path.join(here,'public',file));res.writeHead(200,{'Content-Type':file.endsWith('.js')?'text/javascript; charset=utf-8':file.endsWith('.css')?'text/css; charset=utf-8':file.endsWith('.json')?'application/json; charset=utf-8':'text/html; charset=utf-8','Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'"});res.end(data)}catch{json(res,500,{error:'asset_unavailable'})}
})}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))createServer().listen(port,'127.0.0.1',()=>console.log(`SILICON listening at http://127.0.0.1:${port}`));
