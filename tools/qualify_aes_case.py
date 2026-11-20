"""Admit a case only from a downloaded, complete current server baseline.

This is permission to attempt DSH execution, not evidence that DSH has run it.
"""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from macro_agent import aes_flow,ieda_runtime as rt
from macro_agent.placement_registry import record_verification
from tools.audit_aes_drivers import run as driver_audit
from tools.revalidate_aes_baseline import verify as verify_implementation
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def qualify(server):
    server=Path(server).resolve()
    if not any(server.is_relative_to(ROOT/'runs/aes-p1-20261108/downloaded'/v) for v in ('v5','v5b','v5c','v5d')):raise ValueError('Current downloaded server evidence required')
    r=json.loads((server/'run.json').read_text(encoding='utf-8'))
    if r['status']!='passed' or r['version']!=aes_flow.VERSION:raise ValueError('Baseline has not passed the current native workflow')
    if [s['stage'] for s in r['stages']]!=aes_flow.STAGES or not all(s.get('passed') is True for s in r['stages']):raise ValueError('Incomplete native stages')
    reference=ROOT/'cases/ibench'/r['case']
    for rel,h in r['input_sha256'].items():
        p=(reference/rel).resolve()
        if not p.is_relative_to(reference) or sha(p)!=h:raise ValueError('Input changed: '+rel)
    revalidation=verify_implementation(r,server)
    revalidationfile=server/'validation-revision-audit.json'
    revalidationfile.write_text(json.dumps(revalidation,indent=2),encoding='utf-8')
    if sha(ROOT/'tools/run_aes_baseline.py')!=r['baseline_runner_sha256']:raise ValueError('Baseline driver changed')
    if r['router_sha256']!=aes_flow.ROUTER_SHA256 or sha(ROOT/'environments/ieda-aes-router/iEDA')!=aes_flow.ROUTER_SHA256:raise ValueError('Router changed')
    for s in r['stages']:
        if s['stage']=='validate':continue
        name='final.gds' if s['stage']=='gds_export' else s['stage']+'.def'
        if sha(server/'result'/name)!=s['artifact_sha256']:raise ValueError('Downloaded stage output changed: '+name)
    image=rt.invoke(['image','inspect',rt.IMAGE,'--format','{{.Id}}']).strip()
    if image!=rt.IMAGE:raise ValueError('Local pinned main runtime unavailable')
    export=json.loads((ROOT/'environments/ieda-export/runtime-manifest.json').read_text())
    if sha(ROOT/'environments/ieda-export/bin/ieda-idb-export')!=export['executable_sha256']:raise ValueError('Exporter changed')
    if rt.invoke(['image','inspect',export['image'],'--format','{{.Id}}']).strip()!=export['image']:raise ValueError('Pinned local exporter image unavailable')
    smoke=ROOT/'runs/aes-p1-20261108/runtime-smoke/local-router-recovered.json'
    local=json.loads(smoke.read_text())
    if local.get('passed') is not True or local.get('image')!=image or local.get('router_sha256')!=aes_flow.ROUTER_SHA256:raise ValueError('Local router entry unverified')
    parityfile=smoke.parent/'runtime-parity.json';parity=json.loads(parityfile.read_text())
    if parity.get('local_passed') is not True or parity.get('server',{}).get('passed') is not True or parity.get('main_image')!=image:raise ValueError('Portable runtime parity is unverified')
    audit=driver_audit(server,reference)
    auditfile=server/'independent-driver-audit.json';auditfile.write_text(json.dumps(audit,indent=2),encoding='utf-8')
    if not audit['passed']:raise ValueError('Additional driver audit failed: '+str(auditfile))
    hashes={**revalidation['implementation_sha256'],'tools/audit_aes_drivers.py':sha(ROOT/'tools/audit_aes_drivers.py'),
            'tools/revalidate_aes_baseline.py':sha(ROOT/'tools/revalidate_aes_baseline.py')}
    if r.get('execution_mode')=='resumed_after_validation_only_fix':
        hashes['tools/resume_aes_gds_checkpoint.py']=sha(ROOT/'tools/resume_aes_gds_checkpoint.py')
    elif r.get('execution_mode')=='resumed_after_duplicate_storage_fix':
        hashes['tools/resume_aes_storage_checkpoint.py']=sha(ROOT/'tools/resume_aes_storage_checkpoint.py')
    receipt={'status':'passed','case':r['case'],'version':aes_flow.VERSION,'image':image,
        'evidence':{'path':str(server/'run.json'),'sha256':sha(server/'run.json')},
        'input_sha256':r['input_sha256'],'implementation_sha256':hashes,
        'additional_audit':{'path':str(auditfile),'sha256':sha(auditfile)},
        'validation_revision_audit':{'path':str(revalidationfile),'sha256':sha(revalidationfile)},
        'local_router_smoke':{'path':str(smoke),'sha256':sha(smoke)},
        'runtime_parity':{'path':str(parityfile),'sha256':sha(parityfile)},
        'router_sha256':r['router_sha256'],'native_exporter_sha256':export['executable_sha256'],
        'local_layout_executed':False,'p1_accepted':False,
        'physical_quality_passed':r['physical_quality_passed'],
        'scope':'Server full-flow qualification and local pinned runtime entry; DSH execution/comparison remains mandatory'}
    folder=ROOT/'.cache/aes-qualification';folder.mkdir(exist_ok=True)
    target=folder/(r['case']+'.json')
    if target.exists():raise ValueError('Refuse to replace an existing qualification receipt')
    target.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    record_verification('ieda_ipl_'+r['case'],image,image,target)
    return {'receipt':str(target),'case':r['case'],'server_passed':True,'local_layout_executed':False,'p1_accepted':False,'physical_quality_passed':r['physical_quality_passed']}
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--server',required=True);a=ap.parse_args();print(json.dumps(qualify(a.server)))
