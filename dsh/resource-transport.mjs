// Scoped, user-authorized resource continuation. Python verifies the full audit.
import path from 'node:path';
import {readFileSync,statSync} from 'node:fs';
export function resourceTransport(root,request,{read=readFileSync,stat=statSync}={}){
  const standard={args:['-m','macro_agent.dsh_host'],taskTimeoutMs:21630000};
  const target=path.resolve(root,'runs/dsh-desktop-4247ed3bc3eefbe0/main-task');
  if(request.mode!=='task'||path.resolve(request.run||'.')!==target)return standard;
  const file=path.join(target,'task.json');
  if(stat(file).size>8*1024*1024)throw Error('Task state exceeds resource-transport limit');
  const state=JSON.parse(read(file,'utf8'));
  if(!state.resource_continuation)return standard;
  if(state.resource_continuation.routing_seconds!==64800||state.resource_continuation.continuation_seconds!==72000)
    throw Error('Invalid Core resource-extension values');
  return {args:['tools/dsh_resource_host.py'],taskTimeoutMs:64830000};
}
