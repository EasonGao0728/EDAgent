"""Finish this run's two tail stages after one reviewed read-only checker fix.

This is not a fresh baseline and never changes the failed parent record. All
inherited stages retain explicit provenance. Native producer changes, partial
routing, failed native export, or any other failed gate forbid this continuation.
"""
import argparse, copy, hashlib, json, os, signal, sys, tarfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from macro_agent import aes_flow
from macro_agent.def_validation import read_def

CHECKER = 'macro_agent/native_gds.py'
OLD = 'e57ab8a6c410aba19dc17780ce18418187b62aabfaa760b3f602d1a2e70a1686'
NEW = '8c7c9b7fa3c5dba50eebf6a43e8fe4f83bbfd90a4f8704c62bfeb3a6b3bad1d1'
EMPTY = frozenset('core.keymem.rcon_logic.tmp_rcon[' + str(i) + ']' for i in (1, 3, 4))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def check_record(record, current, empty):
    """Fast fail-closed checks, before examining the archived artifact files."""
    if record.get('case') != 'aes_legacy' or record.get('status') != 'failed':
        raise ValueError('Only the failed current legacy checkpoint is supported')
    stages = record['stages']
    if [s['stage'] for s in stages] != aes_flow.STAGES[:15] or not all(s.get('passed') is True for s in stages[:14]):
        raise ValueError('The complete first fourteen stages must already be passed')
    failed = stages[-1]
    if failed.get('passed') is not False or failed.get('validation', {}).get('passed') is not False or failed.get('returncode') != 0 or any(failed.get(k) for k in ('timed_out', 'storage_limit_exceeded', 'file_size_limit_exceeded')):
        raise ValueError('Native export failure cannot be resumed by this correction')
    if set(empty) != EMPTY or sorted(failed.get('validation', {}).get('errors', [])) != sorted('missing_routed_net:' + n for n in empty):
        raise ValueError('Only the three independently preserved empty-net errors are allowed')
    old = record['implementation_sha256']
    if set(old) != set(current):
        raise ValueError('Implementation file set changed')
    changed = [k for k in current if current[k] != old[k]]
    if changed != [CHECKER] or old[CHECKER] != OLD or current[CHECKER] != NEW:
        raise ValueError('Unreviewed producer or checker change')
    if record['version'] != aes_flow.VERSION or record['router_sha256'] != aes_flow.ROUTER_SHA256:
        raise ValueError('Native version changed')


def review(parent, reference, current):
    parent, reference = Path(parent), Path(reference)
    record = json.loads((parent / 'run.json').read_text(encoding='utf-8'))
    empty = {n for n, ends in read_def(parent / 'result/import_netlist.def')['nets'].items() if not ends}
    check_record(record, current, empty)
    if sha(ROOT / 'tools/run_aes_baseline.py') != record['baseline_runner_sha256']:
        raise ValueError('Original native baseline driver changed')
    if set(record['input_sha256']) != {p.relative_to(reference).as_posix() for p in reference.rglob('*') if p.is_file()}:
        raise ValueError('Checkpoint input file set changed')
    for rel, h in record['input_sha256'].items():
        p = (reference / rel).resolve()
        if not p.is_relative_to(reference.resolve()) or sha(p) != h:
            raise ValueError('Checkpoint input changed: ' + rel)
    exporter = json.loads((ROOT / 'environments/ieda-export/runtime-manifest.json').read_text(encoding='utf-8'))
    for stage in record['stages']:
        name = stage['stage']
        if name == 'validate':
            continue
        file = parent / 'result' / ('final.gds' if name == 'gds_export' else name + '.def')
        expected_binary = (exporter['executable_sha256'] if name == 'gds_export' else
                           aes_flow.ROUTER_SHA256 if name == 'routing' else aes_flow.BINARY_SHA256)
        if sha(file) != stage['artifact_sha256'] or stage['binary_sha256'] != expected_binary:
            raise ValueError('Checkpoint output or binary changed: ' + name)
        if name != 'gds_export':
            actual_empty = {n for n, ends in read_def(file)['nets'].items() if not ends}
            if actual_empty != empty:
                raise ValueError('Empty declarations changed before export: ' + name)
    return record


def relocate(value, old_root, new_root):
    if isinstance(value, dict):
        return {k: relocate(v, old_root, new_root) for k, v in value.items()}
    if isinstance(value, list):
        return [relocate(v, old_root, new_root) for v in value]
    if isinstance(value, str) and value.startswith(str(old_root) + '/'):
        return str(new_root) + value[len(str(old_root)):]
    return value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--parent-archive', required=True)
    ap.add_argument('--archive-sha256', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--runtime', required=True)
    args = ap.parse_args()
    if os.name != 'posix' or os.getuid() != 1015:
        raise ValueError('This bounded continuation is server-account-only')
    archive = Path(args.parent_archive).resolve()
    work = Path(args.output).resolve()
    if not work.is_relative_to(ROOT / 'runs') or work.exists() or not archive.is_relative_to(ROOT):
        raise ValueError('New owned output and archive paths required')
    if sha(archive) != args.archive_sha256:
        raise ValueError('Transferred parent archive changed')
    temporary = ROOT / ('checkpoint-restore-' + str(os.getpid()))
    temporary.mkdir(exist_ok=False)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            target = (temporary / member.name).resolve()
            if not target.is_relative_to(temporary / 'server-legacy-01') or not (member.isdir() or member.isfile()):
                raise ValueError('Unsafe or unexpected checkpoint archive entry')
        tar.extractall(temporary)
    parent = temporary / 'server-legacy-01'
    current = {p.relative_to(ROOT).as_posix(): sha(p) for p in (ROOT / 'macro_agent').glob('*.py')}
    reference = ROOT / 'cases/ibench/aes_legacy'
    old = review(parent, reference, current)
    original_record = (parent / 'run.json').read_bytes()
    parent_hash = hashlib.sha256(original_record).hexdigest()
    files = {p.relative_to(parent).as_posix(): sha(p) for p in parent.rglob('*') if p.is_file()}
    manifest = json.loads((reference / 'manifest.json').read_text(encoding='utf-8'))
    previous_seconds = old['finished_at'] - old['created_at']
    remaining = int(manifest['budget']['wall_seconds'] - previous_seconds)
    if remaining < 120 or len(old['stages']) + 2 > manifest['budget']['executions']:
        raise ValueError('No remaining original execution/time budget')
    work.parent.mkdir(parents=True, exist_ok=True)
    parent.rename(work)
    temporary.rmdir()
    lineage = work / 'lineage'
    lineage.mkdir(exist_ok=False)
    (lineage / 'parent-run.json').write_bytes(original_record)
    aes_flow.write(lineage / 'parent-files.json', files)
    (work / 'gds_export-evidence.json').rename(lineage / 'failed-gds-export-evidence.json')
    old_root = Path(old['stages'][0]['artifact']).parent.parent
    stages = []
    for index, value in enumerate(old['stages'][:14]):
        item = relocate(copy.deepcopy(value), old_root, work)
        item['checkpoint_source'] = {'parent_run_sha256': parent_hash, 'stage_index': index}
        stages.append(item)
    record = {k: copy.deepcopy(old[k]) for k in ('case', 'version', 'input_sha256', 'baseline_runner_sha256', 'router_sha256', 'acceptance_mode')}
    record.update(created_at=time.time(), status='running', agent_calls=0, stages=stages,
                  implementation_sha256=current, resume_runner_sha256=sha(Path(__file__)),
                  execution_mode='resumed_after_validation_only_fix',
                  lineage={'parent_run_sha256': parent_hash, 'parent_archive_sha256': args.archive_sha256,
                           'parent_status': 'failed', 'inherited_stages': 14, 'new_native_stages': [],
                           'parent_elapsed_seconds': previous_seconds, 'remaining_wall_seconds': remaining,
                           'parent_file_manifest_sha256': sha(lineage / 'parent-files.json'),
                           'checker_old_sha256': OLD, 'checker_new_sha256': NEW,
                           'parent_created_at': old['created_at']})
    aes_flow.write(work / 'run.json', record)
    def interrupted(signum, frame):
        raise RuntimeError('Checkpoint continuation interrupted: ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGALRM, interrupted)
    signal.alarm(remaining)
    try:
        for stage in ('gds_export', 'routed_readback'):
            print('RUN ' + stage, flush=True)
            result = aes_flow.execute(stage, work, reference, args.runtime)
            result['stage'] = stage
            record['stages'].append(result)
            record['lineage']['new_native_stages'].append(stage)
            aes_flow.write(work / 'run.json', record)
            if result.get('passed') is not True:
                raise ValueError('Native continuation or independent gate failed: ' + stage)
        record['status'] = 'passed'
        record['physical_quality_passed'] = next(s['drc_gate']['quality_clean'] for s in stages if s['stage'] == 'drc')
    except Exception as exc:
        record.update(status='failed', error=str(exc))
        raise
    finally:
        signal.alarm(0)
        record['finished_at'] = time.time()
        aes_flow.write(work / 'run.json', record)


if __name__ == '__main__':
    main()
