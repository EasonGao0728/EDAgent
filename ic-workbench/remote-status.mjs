import {execFile} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import packages from './case-packages.json' with {type:'json'};

export {packages};
let latest, pending;
async function probe(selected=null, signal) {
  const [config, script] = await Promise.all([
    readFile(new URL('../environments/remote-server.json', import.meta.url), 'utf8').then(JSON.parse),
    readFile(new URL('./server_probe.py', import.meta.url), 'utf8')
  ]);
  if (!config.enabled || !/^[\w][\w.-]*$/.test(config.ssh_host) || !/^\/[\w/-]+$/.test(config.server_root)) throw Error('invalid remote profile');
  return new Promise((resolve,reject)=>{
    const child=execFile('ssh',['-T','-o','BatchMode=yes','-o','ConnectTimeout=5',config.ssh_host,
      'cd '+config.server_root+' && python3 -B -'],{windowsHide:true,signal,timeout:selected?120000:14000,maxBuffer:64000},(error,stdout)=>{
      if(error)return reject(Error(selected?'服务器输入核验失败，请检查连接和输入文件版本。':'服务器状态不可用'));
      try {const data=JSON.parse(stdout); if(selected){if(data.id!==selected || !data.hashes?.netlist)throw Error("invalid case audit");return resolve(data);} if(data.online!==true || !Array.isArray(data.cases) || !Number.isInteger(data.jobs))throw Error('invalid probe');resolve(data);} catch(e){reject(e);}
    });
    child.stdin.on('error',()=>{});const inventory=packages.filter(p=>p.assets && (!selected || p.id===selected));
    const payload=Buffer.from(JSON.stringify(inventory)).toString('base64');
    child.stdin.end(script.replace('CATALOG = []', "import base64\nCATALOG = json.loads(base64.b64decode('"+payload+"'))")
      .replace('SELECTED = None', 'SELECTED = '+(selected?JSON.stringify(selected):'None')));
  });
}
export function remoteStatus() {
  if(latest && Date.now()-latest.checkedAt<20000)return latest;
  pending??=probe().catch(()=>({online:false,cases:[],jobs:null})).then(data=>latest={...data,checkedAt:Date.now()}).finally(()=>{pending=null;});
  return pending;
}

export function auditCase(id,signal){
  if(!packages.some(p=>p.id===id && p.assets))throw Error('未知的案例');
  return probe(id,signal);
}
