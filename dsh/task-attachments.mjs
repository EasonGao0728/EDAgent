import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
// Desktop file-picker/drop inserts @path; web uploads use durable file blocks.
// Both are read from this session's user message, never from tool arguments.
const acceptedNames=new Set(['design.v','design.sdc','gcd.native_2d.v','sky130_fd_sc_hd.tlef','sky130_fd_sc_hd_merged.lef',
  'sky130_fd_sc_hd__tt_025C_1v80.lib','gcd.sdc','manifest.json','design.json',
  'gcd_sram.v','sky130_fd_sc_hs.tlef','sky130_fd_sc_hs_merged.lef','sky130_sram_1rw1r_44x64_8.lef',
  'sky130_fd_sc_hs__tt_025C_1v80.lib','sky130_sram_1rw1r_44x64_8_TT_1p8V_25C.lib']);
function mentions(message){
  return (message.content||[]).filter(b=>b.type==='text').flatMap(b=>
    [...b.text.matchAll(/(?:^|\s)@(?:"([^"\r\n]+)"|([^\s"]+))/g)].map(m=>m[1]||m[2]));
}
export async function conversationAttachments(ctx, agent){
  const messages=agent.session.deriveMessages?.()||[];
  const message=messages.findLast(m=>m.role==='user'&&(!m.source||m.source.kind==='user')&&
    (m.content?.some(b=>b.type==='file')||mentions(m).length));
  if(!message)return undefined;
  const local=mentions(message);
  if(local.length){
    if(message.content.some(b=>b.type==='file'))throw Error('Use one file attachment transport per message');
    return Promise.all(local.map(async hostPath=>{
      const name=path.basename(hostPath);
      if(!path.isAbsolute(hostPath)||!acceptedNames.has(name))throw Error('Unsupported case file reference: '+name);
      const stat=await fs.stat(hostPath);
      // The registered HS Liberty is 72,103,673 bytes. Its reviewed SHA-256 is
      // still enforced by Python intake; other files keep the smaller limit.
      const maxBytes=(name==='sky130_fd_sc_hs__tt_025C_1v80.lib'?80:20)*1024*1024;
      if(!stat.isFile()||stat.size>maxBytes)throw Error('Invalid case input file: '+name);
      const data=await fs.readFile(hostPath);
      return {name,path:hostPath,sha256:createHash('sha256').update(data).digest('hex'),bytes:data.length,
        transport:'desktop_file_reference',message_id:message.id};
    }));
  }
  const store=ctx.get('attachments');
  if(!store)throw Error('DSH attachment storage unavailable');
  return message.content.filter(b=>b.type==='file').map(({attachment:ref})=>{
    const hostPath=store.fileHostPath(ref);
    if(!hostPath)throw Error('Uploaded attachment has no readable host file');
    const sha256=String(ref.attachmentId).match(/^sha256:([a-f0-9]{64})$/)?.[1];
    if(!sha256)throw Error('Invalid uploaded attachment digest');
    return {name:ref.name,path:hostPath,sha256,bytes:ref.bytes,
      attachment_id:String(ref.attachmentId),message_id:message.id,transport:'durable_file_upload'};
  });
}
