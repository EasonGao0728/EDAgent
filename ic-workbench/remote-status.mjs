import {execFile} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import packages from './case-packages.json' with {type:'json'};

export {packages};
let latest, pending, inventory, inventoryPending;
async function probe(selected=null, signal, liveOnly=false) {
  const [config, script] = await Promise.all([
    readFile(process.env.EDAGENT_REMOTE_PROFILE || new URL('../environments/remote-server.json', import.meta.url), 'utf8')
      .then(text=>JSON.parse(text.replace(/^\uFEFF/,''))),
    readFile(new URL('./server_probe.py', import.meta.url), 'utf8')
  ]);
  if (config.enabled!==true || config.local_fallback!==false || !Number.isInteger(config.server_uid) || config.server_uid<=0
      || !/^[A-Za-z0-9][\w.-]*$/.test(config.ssh_host) || !/^(?:\/[\w-]+)+\/main-agent-remote-v1$/.test(config.server_root)) throw Error('invalid remote profile');
  const benchmarks = config.benchmark_root ?? '/srv/benchmarks/iBench/benchmarks';
  if (!/^(?:\/[\w.-]+)+$/.test(benchmarks) || benchmarks.split('/').some(part=>part==='.'||part==='..')) throw Error('invalid benchmark directory');
  return new Promise((resolve,reject)=>{
    const child=execFile('ssh',['-T','-o','BatchMode=yes','-o','ConnectTimeout=5',config.ssh_host,
      'cd '+config.server_root+' && python3 -B -'],{windowsHide:true,signal,timeout:liveOnly?14000:120000,maxBuffer:64000},(error,stdout)=>{
      if(error)return reject(Error(selected?'服务器输入核验失败，请检查连接和输入文件版本。':'服务器状态不可用'));
      try {const data=JSON.parse(stdout); if(selected){if(data.id!==selected || !data.hashes?.netlist)throw Error("invalid case audit");return resolve(data);} if(data.online!==true || !Array.isArray(data.cases) || !Number.isInteger(data.jobs))throw Error('invalid probe');resolve(data);} catch(e){reject(e);}
    });
    child.stdin.on('error',()=>{});const inventory=packages.filter(p=>p.assets && (!selected || p.id===selected));
    const payload=Buffer.from(JSON.stringify(inventory)).toString('base64');
    child.stdin.end(script.replace('CATALOG = []', "import base64\nCATALOG = json.loads(base64.b64decode('"+payload+"'))")
      .replace('SELECTED = None', 'SELECTED = '+(selected?JSON.stringify(selected):'None'))
      .replace('LIVE_ONLY = False', 'LIVE_ONLY = '+(liveOnly?'True':'False'))
      .replace('Path("/srv/benchmarks/iBench/benchmarks")','Path('+JSON.stringify(benchmarks)+')'));
  });
}
export function remoteStatus({fresh=false}={}) {
  if(!inventory || Date.now()-inventory.catalogCheckedAt>300000){
    inventoryPending??=probe().then(({cases,runnable_cases,qualifications,readiness})=>{
      inventory={cases,runnable_cases,qualifications,readiness,catalogCheckedAt:Date.now()};
    }).catch(()=>{}).finally(()=>{inventoryPending=null;});
  }
  const snapshot=data=>({...data,...inventory,catalogPending:!inventory});
  if(!fresh&&latest && Date.now()-latest.checkedAt<20000)return snapshot(latest);
  pending??=probe(null,undefined,true).catch(()=>({online:false,cases:[],runnable_cases:[],jobs:null}))
    .then(data=>latest={...data,checkedAt:Date.now()}).finally(()=>{pending=null;});
  return pending.then(snapshot);
}

export function auditCase(id,signal){
  if(!packages.some(p=>p.id===id && p.assets))throw Error('未知的案例');
  return probe(id,signal);
}
