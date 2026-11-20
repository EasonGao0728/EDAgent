import path from 'node:path';

// Retry only a proven GET /models parse failure before Responses was called.
// Token exchange, authentication JSON and generated/tool JSON are excluded.
export function isCatalogReadError(request,reply,diagnostic,root){
  if(request.mode!=='native_model'||reply.code!=='invalid_json_response')return false;
  const d=diagnostic;
  if(!d||d.mode!=='native_model'||d.code!==reply.code||!/^[a-f0-9]{12}$/.test(d.id||''))return false;
  if(!String(reply.error).includes(`[诊断 ${d.id}，runs/dsh-host-errors.jsonl]`))return false;
  if(!Array.isArray(d.frames)||d.frames.length<2)return false;
  const [caller,leaf]=d.frames.slice(-2);
  const same=(file,name)=>typeof file==='string'&&path.resolve(file).toLowerCase()===path.resolve(root,'macro_agent',name).toLowerCase();
  return caller.function==='models'&&same(caller.file,'chatgpt_provider.py')&&
    leaf.function==='json'&&same(leaf.file,'openai_http.py');
}
