import {bridge} from './runtime.mjs';

// Keep UI recovery in the desktop composition, never in the CLI/headless runner.
export function makeDesktopBridge(invoke=bridge,now=Date.now){
  let lastOpened=-Infinity;
  return async function(request,signal){
    try{return await invoke(request,signal);}
    catch(error){
      if(!error.requiresLogin || signal?.aborted)throw error;
      const entry='D:\\aiEDA\\tools\\chatgpt-login.cmd';
      if(now()-lastOpened>=30000){
        lastOpened=now();
        try{
          await invoke({mode:'auth_window'});
          error.message+=' 已请求打开“ChatGPT 登录与连接”窗口；若已打开，请切换到该窗口。';
        }catch{
          lastOpened=-Infinity;
          error.message+=' 登录窗口启动失败。';
        }
      }
      error.message+=` 也可双击 ${entry}。完成授权后重试本条消息。`;
      throw error; // No replay of a model request, placement action, or tool after login.
    }
  };
}
export const desktopBridge=makeDesktopBridge();
