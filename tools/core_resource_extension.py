"""One explicitly authorized Core routing-time extension, with preserved lineage.

No native execution occurs during preparation. The desktop-only worker loads a
sealed copy of the existing runner with exactly two timeout expressions changed.
The original producer files, seven design inputs and accepted stages stay intact.
"""
import copy
import hashlib
import json
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TASK = ROOT / 'runs/dsh-desktop-4247ed3bc3eefbe0/main-task'
BASE = ROOT / 'macro_agent/aes_flow.py'
BASE_SHA = 'aa5e76c451790b9b3421cf9f6f58ab7e29bef41cf6e04d14d3a15fb78b570381'
PREFIX = ['import_netlist', 'floorplan', 'fanout', 'placement', 'validate',
          'export_def', 'cts', 'to_drv', 'to_hold', 'legalization']
ROUTING_SECONDS = 18 * 3600
CONTINUATION_SECONDS = 20 * 3600
AUTHORIZATION = ('User approved on 2026-11-10: extend the next unfinished Core routing '
                 'attempt to 18 hours and allow 20 hours for continuation; preserve '
                 'the original timeout and all completed stages; CPU4/memory8GB, '
                 'algorithm, design inputs and quality gates unchanged.')
REPLACEMENTS = [
    ("seconds=m['budget'].get('routing_seconds',1800) if stage=='routing' else 1800",
     "seconds=64800 if stage=='routing' else 1800"),
    ("if not 0<seconds<=21600:raise ValueError('Stage deadline outside reviewed medium-AES ceiling')",
     "if not 0<seconds<=(64800 if stage=='routing' else 1800):raise ValueError('Stage deadline outside reviewed medium-AES ceiling')"),
]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def ref(path):
    return {'path': str(Path(path).resolve()), 'sha256': sha(path)}


def extended_source():
    if sha(BASE) != BASE_SHA:
        raise ValueError('Original native runner changed')
    source = BASE.read_text(encoding='utf-8')
    for before, after in REPLACEMENTS:
        if source.count(before) != 1:
            raise ValueError('Timeout expression is not unique')
        source = source.replace(before, after, 1)
    return source


def expected_budget(original, resumed_at):
    budget = copy.deepcopy(original['contract']['budget'])
    budget.update(wall_seconds=resumed_at + CONTINUATION_SECONDS - original['created_at'],
                  container_seconds=ROUTING_SECONDS, host_seconds=ROUTING_SECONDS + 20,
                  routing_seconds=ROUTING_SECONDS)
    return budget


def eligible(state, evidence):
    if state['contract']['case_id'] != 'aes_core_sky130_t' or state['contract']['goal'] != 'full_backend':
        raise ValueError('Wrong case or goal')
    if state['status'] != 'stopped_with_best' or state.get('pending'):
        raise ValueError('Wait for a stopped task with no pending native execution')
    if state['completed'] != PREFIX or state['failure_counts'].get('routing') != 1:
        raise ValueError('Exactly one failed routing attempt after the ten-stage prefix required')
    if state.get('resource_continuation') or state.get('quota_continuation'):
        raise ValueError('Already amended')
    budget = state['contract']['budget']
    if (budget['routing_seconds'], budget['container_seconds'], budget['host_seconds'],
            budget['wall_seconds'], budget['cpu_threads'], budget['memory_gb']) != (21600, 21600, 21620, 32400, 4, 8):
        raise ValueError('Original resource contract changed')
    if any(state['counts'][k] >= budget[k] for k in ('executions', 'model_calls')):
        raise ValueError('Count budget exhausted')
    if (evidence.get('stage') != 'routing' or evidence.get('passed') is not False
            or evidence.get('timed_out') is not True or evidence.get('deadline_seconds') != 21600):
        raise ValueError('Actual original six-hour routing timeout required')
    if evidence.get('storage_limit_exceeded') or evidence.get('file_size_limit_exceeded'):
        raise ValueError('A time extension cannot cure a storage failure')


def validate(state, folder=None):
    """Validate the amended run without changing it or resetting any counters."""
    from macro_agent import main_task as t
    folder = Path(folder or TASK).resolve()
    if folder != TASK.resolve():
        raise ValueError('Resource extension is limited to the authorized Core task')
    a = state.get('resource_continuation')
    if not isinstance(a, dict) or a.get('authorization') != AUTHORIZATION:
        raise ValueError('Missing exact resource authorization')
    for key in ('parent', 'failed_routing', 'runner_source', 'program', 'worker'):
        r = a[key]
        p = Path(r['path'])
        if not p.is_file() or sha(p) != r['sha256']:
            raise ValueError('Amendment evidence changed: ' + key)
    if Path(a['program']['path']).resolve() != Path(__file__).resolve():
        raise ValueError('Unexpected amendment program')
    if Path(a['worker']['path']).resolve() != ROOT / 'tools/dsh_resource_host.py':
        raise ValueError('Unexpected desktop worker')
    original = t.load(Path(a['parent']['path']))
    failed = t.load(Path(a['failed_routing']['path']))
    eligible(original, failed)
    if Path(a['runner_source']['path']).read_text(encoding='utf-8') != extended_source():
        raise ValueError('Runner differs beyond the two authorized timeout expressions')
    if a.get('routing_seconds') != ROUTING_SECONDS or a.get('continuation_seconds') != CONTINUATION_SECONDS:
        raise ValueError('Unauthorized resource values')
    if a.get('original_routing_budget_met') is not False:
        raise ValueError('Original timeout must remain reported as failed')
    if (a.get('new_deadline') != a['resumed_at'] + CONTINUATION_SECONDS
            or a.get('original_deadline') != original['created_at'] + original['contract']['budget']['wall_seconds']):
        raise ValueError('Amendment deadline history changed')
    if state['created_at'] != original['created_at']:
        raise ValueError('Original start time changed')
    expected = copy.deepcopy(original['contract'])
    expected['budget'] = expected_budget(original, a['resumed_at'])
    expected['all_inputs_hash'] = t.digest(state['input_refs'])
    if state['contract'] != expected:
        raise ValueError('Contract changed beyond audited runtime budget and adapter references')
    additions = [a['runner_source'], a['program'], a['worker']]
    if state['input_refs'] != original['input_refs'] + additions:
        raise ValueError('Frozen input references changed')
    t.verify_refs(state['input_refs'])
    if state['completed'][:len(PREFIX)] != PREFIX:
        raise ValueError('Accepted prefix changed')
    if any(state['results'].get(k) != original['results'][k] for k in PREFIX):
        raise ValueError('Accepted result was replaced')
    if any(state['counts'][k] < original['counts'][k] for k in ('executions', 'model_calls')):
        raise ValueError('Execution or model counter reset')
    if any(state['counts'][k] > state['contract']['budget'][k] for k in ('executions', 'model_calls')):
        raise ValueError('Count budget exceeded')
    if state['failure_counts'].get('routing', 0) < original['failure_counts']['routing']:
        raise ValueError('Original failure was removed')
    if state['events'][:len(original['events'])] != original['events']:
        raise ValueError('Original event history changed')
    if any(state['receipts'].get(k) != v for k, v in original['receipts'].items()):
        raise ValueError('Original receipt history changed')
    return {'passed': True, 'original_routing_budget_met': False,
            'routing_seconds': ROUTING_SECONDS, 'continuation_seconds': CONTINUATION_SECONDS,
            'native_binaries_scripts_design_inputs_and_quality_gates_unchanged': True,
            'parent': a['parent'], 'failed_routing': a['failed_routing'],
            'runner_source': a['runner_source'], 'authorization': AUTHORIZATION}


def prepare(apply=False):
    from macro_agent import main_task as t, ieda_runtime as rt
    with t.locked(TASK):
        state = t.load(TASK / 'task.json')
        failed_path = TASK / 'attempts/774def8107a9/routing-evidence.json'
        evidence = t.load(failed_path)
        eligible(state, evidence)
        t.verify_refs(state['input_refs'])
        for stage in PREFIX:
            result = state['results'][stage]
            t.verify_refs(result['artifact_refs'])
            if t.load(Path(result['receipt_ref'])) != result:
                raise ValueError('Accepted stage receipt changed')
        if any(n.startswith('aieda-') for n in rt.invoke(['ps', '--format', '{{.Names}}']).splitlines()):
            raise ValueError('Wait for all active aiEDA containers; do not interrupt them')
        source = extended_source()
        if not apply:
            return {'eligible': True, 'authorization': AUTHORIZATION,
                    'routing_seconds': ROUTING_SECONDS, 'continuation_seconds': CONTINUATION_SECONDS}
        audit = TASK / 'checkpoints/routing-time-extension-20261110'
        audit.mkdir(parents=True, exist_ok=False)
        (audit / 'task-before.json').write_bytes((TASK / 'task.json').read_bytes())
        (audit / 'aes_flow_runtime.py').write_text(source, encoding='utf-8', newline='\n')
        new = copy.deepcopy(state)
        now = time.time()
        a = {'authorization': AUTHORIZATION, 'resumed_at': now,
             'routing_seconds': ROUTING_SECONDS, 'continuation_seconds': CONTINUATION_SECONDS,
             'original_routing_budget_met': False, 'new_deadline': now + CONTINUATION_SECONDS,
             'original_deadline': state['created_at'] + state['contract']['budget']['wall_seconds'],
             'parent': ref(audit / 'task-before.json'), 'failed_routing': ref(failed_path),
             'runner_source': ref(audit / 'aes_flow_runtime.py'), 'program': ref(__file__),
             'worker': ref(ROOT / 'tools/dsh_resource_host.py')}
        new['resource_continuation'] = a
        new['contract']['budget'] = expected_budget(state, now)
        new['input_refs'] += [a['runner_source'], a['program'], a['worker']]
        new['contract']['all_inputs_hash'] = t.digest(new['input_refs'])
        new['revision'] += 1
        new['events'].append({'action': 'authorized_routing_time_extension',
                              'status': 'stopped_with_best', **a})
        validate(new)
        t.save(audit / 'amendment.json', a)
        t.save(TASK / 'task.json', new)
        return a


def install_for_request(request):
    """Use the unchanged controller; replace only this task's routing executor."""
    from macro_agent import main_task as t
    if request.get('mode') != 'task' or Path(request.get('run', '')).resolve() != TASK.resolve():
        raise ValueError('Extended worker cannot handle other requests')
    validate(t.load(TASK / 'task.json'))
    original_backend = t.task_backend
    original_view = t.view

    def amended_view(state, folder):
        value = original_view(state, folder)
        value['resource_continuation'] = state['resource_continuation']
        value['original_routing_resource_budget_met'] = False
        return value

    def backend_for(state):
        audit = validate(state)
        backend = original_backend(state)
        original_execute = backend.execute
        original_package = backend.package
        source_path = Path(state['resource_continuation']['runner_source']['path'])
        module = types.ModuleType('macro_agent._authorized_core_runtime')
        # Preserve original asset-root resolution; traceback points to sealed copy.
        module.__file__ = str(BASE)
        module.__package__ = 'macro_agent'
        exec(compile(source_path.read_text(encoding='utf-8'), str(source_path), 'exec'), module.__dict__)

        def execute(stage, work):
            if stage != 'routing':
                return original_execute(stage, work)
            work = Path(work).resolve()
            if work.parent != TASK / 'attempts' or work == Path(state['accepted_work']).resolve():
                raise ValueError('Extended routing requires a fresh private attempt')
            policy_path = work / 'execution-policy.json'
            policy = t.load(policy_path)
            if policy['routing_seconds'] != 21600:
                raise ValueError('Expected original cloned execution policy')
            policy.update(routing_seconds=ROUTING_SECONDS,
                          authorized_runtime_extension=audit,
                          original_policy_sha256=sha(policy_path))
            t.save(policy_path, policy)
            value = module.execute(stage, work, state['contract']['input_root'])
            if value.get('passed') is not True:
                raise ValueError('AES_BACKEND_GATE_FAILED: ' + str(Path(work) / 'routing-evidence.json'))
            value['authorized_runtime_extension'] = audit
            return value

        backend.execute = execute

        def package(final_state, folder, active_backend):
            value = original_package(final_state, folder, active_backend)
            folder = Path(folder)
            acceptance = t.load(folder / 'acceptance.json')
            acceptance['authorized_resource_extension'] = validate(final_state, folder)
            acceptance['original_routing_resource_budget_met'] = False
            t.save(folder / 'acceptance.json', acceptance)
            report = folder / 'report.html'
            notice = ('<p style="padding:16px;background:#fff0d5;color:#8b3500">'
                      '原六小时路由时间预算未通过：首次路由超时，原失败记录已保留。'
                      '经用户授权，仅将未完成路由的上限延长至18小时、续接总时限20小时；'
                      '前10阶段未重跑，CPU4核/内存8GB、输入、算法和质量检查不变。'
                      '新预算下完成不代表原资源预算通过。</p>')
            report.write_text(report.read_text(encoding='utf-8').replace('</h1>', '</h1>'+notice, 1),encoding='utf-8')
            value['acceptance'] = ref(folder / 'acceptance.json')
            value['report'] = ref(report)
            return value

        backend.package = package
        return backend

    t.task_backend = backend_for
    t.view = amended_view


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.apply)))
