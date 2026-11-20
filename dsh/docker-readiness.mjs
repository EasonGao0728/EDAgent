import {execFile} from 'node:child_process';
import path from 'node:path';
import {root} from './runtime.mjs';

export const nativeTaskActions=new Set(['import_netlist','floorplan','macro_placement','fanout','placement','export_def','cts','to_drv','to_hold','legalization','routing','filler','drc','timing','gds_export','routed_readback']);
export function requiresDocker(operation,action){return operation==='act' && nativeTaskActions.has(action);}
export function probeDocker({run=execFile,probeOnly=false}={}){
  return new Promise((resolve,reject)=>{
    run(path.join(process.env.SystemRoot||'C:\\Windows','System32','WindowsPowerShell','v1.0','powershell.exe'),
      ['-NoProfile','-NonInteractive','-File',path.join(root,'tools','start-ieda-docker.ps1'),'-WaitSeconds',probeOnly?'0':'90','-Json',...(probeOnly?['-ProbeOnly']:[])],
      {windowsHide:true,timeout:probeOnly?15000:110000,maxBuffer:16000,encoding:'utf8'},(error,stdout,stderr)=>{
        let result;
        try{result=JSON.parse(stdout.trim());}catch{
          const detail={code:error?.code??null,signal:error?.signal??null,killed:error?.killed===true,probeOnly};
          const e=Error('DOCKER_PREFLIGHT_FAILED: '+JSON.stringify(detail)+' '+(stderr||error?.message||'invalid readiness result').slice(-1200));
          e.code='DOCKER_PREFLIGHT_FAILED';e.diagnostic=detail;reject(e);return;
        }
        if(result.ready===true && !error){resolve(result);return;}
        const e=Error(`${result.code||'DOCKER_ENGINE_UNAVAILABLE'}: ${result.message||'Engine is not ready'}`);e.code=result.code;reject(e);
      });
  });
}
export async function probeWithRecovery(check=probeDocker){
  try{return await check();}catch(first){
    // Recheck only the engine after an unreadable/timed-out host probe.
    // Never restart Docker or repeat a native EDA action in this recovery.
    if(first.code!=='DOCKER_PREFLIGHT_FAILED')throw first;
    try{return {...await check({probeOnly:true}),recovered_after_preflight_error:first.message};}
    catch(second){const e=Error(first.message+'; readonly recheck: '+second.message);e.code=second.code||first.code;throw e;}
  }
}
let pending;
export async function ensureDockerReady(check=probeWithRecovery){
  // Concurrent tool attempts share one bounded startup; no process killing,
  // socket deletion, factory reset or persistent daemon reconfiguration.
  if(!pending)pending=Promise.resolve().then(check).finally(()=>{pending=undefined;});
  return pending;
}
