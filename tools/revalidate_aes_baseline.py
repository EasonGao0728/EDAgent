"""Audit exact reviewed checker/controller revisions without rewriting a run.

Native producer/input/runtime changes still require a fresh server execution.
A failed or incomplete baseline can never be rescued by this audit.
"""
import hashlib,json,tarfile
from pathlib import Path,PurePosixPath
from macro_agent import aes_flow,aes_transforms
from macro_agent.def_validation import read_def

ROOT=Path(__file__).resolve().parents[1]
CHECKER='macro_agent/aes_transforms.py'
OLD='cea5c23c8226ae8edce1d6316856593d9da231b506f36e0ebe77b49128b2f8e4'
NEW='4e457454cf17e420e84b45e59035907559576bf2e89f89d14ede333d2a0aed82'
GDS='macro_agent/native_gds.py'
CONTROLLER='macro_agent/main_task.py'
QUOTA='macro_agent/quota.py'
STORAGE='macro_agent/aes_flow.py'
APPROVED={CHECKER:(OLD,NEW),
    STORAGE:('7b65e838b7998d7156e3d1da6e8ebe705c74e51f72eb234f6c05966d97360bde','aa5e76c451790b9b3421cf9f6f58ab7e29bef41cf6e04d14d3a15fb78b570381'),
    QUOTA:('ef0b8b4eab520f11da74c23c2622523fe8acf7dc53d8b447e9fb83df63462d14','55cd171166bde2716d25fe5e6a23dab9f55a2e2b95753c0db3565e3dfcd2d4e7'),
    GDS:('e57ab8a6c410aba19dc17780ce18418187b62aabfaa760b3f602d1a2e70a1686','8c7c9b7fa3c5dba50eebf6a43e8fe4f83bbfd90a4f8704c62bfeb3a6b3bad1d1'),
    CONTROLLER:('a30d3a24568271a0f9e49022e802699d3cf0cd5761dff9f5e457279598e59f92','f60704762113a81dd9685b6cfc0101a318e7d6c0f45d7207ae505e977c412282')}
PREVIOUS={'fanout':'floorplan','placement':'fanout','cts':'export_def','to_drv':'cts',
          'to_hold':'to_drv','legalization':'to_hold','routing':'legalization',
          'filler':'routing','drc':'filler','timing':'filler','routed_readback':'filler'}

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_lineage(record,server):
    mode=record.get('execution_mode')
    if mode not in ('resumed_after_validation_only_fix','resumed_after_duplicate_storage_fix'):
        if 'lineage' in record:raise ValueError('Unrecognized baseline lineage')
        return None
    from tools.resume_aes_gds_checkpoint import relocate
    storage=mode=='resumed_after_duplicate_storage_fix'
    if storage:
        from tools.resume_aes_storage_checkpoint import review
    else:
        from tools.resume_aes_gds_checkpoint import review
    profile='v5c' if storage else 'v5b';run='server-core-01' if storage else 'server-legacy-01'
    driver='tools/resume_aes_storage_checkpoint.py' if storage else 'tools/resume_aes_gds_checkpoint.py'
    parent=ROOT/'runs/aes-p1-20261108/downloaded'/profile/run
    archive=ROOT/'runs/aes-p1-20261108'/(profile+'-'+run+'.tar.gz')
    lineage=record['lineage'];embedded=server/'lineage/parent-run.json'
    if sha(parent/'run.json')!=lineage['parent_run_sha256'] or embedded.read_bytes()!=(parent/'run.json').read_bytes() or sha(archive)!=lineage['parent_archive_sha256']:
        raise ValueError('Checkpoint lineage parent changed')
    deployment=json.loads((ROOT/'runs/aes-p1-20261108'/('v5d-deployment.json' if storage else 'v5c-deployment.json')).read_text(encoding='utf-8'))
    frozen={k:v for k,v in deployment['files'].items() if k.startswith('macro_agent/') and k.endswith('.py')}
    if record['implementation_sha256']!=frozen:raise ValueError('Checkpoint frozen implementation changed')
    old=review(parent,ROOT/'cases/ibench'/('aes_core_sky130_t' if storage else 'aes_legacy'),frozen)
    if record['resume_runner_sha256']!=sha(ROOT/driver) or record['resume_runner_sha256']!=deployment['files'][driver]:
        raise ValueError('Checkpoint continuation driver changed')
    if lineage['inherited_stages']!=14 or lineage['new_native_stages']!=['gds_export','routed_readback']:
        raise ValueError('Checkpoint tail was not executed')
    old_root=PurePosixPath(old['stages'][0]['artifact']).parent.parent
    new_root=PurePosixPath(record['stages'][0]['artifact']).parent.parent
    for index,value in enumerate(old['stages'][:14]):
        expected=relocate(value,old_root,new_root)
        expected['checkpoint_source']={'parent_run_sha256':lineage['parent_run_sha256'],'stage_index':index}
        if record['stages'][index]!=expected:raise ValueError('Inherited stage evidence changed')
    manifest=server/'lineage/parent-files.json'
    if sha(manifest)!=lineage['parent_file_manifest_sha256']:raise ValueError('Checkpoint file manifest changed')
    files=json.loads(manifest.read_text(encoding='utf-8'))
    actual={p.relative_to(parent).as_posix():sha(p) for p in parent.rglob('*') if p.is_file()}
    if actual!=files:raise ValueError('Checkpoint source files changed')
    budget=json.loads((ROOT/'cases/ibench'/record['case']/'manifest.json').read_text())['budget']
    elapsed=old['finished_at']-old['created_at']
    if lineage['parent_elapsed_seconds']!=elapsed or lineage['remaining_wall_seconds']!=int(budget['wall_seconds']-elapsed):
        raise ValueError('Checkpoint original time budget changed')
    if elapsed+record['finished_at']-record['created_at']>budget['wall_seconds'] or len(old['stages'])+2>budget['executions']:
        raise ValueError('Checkpoint cumulative original budget exceeded')
    if storage:
        audit=server/'drc-storage-dedup.json'
        if sha(audit)!=lineage['storage_dedup_sha256']:raise ValueError('Storage audit changed')
        rows=json.loads(audit.read_text())['removed']
        if {r['removed'] for r in rows}!={'result/report/drc.rpt.artifacts/'+n for n in ('violations.json','violation_map.json')}:raise ValueError('Unexpected storage removal')
        for row in rows:
            if files[row['removed']]!=row['sha256'] or files[row['canonical']]!=row['sha256'] or sha(server/row['canonical'])!=row['sha256'] or (server/row['removed']).exists():
                raise ValueError('Complete canonical DRC details not preserved')
    return {'passed':True,'mode':record['execution_mode'],'inherited_stages':14,
            'new_native_stages':lineage['new_native_stages'],'parent_status_preserved':'failed',
            'parent_run_sha256':lineage['parent_run_sha256'],'parent_archive_sha256':lineage['parent_archive_sha256']}

def verify(record,server):
    server=Path(server)
    if record['status']!='passed' or [s['stage'] for s in record['stages']]!=aes_flow.STAGES or not all(s.get('passed') is True for s in record['stages']):
        raise ValueError('Revalidation requires an already passed complete baseline')
    current={p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'macro_agent').glob('*.py')}
    original=record['implementation_sha256']
    if set(current)!=set(original):raise ValueError('Implementation file set changed')
    changed=[p for p in current if current[p]!=original[p]]
    result={'producer_unchanged':True,'changed_validation_files':[p for p in changed if p not in (CONTROLLER,QUOTA,STORAGE)],
            'changed_storage_only_files':[p for p in changed if p==STORAGE],
            'changed_desktop_controller_files':[p for p in changed if p in (CONTROLLER,QUOTA)],
            'source_run_sha256':sha(server/'run.json'),'implementation_sha256':current,
            'original_implementation_sha256':original,'validation_version':aes_transforms.VALIDATION_VERSION,
            'rechecked_stages':{},'native_rerun':False,'checkpoint_lineage':verify_lineage(record,server)}
    if not changed:return result
    if any(p not in APPROVED or (original[p],current[p])!=APPROVED[p] for p in changed):
        raise ValueError('Unreviewed producer or validator change')
    archive=None
    for profile in ('v5','v5b','v5c','v5d'):
        candidate=ROOT/'runs/aes-p1-20261108'/(profile+'-launch.tar.gz')
        if not candidate.is_file():continue
        with tarfile.open(candidate) as t:
            frozen={m.name:hashlib.sha256(t.extractfile(m).read()).hexdigest() for m in t if m.name in original and m.isfile()}
        if frozen==original:archive=candidate;break
    if archive is None:raise ValueError('Original frozen source archive not found')
    result['frozen_source_archive_sha256']=sha(archive)
    result['reason']='Exact reviewed empty-net checkers, desktop lossless storage/checkpoint controller, user-configured quota floor, and SHA-verified removal of duplicate secondary DRC exports; native binaries, commands, scripts, inputs and gates unchanged'
    stages={s['stage']:s for s in record['stages']}
    for stage,s in stages.items():
        if stage=='validate':continue
        artifact=server/'result'/('final.gds' if stage=='gds_export' else stage+'.def')
        if sha(artifact)!=s['artifact_sha256']:raise ValueError('Baseline artifact changed: '+stage)
    for stage,previous in (PREVIOUS.items() if CHECKER in changed else []):
        if stages[stage].get('transformation',{}).get('passed') is not True:
            raise ValueError('Original transformation was not passed: '+stage)
        checked=aes_transforms.check(read_def(server/'result'/(previous+'.def')),read_def(server/'result'/(stage+'.def')),stage)
        result['rechecked_stages'][stage]=checked
        if checked['passed'] is not True:raise ValueError('Current validator rejects baseline: '+stage)
    if GDS in changed:
        from macro_agent.native_gds import validate
        reference=ROOT/'cases/ibench'/record['case'];m=json.loads((reference/'manifest.json').read_text(encoding='utf-8'))
        checked=validate(server/'result/final.gds',server/'result/filler.def',reference/m['tech_lef'],[reference/p for p in m['cell_lefs']])
        result['gds_revalidation']=checked
        if checked['passed'] is not True:raise ValueError('Current GDS validator rejects baseline')
    return result
