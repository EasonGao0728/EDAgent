"""Audited, narrowly scoped GDS checker correction; never starts native EDA."""
from pathlib import Path
import base64,json,shlex,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'runs/medium-macro-fullflow-20261114'
CODE=r'''
from pathlib import Path
import json,sys,os,hashlib,base64,ast,time
assert os.getuid()==1015
root=Path('/srv/edagent/main-agent-remote-v1');sys.path[:0]=[str(root),'/srv/edagent/python']
from macro_agent.remote_platform import install
t=install()
from macro_agent import main_decisions as decisions
from macro_agent.def_validation import read_def,section
import re
payload=json.loads(sys.stdin.read());code=base64.b64decode(payload['code']);ast.parse(code)
module=root/'macro_agent/native_gds.py';folder=root/'runs/remote-ba81f7bdbfebcf944da30462'
failed=folder/'attempts/35edb3d986f6';ref=root/'cases/ibench/swerv_nangate45'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(module)=='8c7c9b7fa3c5dba50eebf6a43e8fe4f83bbfd90a4f8704c62bfeb3a6b3bad1d1','Unexpected checker revision'
before=t.load(failed/'gds_export-evidence.json');assert before['returncode']==0 and not before['passed']
assert sha(failed/'result/final.gds')==before['artifact_sha256']
d=read_def(failed/'result/filler.def');rows={r.split()[0]:r for r in section((failed/'result/filler.def').read_text(),'NETS')}
expected={n for n,ends in d['nets'].items() if len(ends)==1 and not re.search(r'\+\s*(?:ROUTED|FIXED|COVER)\b|\bNEW\s+\S+\s+\(',rows[n])}
assert len(expected)==2094 and set(before['validation']['errors'])=={'missing_routed_net:'+n for n in expected},'Unrelated export failure'
ns={'__name__':'macro_agent._reviewed_gds_candidate','__package__':'macro_agent','__file__':str(module)}
exec(compile(code,str(module),'exec'),ns)
m=t.load(ref/'manifest.json')
v=ns['validate'](failed/'result/final.gds',failed/'result/filler.def',ref/m['tech_lef'],[ref/f for f in m['cell_lefs']])
assert v['passed'] and set(v['unrouted_single_terminal_nets_checked'])==expected,'Candidate fails real artifact verification'
receipt={'time':time.time(),'mode':payload['mode'],'old_checker_sha256':sha(module),'new_checker_sha256':hashlib.sha256(code).hexdigest(),
 'original_failure':t.file_ref(failed/'gds_export-evidence.json'),'same_gds_sha256':sha(failed/'result/final.gds'),
 'same_filler_def_sha256':sha(failed/'result/filler.def'),'validation':v,'native_stages_started':0,'old_failure_preserved':True}
if payload['mode']=='deploy':
 with t.locked(root/'scheduler'),t.locked(folder):
  assert not [p for p in root.glob('runs/*/jobs/*.json') if t.load(p)['status'] not in ('completed','failed','cancelled','lost')],'Active job'
  s=t.load(folder/'task.json');assert not s.get('pending') and len(s['completed'])==15
  assert s['status'] in ('running','stopped_with_best') and s['failure_counts'].get('gds_export')==1
  t.verify_refs(s['input_refs'])
  for stage in s['completed']:
   result=s['results'][stage];t.verify_refs(result['artifact_refs']);assert t.load(Path(result['receipt_ref']))==result
  manifest=root/'deployment-manifest.json';deployment=t.load(manifest)
  assert deployment['macro_agent/native_gds.py']['sha256']==sha(module)
  backup=folder/'checkpoints/before-single-terminal-gds-checker';backup.mkdir(exist_ok=False)
  for name,p in [('task.json',folder/'task.json'),('main-decisions.json',folder/'main-decisions.json'),('native_gds.py',module),('deployment-manifest.json',manifest)]:
   (backup/name).write_bytes(p.read_bytes())
  tmp=module.with_suffix('.single-terminal.tmp');tmp.write_bytes(code);tmp.replace(module)
  deployment['macro_agent/native_gds.py']={'sha256':sha(module),'bytes':len(code)};t.save(manifest,deployment)
  receipt.update(completed_stages_reused=s['completed'],counts_preserved=s['counts'],failure_counts_preserved=s['failure_counts'],budgets_reset=False)
  target=folder/'single-terminal-gds-checker-correction.json';t.save(target,receipt)
  assert any(x['path']==str(module) for x in s['input_refs'])
  s['input_refs']=[t.file_ref(module) if x['path']==str(module) else x for x in s['input_refs']]
  s['input_refs'].append(t.file_ref(target));s['contract']['all_inputs_hash']=t.digest(s['input_refs'])
  s['contract']['gds_checker_correction']=t.file_ref(target);s['revision']+=1
  s['events'].append({'action':'reviewed_gds_checker_correction','time':time.time(),'receipt':t.file_ref(target),'native_stages_started':0,'budgets_reset':False,'completed_stages_reused':s['completed'],'reason':'A single endpoint without DEF route geometry needs no routed conductor; retain named empty reference and all IO/multi-endpoint/route checks'})
  t.verify_refs(s['input_refs']);t.save(folder/'task.json',s)
  store=decisions.store(folder);store['revision']+=1;store['events'].append({'action':'reviewed_gds_checker_correction','receipt':t.file_ref(target),'budgets_reset':False});decisions.write(folder,store)
print(json.dumps(receipt))
'''
mode=sys.argv[1] if len(sys.argv)>1 else 'check'
assert mode in ('check','deploy')
payload={'mode':mode,'code':base64.b64encode((ROOT/'macro_agent/native_gds.py').read_bytes()).decode()}
r=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12','eda-backup','python3 -B -c '+shlex.quote(CODE)],input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=100)
if r.returncode:raise RuntimeError(r.stderr or r.stdout)
v=json.loads(r.stdout);(OUT/('gds-checker-'+mode+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'mode':mode,'passed':v['validation']['passed'],'single_terminal_nets':len(v['validation']['unrouted_single_terminal_nets_checked']),'routed_nets_checked':v['validation']['routed_nets_checked'],'route_points_checked':v['validation']['route_points_checked'],'native_stages_started':0,'new_checker_sha256':v['new_checker_sha256']},ensure_ascii=False))
