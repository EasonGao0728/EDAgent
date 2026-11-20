import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {catalog,cosine,loadTools,visibleToolNames,BOOTSTRAP,catalogVersion,selectionFolder,searchTools} from './tool-library.mjs';
import {inputAdvice,qualityAdvice,writePerceptionReport} from './perception-report.mjs';

test('catalog distinguishes tools, bounded experiments and unsupported local repair',()=>{
  const {cards}=catalog();assert.equal(new Set(cards.map(c=>c.id)).size,cards.length);
  assert.equal(cards.find(c=>c.id==='local-eco').status,'capability_gap');assert.deepEqual(cards.find(c=>c.id==='local-eco').tools,[]);
  assert.equal(cards.find(c=>c.id==='tool-maker').status,'disabled');
});
test('unknown retrieval phase returns corrective facts without executing or crashing conversation',async()=>{
  const r=await searchTools('continue workflow',{stage:'execution'});
  assert.equal(r.error,'UNKNOWN_STAGE');assert.deepEqual(r.candidates,[]);assert.equal(r.maker_called,false);
  assert.ok(r.allowed_stages.includes('floorplan'));assert.ok(!r.allowed_stages.includes('execution'));
});
test('cosine uses normalized angle similarity, rejects incompatible vectors',()=>{
  assert.equal(cosine([1,0],[1,0]),1);assert.equal(cosine([1,0],[0,1]),0);assert.equal(cosine([0,0],[1,0]),0);assert.throws(()=>cosine([1],[1,0]));
});
test('context loads selected capability definitions rather than full catalog and isolates sessions',async()=>{
  const a=await fs.mkdtemp(path.join(os.tmpdir(),'tool-index-a-')),b=await fs.mkdtemp(path.join(os.tmpdir(),'tool-index-b-'));
  try{assert.deepEqual(await visibleToolNames(a),BOOTSTRAP);await loadTools(a,['density-branch'],'test');assert.ok((await visibleToolNames(a)).has('mp_feedback_branch'));assert.ok(!(await visibleToolNames(b)).has('mp_feedback_branch'));
    await loadTools(a,['input-profile'],'replace');assert.ok(!(await visibleToolNames(a)).has('mp_feedback_branch'));
    await assert.rejects(()=>loadTools(a,['local-eco'],'no'),/UNAVAILABLE/);
    await fs.writeFile(path.join(selectionFolder(a),'loaded-tool-cards.json'),JSON.stringify({catalog_version:'stale',card_ids:['density-branch']}));assert.deepEqual(await visibleToolNames(a),BOOTSTRAP);
  }finally{await fs.rm(a,{recursive:true,force:true});await fs.rm(b,{recursive:true,force:true});}
});
test('a fabricated tool list in cached selection cannot load arbitrary tools',async()=>{
  const a=await fs.mkdtemp(path.join(os.tmpdir(),'tool-index-'));
  try{await fs.mkdir(selectionFolder(a),{recursive:true});await fs.writeFile(path.join(selectionFolder(a),'loaded-tool-cards.json'),JSON.stringify({catalog_version:catalogVersion,card_ids:['input-profile'],tools:['shell']}));const visible=await visibleToolNames(a);assert.ok(!visible.has('shell'));assert.ok(visible.has('mp_feedback_inspect'));}finally{await fs.rm(a,{recursive:true,force:true});}
});
test('input advice does not turn proxy metrics into congestion or inferred function',()=>{
  const a=inputAdvice({metrics:{hard_macros:{value:0},nominal_area_utilization:{value:.57}}});assert.ok(a.features.some(x=>x.includes('未发现硬宏')));assert.ok(a.unknowns.some(x=>x.includes('拥塞')));
  assert.ok(!inputAdvice({metrics:{hard_macros:{value:null}}}).features.some(x=>x.includes('未发现硬宏')));
});
test('quality report retains unsupported repair and does not invent marker regions',()=>{
  const q=qualityAdvice({count_consistent:true,count:100,hotspots:[{tile_10um:[2,3],markers:10}]});assert.deepEqual(q.regions[0].bbox_um,[20,30,30,40]);assert.equal(q.measured_congestion,null);assert.equal(q.automatic_local_repair_enabled,false);
  assert.deepEqual(qualityAdvice({count_consistent:false,hotspots:[{tile_10um:[2,3],markers:10}]}).regions,[]);
});
test('reports escape untrusted metadata, preserve exact provenance and create content-addressed artifacts',async()=>{
  const a=await fs.mkdtemp(path.join(os.tmpdir(),'input-report-'));
  try{const r=await writePerceptionReport(a,'input',{evidence_id:'source',facts:{status:'<script>alert(1)</script>',metrics:{instances:{value:255,unit:'count',kind:'measured'}},sources:[{sha256:'ref'}]}});const h=await fs.readFile(r.report.path,'utf8');assert.ok(h.includes('255'));assert.ok(!h.includes('<script>'));assert.equal(JSON.parse(await fs.readFile(r.data.path,'utf8')).evidence_id,'source');}finally{await fs.rm(a,{recursive:true,force:true});}
});
