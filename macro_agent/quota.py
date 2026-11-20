"""Read-only Codex app-server quota checks; never reads or copies auth files."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def codex_candidates():
    # A long-lived DSH process can retain a PATH from before a Codex update.
    # Discover the current per-user installation afresh on every request.
    base = Path(os.environ.get('LOCALAPPDATA', '')) / 'OpenAI/Codex/bin'
    candidates = sorted(base.glob('*/codex.exe'), key=lambda p: p.stat().st_mtime, reverse=True)
    # Desktop and terminal PATH can differ. Discover the current user's installed
    # Store package through Windows, rather than guessing a versioned package path.
    if os.name == 'nt':
        try:
            installed=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',
                '(Get-AppxPackage -Name OpenAI.Codex).InstallLocation'],capture_output=True,text=True,
                timeout=8,creationflags=subprocess.CREATE_NO_WINDOW)
            for location in installed.stdout.splitlines():
                executable=Path(location.strip())/'app/resources/codex.exe'
                if location.strip() and executable.is_file(): candidates.append(executable)
        except (OSError,subprocess.TimeoutExpired): pass
    found = shutil.which('codex')
    if found and Path(found).suffix.lower() == '.exe':
        candidates.append(Path(found))
    return list(dict.fromkeys(str(p) for p in candidates))


def codex_executable():
    candidates = codex_candidates()
    if candidates: return candidates[0]
    raise ValueError('QUOTA_UNAVAILABLE: 未找到 Codex，请确认本机 Codex 已安装并登录。')


def start_server(*, direct=False):
    failures=[]
    launch_options={}
    if direct:
        # Only this read-only child process bypasses the host proxy for the
        # official quota host. TLS, Codex-managed credentials and account checks
        # are unchanged. Never modify the parent or Windows proxy configuration.
        env=os.environ.copy()
        bypass=next((v for k,v in env.items() if k.lower()=='no_proxy'), '')
        env={k:v for k,v in env.items() if k.lower()!='no_proxy'}
        env['NO_PROXY']=','.join(filter(None,[bypass,'chatgpt.com']))
        launch_options['env']=env
    for executable in codex_candidates():
        try:
            return subprocess.Popen([executable, 'app-server', '--listen', 'stdio://'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                encoding='utf-8', text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                **launch_options)
        except OSError as exc:
            failures.append({'executable':executable,'errno':exc.errno,
                             'winerror':getattr(exc,'winerror',None)})
    error=ValueError('QUOTA_LAUNCH_FAILED: 无法启动本机 Codex 额度查询进程；请检查安装路径或文件权限。没有调用模型。')
    error.launch_failures=failures
    raise error


def stop_server(proc):
    # Windows may report access denied if the process exits between poll and
    # terminate. Cleanup must not replace the original result/error.
    for action in ('terminate','kill'):
        if proc.poll() is not None: return
        try:
            getattr(proc,action)()
            proc.wait(timeout=3)
            return
        except (OSError,subprocess.TimeoutExpired):
            continue


def read_limits(timeout=25, *, direct=False):
    proc = start_server(direct=direct)
    messages = queue.Queue()
    def reader():
        try:
            for line in proc.stdout:
                if len(line) > 1_000_000:
                    continue
                try: messages.put(json.loads(line))
                except ValueError: pass
        finally:
            messages.put(None)
    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    def send(value):
        proc.stdin.write(json.dumps(value) + '\n')
        proc.stdin.flush()
    def rpc(identifier, method, params):
        send({'id': identifier, 'method': method, 'params': params})
        while True:
            remaining = deadline-time.monotonic()
            if remaining <= 0: raise TimeoutError()
            item = messages.get(timeout=remaining)
            if item is None: raise RuntimeError('server exited')
            if item.get('id') == identifier:
                if 'error' in item: raise RuntimeError('quota RPC failed')
                return item['result']
    try:
        rpc(1, 'initialize', {'clientInfo': {'name':'aieda_quota', 'title':'aiEDA quota reader', 'version':'0.1.0'}})
        send({'method':'initialized'})
        return rpc(2, 'account/rateLimits/read', {})
    except (TimeoutError, queue.Empty, RuntimeError, OSError, KeyError):
        raise ValueError('QUOTA_UNAVAILABLE: 自动查询额度失败；请检查网络与 Codex 登录状态后重试。未使用过期额度。') from None
    finally:
        stop_server(proc)
        try: proc.stdin.close()
        except OSError: pass
        thread.join(timeout=1)
        # Do not block on the text stream's lock if the reader is still alive.
        if not thread.is_alive(): proc.stdout.close()


def snapshot(result, expected_account):
    if result.get('accountId') != expected_account:
        raise ValueError('QUOTA_ACCOUNT_MISMATCH: Codex 当前账号与项目绑定账号不同。')
    buckets = result.get('rateLimitsByLimitId')
    bucket = buckets.get('codex') if isinstance(buckets, dict) else result.get('rateLimits')
    if not isinstance(bucket, dict) or bucket.get('limitId') != 'codex':
        raise ValueError('QUOTA_UNKNOWN: 未返回本项目所需的 Codex 额度。')
    weekly = [bucket.get(k) for k in ('primary','secondary') if isinstance(bucket.get(k), dict) and bucket[k].get('windowDurationMins') == 10080]
    if not weekly:
        raise ValueError('QUOTA_UNKNOWN: 未返回周额度窗口，无法核验当前额度。')
    values = [w.get('usedPercent') for w in weekly]
    if any(type(v) not in (int,float) or not math.isfinite(v) or not 0 <= v <= 100 for v in values):
        raise ValueError('QUOTA_UNKNOWN: 服务返回的周额度无效。')
    return {'source':'codex_usage_limits', 'acquisition':'codex_app_server_account_rateLimits_read',
        'accountId':expected_account, 'windowDurationMins':10080,
        'remainingPercent':100-max(values), 'checkedAt':time.time()*1000,
        'ordinaryUsageAllowed': result.get('ordinaryUsageAllowed'),
        'resetsAt':weekly[0].get('resetsAt')}


def quota_threshold(policy):
    value=policy.get('stopBelowPercent',20)
    if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= 100):
        raise ValueError('QUOTA_POLICY_INVALID: 停止线须为0至100，或null表示取消。')
    return value


def read_policy():
    return json.loads((ROOT/'dsh/quota-policy.json').read_text(encoding='utf-8'))


def ensure_quota(file=None, *, reader=None):
    policy=read_policy()
    threshold=quota_threshold(policy)
    preferred=policy.get('preferredRoute','configured')
    if preferred not in ('configured','direct'):
        raise ValueError('QUOTA_UNKNOWN: 无效的额度查询连接方式。')
    # A fresh read may fail transiently before any model request. Retry reads,
    # never substitute a cached value or retry an account/limit rejection.
    for attempt in range(3):
        route=preferred if attempt%2==0 else ('configured' if preferred=='direct' else 'direct')
        try:
            result=reader() if reader else read_limits(direct=route=='direct')
            break
        except ValueError as exc:
            if not str(exc).startswith('QUOTA_UNAVAILABLE:') or attempt==2: raise
            time.sleep(attempt+1)
    q=snapshot(result,policy['accountId'])
    q['transportRoute']='injected_reader' if reader else route
    q['stopBelowPercent']=threshold
    path=Path(file or ROOT/'.cache/dsh-quota.json').resolve()
    if not path.is_relative_to(ROOT/'.cache'):
        raise ValueError('Invalid quota snapshot path')
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(q,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)
    if threshold is not None and q['remainingPercent']<threshold:
        raise ValueError(f"QUOTA_STOP: 周额度剩余 {q['remainingPercent']}%，低于{threshold}%停止线。")
    if q['ordinaryUsageAllowed'] is False:
        raise ValueError('QUOTA_STOP: 服务当前不允许模型使用，请等待额度恢复。')
    return q
