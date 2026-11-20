"""Audited Core GDS/readback continuation; preserve the storage-failed parent."""
import argparse, copy, hashlib, json, os, signal, sys, tarfile, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def sha256_file_digest_compat(stream,digest):
    """Python 3.10 bridge for this frozen runner's SHA-256 stream hashing."""
    if digest!='sha256':raise ValueError('Only audited SHA-256 is supported')
    value=hashlib.sha256()
    for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value

# aes_flow's frozen duplicate-storage audit uses the same newer stdlib helper.
# Supply the missing API only; never replace an existing implementation.
if not hasattr(hashlib,'file_digest'):hashlib.file_digest=sha256_file_digest_compat
from macro_agent import aes_flow
from tools.resume_aes_gds_checkpoint import relocate

REVISIONS={
 'macro_agent/aes_flow.py':('7b65e838b7998d7156e3d1da6e8ebe705c74e51f72eb234f6c05966d97360bde','aa5e76c451790b9b3421cf9f6f58ab7e29bef41cf6e04d14d3a15fb78b570381'),
 'macro_agent/main_task.py':('a30d3a24568271a0f9e49022e802699d3cf0cd5761dff9f5e457279598e59f92','f60704762113a81dd9685b6cfc0101a318e7d6c0f45d7207ae505e977c412282'),
 'macro_agent/quota.py':('ef0b8b4eab520f11da74c23c2622523fe8acf7dc53d8b447e9fb83df63462d14','55cd171166bde2716d25fe5e6a23dab9f55a2e2b95753c0db3565e3dfcd2d4e7')}

def sha(p):
    # The approved server runs Python 3.10, which lacks hashlib.file_digest.
    digest=hashlib.sha256()
    with Path(p).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def check_record(record,current):
    if record.get('case')!='aes_core_sky130_t' or record.get('status')!='failed':
        raise ValueError('Only the storage-failed Core parent is supported')
    stages=record['stages']
    if [s['stage'] for s in stages]!=aes_flow.STAGES[:15] or not all(s.get('passed') is True for s in stages[:14]):
        raise ValueError('All first fourteen native stages must be passed')
    fail=stages[-1]
    if fail.get('passed') is not False or fail.get('storage_limit_exceeded') is not True or fail.get('returncode')!=-9 or fail.get('timed_out') or fail.get('file_size_limit_exceeded'):
        raise ValueError('Only the exact workspace-cap failure may continue')
    original=record['implementation_sha256']
    if set(original)!=set(current):raise ValueError('Source file set changed')
    changed={p for p in current if current[p]!=original[p]}
    if changed!=set(REVISIONS) or any((original[p],current[p])!=REVISIONS[p] for p in changed):
        raise ValueError('Unreviewed implementation revision')
    if record['version']!=aes_flow.VERSION or record['router_sha256']!=aes_flow.ROUTER_SHA256:
        raise ValueError('Native version changed')

def review(parent,reference,current):
    parent,reference=Path(parent),Path(reference)
    record=json.loads((parent/'run.json').read_text(encoding='utf-8'))
    check_record(record,current)
    if sha(ROOT/'tools/run_aes_baseline.py')!=record['baseline_runner_sha256']:raise ValueError('Baseline driver changed')
    files={p.relative_to(reference).as_posix():sha(p) for p in reference.rglob('*') if p.is_file()}
    if files!=record['input_sha256']:raise ValueError('Original inputs changed')
    for stage in record['stages'][:14]:
        name=stage['stage']
        if name=='validate':continue
        binary=aes_flow.ROUTER_SHA256 if name=='routing' else aes_flow.BINARY_SHA256
        if sha(parent/'result'/(name+'.def'))!=stage['artifact_sha256'] or binary!=stage['binary_sha256']:
            raise ValueError('Accepted checkpoint artifact changed: '+name)
    report=parent/'result/report'
    for name in ('violations.json','violation_map.json'):
        if sha(report/name)!=sha(report/'drc.rpt.artifacts'/name):raise ValueError('DRC duplicate differs')
    return record

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--parent-archive',required=True);ap.add_argument('--archive-sha256',required=True);ap.add_argument('--output',required=True);ap.add_argument('--runtime',required=True);args=ap.parse_args()
    if os.name!='posix' or os.getuid()!=1015:raise ValueError('Personal server account required')
    archive=Path(args.parent_archive).resolve();work=Path(args.output).resolve()
    if not archive.is_relative_to(ROOT) or not work.is_relative_to(ROOT/'runs') or work.exists():raise ValueError('New owned output required')
    if sha(archive)!=args.archive_sha256:raise ValueError('Parent archive changed')
    temporary=ROOT/('core-checkpoint-'+str(os.getpid()));temporary.mkdir(exist_ok=False)
    with tarfile.open(archive) as t:
        for member in t.getmembers():
            target=(temporary/member.name).resolve()
            if not target.is_relative_to(temporary/'server-core-01') or not(member.isdir() or member.isfile()):raise ValueError('Unsafe parent archive')
        t.extractall(temporary)
    parent=temporary/'server-core-01';reference=ROOT/'cases/ibench/aes_core_sky130_t'
    current={p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'macro_agent').glob('*.py')}
    old=review(parent,reference,current);raw=(parent/'run.json').read_bytes();parent_hash=sha(parent/'run.json')
    files={p.relative_to(parent).as_posix():sha(p) for p in parent.rglob('*') if p.is_file()}
    budget=json.loads((reference/'manifest.json').read_text())['budget'];previous=old['finished_at']-old['created_at'];remaining=int(budget['wall_seconds']-previous)
    if remaining<120 or len(old['stages'])+2>budget['executions']:raise ValueError('Original cumulative budget exhausted')
    work.parent.mkdir(exist_ok=True);parent.rename(work);temporary.rmdir()
    lineage=work/'lineage';lineage.mkdir();(lineage/'parent-run.json').write_bytes(raw);aes_flow.write(lineage/'parent-files.json',files)
    (work/'gds_export-evidence.json').rename(lineage/'failed-gds-export-evidence.json')
    if (work/'result/final.gds').exists():(work/'result/final.gds').rename(lineage/'failed-final.gds')
    aes_flow.prune_duplicate_drc_exports(work)
    if sum(p.stat().st_size for p in work.rglob('*') if p.is_file())>=aes_flow.WORK_LIMIT_BYTES:raise ValueError('Compacted checkpoint still exceeds original cap')
    old_root=Path(old['stages'][0]['artifact']).parent.parent;stages=[]
    for index,s in enumerate(old['stages'][:14]):
        item=relocate(copy.deepcopy(s),old_root,work);item['checkpoint_source']={'parent_run_sha256':parent_hash,'stage_index':index};stages.append(item)
    record={k:copy.deepcopy(old[k]) for k in ('case','version','input_sha256','baseline_runner_sha256','router_sha256','acceptance_mode')}
    record.update(created_at=time.time(),status='running',agent_calls=0,stages=stages,implementation_sha256=current,resume_runner_sha256=sha(Path(__file__)),execution_mode='resumed_after_duplicate_storage_fix',
      lineage={'parent_run_sha256':parent_hash,'parent_archive_sha256':args.archive_sha256,'parent_status':'failed','inherited_stages':14,'new_native_stages':[],'parent_elapsed_seconds':previous,'remaining_wall_seconds':remaining,'parent_file_manifest_sha256':sha(lineage/'parent-files.json'),'storage_dedup_sha256':sha(work/'drc-storage-dedup.json')})
    aes_flow.write(work/'run.json',record)
    def interrupt(signum,frame):raise RuntimeError('Native tail interrupted: '+str(signum))
    signal.signal(signal.SIGTERM,interrupt);signal.signal(signal.SIGALRM,interrupt);signal.alarm(remaining)
    try:
        for stage in ('gds_export','routed_readback'):
            print('RUN '+stage,flush=True);result=aes_flow.execute(stage,work,reference,args.runtime);record['stages'].append(result);record['lineage']['new_native_stages'].append(stage);aes_flow.write(work/'run.json',record)
            if result.get('passed') is not True:raise ValueError('Native tail failed: '+stage)
        record['status']='passed';record['physical_quality_passed']=stages[12]['drc_gate']['quality_clean']
    except Exception as exc:
        record.update(status='failed',error=str(exc));raise
    finally:
        signal.alarm(0);record['finished_at']=time.time();aes_flow.write(work/'run.json',record)

if __name__=='__main__':main()
