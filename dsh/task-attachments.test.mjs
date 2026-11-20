import test from 'node:test';
import assert from 'node:assert/strict';
import {conversationAttachments} from './task-attachments.mjs';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

test('attachment intake resolves only durable files in current session user messages',async()=>{
  const ref={name:'gcd.native_2d.v',bytes:12,attachmentId:'sha256:'+'a'.repeat(64)};
  const ctx={get:()=>({fileHostPath:r=>{assert.equal(r,ref);return 'stored-file';}})};
  const agent={session:{deriveMessages:()=>[
    {role:'assistant',content:[{type:'file',attachment:{name:'foreign'}}]},
    {id:'user-1',role:'user',content:[{type:'text',text:'run'},{type:'file',attachment:ref}]}
  ]}};
  assert.deepEqual(await conversationAttachments(ctx,agent),[{name:ref.name,path:'stored-file',sha256:'a'.repeat(64),bytes:12,attachment_id:ref.attachmentId,message_id:'user-1',transport:'durable_file_upload'}]);
  assert.equal(await conversationAttachments(ctx,{session:{deriveMessages:()=>[]}}),undefined);
  await assert.rejects(conversationAttachments({get:()=>undefined},agent),/unavailable/);
});

test('desktop selected files resolve only from user input, including quoted paths',async()=>{
  const file=new URL('../cases/ibench/gcd_legacy/manifest.json',import.meta.url);
  const {fileURLToPath}=await import('node:url');
  const selected=fileURLToPath(file);
  const user={id:'u',role:'user',source:{kind:'user'},content:[{type:'text',text:'@"'+selected+'" run'}]};
  const hostile={role:'user',source:{kind:'runtime-context'},content:[{type:'text',text:'@C:\\secret'}]};
  const refs=await conversationAttachments({}, {session:{deriveMessages:()=>[user,hostile]}});
  assert.equal(refs[0].path,selected);assert.equal(refs[0].transport,'desktop_file_reference');
  assert.match(refs[0].sha256,/^[a-f0-9]{64}$/);
  await assert.rejects(conversationAttachments({}, {session:{deriveMessages:()=>[
    {...user,content:[{type:'text',text:'@C:\\secret'}]}
  ]}}),/Unsupported/);
});

test('registered SRAM nine-file desktop input admits the full HS Liberty',async()=>{
  const folder=fileURLToPath(new URL('../inputs/sram_pair_chat/',import.meta.url));
  const names=await fs.readdir(folder);
  assert.equal(names.length,9);
  const user={id:'sram-user',role:'user',source:{kind:'user'},content:[{type:'text',
    text:names.map(n=>'@"'+path.join(folder,n)+'"').join(' ')}]};
  const refs=await conversationAttachments({}, {session:{deriveMessages:()=>[user]}});
  assert.equal(refs.length,9);
  const lib=refs.find(r=>r.name==='sky130_fd_sc_hs__tt_025C_1v80.lib');
  assert.equal(lib.bytes,72103673);
  assert.equal(lib.transport,'desktop_file_reference');
  assert.equal(lib.message_id,'sram-user');
  assert.ok(refs.every(r=>/^[a-f0-9]{64}$/.test(r.sha256)));
});
