"""Explicit Linux execution profile for the unchanged deterministic controller.

This module is installed only by remote_service. It never runs on the desktop.
Container argument templates are interpreted by remote_native; no Docker daemon
is used. The execution-profile hash is frozen along with the old backend inputs.
"""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import os
import sys
import copy
import hashlib

PROFILE = 'ssh-bwrap-quality-v2'


def python_compat():
    # Authorized server provides Python 3.10; emulate the streaming 3.11 API
    # without changing any preserved controller source or digest semantics.
    if not hasattr(hashlib,'file_digest'):
        def file_digest(stream,algorithm):
            result=hashlib.new(algorithm)
            while data:=stream.read(262144):result.update(data)
            return result
        hashlib.file_digest=file_digest


@contextmanager
def locked(folder):
    import fcntl
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    with (folder/'controller.lock').open('a+b') as stream:
        try: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('TASK_BUSY: server action is running') from None
        try: yield
        finally: fcntl.flock(stream, fcntl.LOCK_UN)


def is_worker_account():
    """Bind the worker to the non-root account explicitly configured by its operator."""
    import json
    if os.name != "posix":
        return False
    path=Path(__file__).resolve().parents[1]/"environments/remote-server.json"
    profile=json.loads(path.read_bytes())
    uid=profile.get("server_uid")
    return profile.get("enabled") is True and type(uid) is int and uid>0 and os.getuid()==uid


def install():
    python_compat()
    if not is_worker_account():
        raise RuntimeError('Remote profile requires the authorized server account')
    from . import main_task as task, ieda_runtime as rt
    from .remote_native import runtime_status
    task.locked = locked
    rt.docker = lambda: [sys.executable, '-B', '-m', 'macro_agent.remote_native']
    rt.status = runtime_status
    def invoke(args, timeout=20):
        # Worker-scoped native handles, never inspect or kill unrelated processes.
        from .remote_native import control
        return control(args)
    rt.invoke = invoke
    original = task.task_backend
    def backend(state):
        old = original(state)
        quality_enabled=state['contract'].get('case_id')=='swerv_nangate45' and (
            not state['contract'].get('backend_version') or state['contract'].get('case_manifest',{}).get('pre_route_quality_policy'))
        names = ('rt','STAGES','manifest','setup','execute','package')
        obj = SimpleNamespace(**{k:getattr(old,k) for k in names if hasattr(old,k)})
        obj.BACKEND_VERSION = old.BACKEND_VERSION+'-'+PROFILE
        if quality_enabled:obj.BACKEND_VERSION+='-preroute-v1'
        def manifest():
            value=copy.deepcopy(old.manifest())
            value['execution_profile']={'location':'server','profile':PROFILE,
                'cpu_policy':'affinity capped at registered cpu_threads',
                'memory_policy':'per-process RLIMIT_AS; not Docker cgroup RSS',
                'local_fallback':False,'single_native_job':True}
            if quality_enabled:
                from .hold_policy import POLICY
                value['pre_route_quality_policy']={'io_compatibility':'single-PORT rectangular pre-route IO',
                    'hpwl':'exact integer-DBU consistency required','hold':copy.deepcopy(POLICY),
                    'routing':'blocked without accepted pre-route review'}
            return value
        obj.manifest=manifest
        adjustment=state.get('contract',{}).get('branch_adjustment')
        def execute(stage,work):
            effect=None
            if adjustment and stage=='placement':
                from .feedback_control import apply_adjustment
                effect=apply_adjustment(Path(work),adjustment)
            if quality_enabled:
                from .quality_backend import execute as quality_execute
                reference=Path(state['contract'].get('input_root') or task.ROOT/'cases/ibench/swerv_nangate45')
                value=quality_execute(stage,work,reference)
            else:value=old.execute(stage,work)
            if state.get('contract',{}).get('case_id','').startswith('aes_'):
                from .route_quality import audit_stage
                value=audit_stage(stage,value,work,old.manifest())
                if value.get('passed') is not True:raise ValueError('REMOTE_QUALITY_EVIDENCE_GATE_FAILED: '+str(stage))
            if effect:
                effect['config_after_execution']=task.file_ref(Path(work)/'config/pl_default_config.json')
                effect['config_unchanged_during_execution']=effect['config_after_execution']==effect['config_before_execution']
                if not effect['config_unchanged_during_execution']:raise ValueError('ADJUSTMENT_CONFIG_CHANGED')
                effect['native_log']=task.file_ref(Path(value['log']))
                value['parameter_effect']=effect
            return value
        obj.execute=execute
        obj.input_files = lambda: old.input_files()+[
            Path(__file__), Path(__file__).with_name('remote_native.py'),
            Path(__file__).with_name('remote_service.py'),
            Path(__file__).with_name('route_quality.py'),
            Path(__file__).with_name('main_decisions.py'),
            Path(__file__).with_name('decision_experiments.py'),
            Path(__file__).with_name('knowledge.py'),
            Path(__file__).with_name('p1_perception.py'),
            Path(__file__).with_name('drc_counts.py'),
            Path(__file__).with_name('backend_checks.py'),
            Path(__file__).with_name('aes_reproduction.py'),
            Path(__file__).with_name('feedback_control.py'),
            task.ROOT/'dsh/knowledge/index.json',
            task.ROOT/'environments/remote-server.json']+([Path(__file__).with_name(n+'.py') for n in
                ('quality_backend','hold_policy','pin_metrics','def_io_compat')] if quality_enabled else [])
        return obj
    task.task_backend = backend
    return task
