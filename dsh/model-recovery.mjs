import {setTimeout as delay} from 'node:timers/promises';

// Only pre-stream transport or proven model-catalog GET failures are retried. Tool execution is outside
// this function; stream interruption/auth/quota/validation failures propagate.
export async function modelWithRecovery({beforeAttempt,invoke,signal,pause=delay}){
  for(let attempt=0;attempt<3;attempt++){
    signal?.throwIfAborted();
    await beforeAttempt(attempt); // Recheck quota and reserve/log every attempt.
    try{return await invoke();}
    catch(error){
      const retryable=error.code==='network_error'||(error.code==='invalid_json_response'&&error.retryableCatalogRead===true);
      if(!retryable||attempt===2||signal?.aborted)throw error;
      await pause(1000*(attempt+1),undefined,{signal});
    }
  }
}
