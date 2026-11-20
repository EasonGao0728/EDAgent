import fs from 'node:fs/promises';
import path from 'node:path';

export async function inspectUploadPackage(files){
  const byName=new Map(files.map(f=>[f.name,f]));
  if(!files.length)throw Error('请先选择本轮的输入文件');
  const problems=[];
  async function object(name){
    const f=byName.get(name);
    if(!f){problems.push('缺少 '+name);return {};}
    if(f.bytes>2*1024*1024){problems.push(name+' 超出清单大小上限 2 MiB');return {};}
    try{
      const value=JSON.parse(await fs.readFile(f.hostPath,'utf8'));
      if(!value||Array.isArray(value)||typeof value!=='object')throw Error();
      return value;
    }catch{problems.push(name+' 应为有效的 JSON 对象');return {};}
  }
  const manifest=await object('manifest.json'),design=await object('design.json');
  const top=manifest.top||design.top;
  if(typeof top!=='string'||!top.trim())problems.push('请在清单中声明顶层模块 top');
  if(design.top && manifest.top && design.top!==manifest.top)problems.push('两个清单中的 top 不一致');
  if(byName.has('manifest.json')){
    for(const field of ['netlist','tech_lef','cell_lefs','libs','sdc']){
      const value=manifest[field],list=['cell_lefs','libs'].includes(field)?value:[value];
      if(!Array.isArray(list)||!list.length||list.some(v=>typeof v!=='string'||!v.trim())){
        problems.push('manifest.json 需要填写 '+field);continue;
      }
      for(const ref of list){
        const name=path.posix.basename(ref.replaceAll('\\','/'));
        if(!byName.get(name)?.bytes)problems.push(field+' 缺少或为空：'+name);
      }
    }
  }
  return {top:typeof top==='string'?top:null,caseId:typeof manifest.case_id==='string'?manifest.case_id:null,problems,
    files:files.map(f=>({name:f.name,bytes:f.bytes,sha256:f.attachmentId.slice(7)}))};
}
