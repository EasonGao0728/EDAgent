"""Audited host maintenance for a Windows reboot during local AES execution.

No native work is accepted or executed here. A fresh OS boot and an empty,
reachable Docker engine prove the old local process cannot still be running.
The frozen controller, inputs, accepted receipts and original budgets stay intact.
Normal DSH observe/resume/act calls must perform all subsequent work.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from macro_agent import main_task as tasks, ieda_runtime as rt


def collect_host_evidence():
    if os.name != 'nt':
        raise ValueError('This recovery only supports local Windows Docker tasks')
    code = "[DateTimeOffset]((Get-CimInstance Win32_OperatingSystem).LastBootUpTime).ToUniversalTime() | ForEach-Object { $_.ToUnixTimeMilliseconds() }"
    p = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code],
                       capture_output=True, text=True, timeout=20, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    boot = int(p.stdout.strip()) / 1000
    engine = json.loads(rt.invoke(['info', '--format', '{{json .}}']))
    containers = rt.invoke(['ps', '-a', '--format', '{{json .}}'])
    return {'observed_at': time.time(), 'boot_epoch': boot,
            'boot_source': 'Win32_OperatingSystem.LastBootUpTime',
            'engine_os': engine['OSType'], 'engine_id': engine['ID'],
            'engine_version': engine['ServerVersion'],
            'containers': [json.loads(line) for line in containers.splitlines() if line.strip()]}


def validate_interruption(state, folder, evidence, now):
    pending = state.get('pending')
    if state['status'] != 'running' or not pending:
        raise ValueError('Running task with an uncertain local execution required')
    if state['contract'].get('goal') != 'full_backend' or state['contract'].get('case_id') not in (
            'aes_sky130_t', 'aes_legacy', 'aes_core_sky130_t'):
        raise ValueError('Only registered local AES full-backend tasks are supported')
    budget = state['contract']['budget']
    if now >= state['created_at'] + budget['wall_seconds']:
        raise ValueError('Original task wall budget exhausted; recovery cannot extend it')
    if abs(now - evidence['observed_at']) > 30 or evidence['engine_os'] != 'linux' or not evidence['engine_id']:
        raise ValueError('Fresh reachable Linux engine evidence required')
    if evidence['containers']:
        raise ValueError('Engine must contain no containers; never kill or alter unknown jobs')
    started = pending['safe_retry_after'] - max(150, budget['host_seconds'] + 10)
    boot = evidence['boot_epoch']
    if not state['created_at'] <= started < boot - 2 <= now:
        raise ValueError('OS boot must postdate this exact pending execution')
    work = Path(pending['work']).resolve()
    if work.parent != folder / 'attempts' or not work.is_dir() or work.is_symlink():
        raise ValueError('Pending attempt path outside this task')
    if (work / 'stage-receipt.json').exists():
        raise ValueError('Completed receipt exists; use normal recover to validate it')
    log = work / 'logs' / (pending['action'] + '.log')
    if not log.is_file() or log.stat().st_size == 0 or log.stat().st_mtime >= boot:
        raise ValueError('Require a nonempty interrupted log predating the reboot')
    return {'started_epoch': started, 'boot_epoch': boot, 'interrupted_log': tasks.file_ref(log),
            'log_mtime': log.stat().st_mtime, 'pending': copy.deepcopy(pending)}


def mark_stopped(state, receipt):
    repaired = copy.deepcopy(state)
    interrupted = repaired['pending']
    repaired['pending'] = None
    repaired['status'] = 'stopped_with_best'
    repaired['stop_reason'] = 'Verified Windows reboot interrupted native ' + interrupted['action'] + '; accepted checkpoint preserved. DSH resume required.'
    repaired['revision'] += 1
    repaired['events'].append({'action': interrupted['action'], 'status': 'interrupted_host_reboot',
                               'work': interrupted['work'], 'action_id': interrupted['action_id'],
                               'recovery_receipt': receipt, 'accepted': False,
                               'budgets_reset': False, 'native_execution_started_by_recovery': False})
    return repaired


def recover(folder, apply=False):
    folder = Path(folder).resolve()
    if not folder.is_relative_to(ROOT / 'runs'):
        raise ValueError('Task must be inside project runs')
    with tasks.locked(folder):
        state = tasks.load(folder / 'task.json')
        tasks.verify_refs(state['input_refs'])
        backend = tasks.task_backend(state)
        if state['completed'] != backend.STAGES[:len(state['completed'])]:
            raise ValueError('Accepted stages are not a complete prefix')
        if state['pending']['action'] != backend.STAGES[len(state['completed'])]:
            raise ValueError('Pending action is not the next stage')
        for stage in state['completed']:
            result = state['results'][stage]
            tasks.verify_refs(result['artifact_refs'])
            if tasks.load(Path(result['receipt_ref'])) != result:
                raise ValueError('Accepted receipt changed: ' + stage)
        evidence = collect_host_evidence()
        interrupted = validate_interruption(state, folder, evidence, time.time())
        if not apply:
            return {'eligible': True, 'applied': False, 'evidence': evidence, 'interrupted': interrupted}
        recovery = folder / 'checkpoints' / ('host-reboot-' + uuid.uuid4().hex[:12])
        recovery.mkdir(parents=True, exist_ok=False)
        before = recovery / 'task-before.json'
        before.write_bytes((folder / 'task.json').read_bytes())
        record = {'schema_version': 'verified_host_reboot_recovery_v1', 'host': evidence,
                  'interrupted': interrupted, 'before': tasks.file_ref(before),
                  'recovery_program': tasks.file_ref(Path(__file__)),
                  'controller': tasks.file_ref(Path(tasks.__file__)),
                  'accepted_stages_preserved': list(state['completed']),
                  'budgets_reset': False, 'deadline_epoch': state['created_at'] + state['contract']['budget']['wall_seconds'],
                  'native_execution_started': False, 'accepted_interrupted_output': False}
        receipt = recovery / 'recovery.json'
        tasks.save(receipt, record)
        updated = mark_stopped(state, tasks.file_ref(receipt))
        # Invariants checked immediately before the atomic state transition.
        for key in ('contract', 'input_refs', 'counts', 'failure_counts', 'created_at', 'completed', 'results', 'accepted_work', 'receipts'):
            if updated[key] != state[key]:
                raise ValueError('Recovery altered protected state: ' + key)
        # Recheck engine availability and absence under the same task lock.
        fresh = collect_host_evidence()
        validate_interruption(state, folder, fresh, time.time())
        if fresh['boot_epoch'] != evidence['boot_epoch'] or fresh['engine_id'] != evidence['engine_id']:
            raise ValueError('Host identity changed during recovery')
        tasks.save(folder / 'task.json', updated)
        return {'applied': True, 'status': updated['status'], 'counts': updated['counts'],
                'accepted_stages': updated['completed'], 'recovery_receipt': str(receipt),
                'deadline_epoch': record['deadline_epoch'], 'native_execution_started': False}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run', required=True)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    print(json.dumps(recover(args.run, args.apply), ensure_ascii=False))
