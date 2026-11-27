import {setTimeout as delay} from 'node:timers/promises';

// No tool dispatch occurs here. Partial streams and unclassified errors propagate.
export async function modelWithRecovery({beforeAttempt,invoke,signal,pause=delay,onRetry}){
  for(let attempt=0;attempt<3;attempt++){
    signal?.throwIfAborted();
    await beforeAttempt(attempt); // Recheck quota and reserve/log every attempt.
    try{return await invoke();}
    catch(error){
      const transientService=error.code==='server_error'||(['http_error','remote_error'].includes(error.code)&&[502,503,504].includes(error.httpStatus));
      const retryable=error.code==='network_error'||transientService||(error.code==='invalid_json_response'&&error.retryableCatalogRead===true);
      if(!retryable||attempt===2||signal?.aborted)throw error;
      await onRetry?.({code:error.code,nextAttempt:attempt+2});
      await pause(3000*(2**attempt),undefined,{signal});
    }
  }
}
