"""Actionable host errors and local diagnostics without request/credential data."""
import json
import os
from pathlib import Path
import time
import traceback
import uuid

ROOT=Path(__file__).resolve().parents[1]


def error_response(exc, mode, root=ROOT):
    event_id=uuid.uuid4().hex[:12]
    frames=[{'file':f.filename,'line':f.lineno,'function':f.name}
            for f in traceback.extract_tb(exc.__traceback__)]
    diagnostic={'id':event_id,'time':time.time(),'mode':mode,
                'type':type(exc).__name__,'code':getattr(exc,'code',None),
                'winerror':getattr(exc,'winerror',None),'frames':frames}
    if hasattr(exc,'launch_failures'):
        diagnostic['launch_failures']=exc.launch_failures
    if hasattr(exc,'transport'):
        diagnostic['transport']=exc.transport
    # Do not persist exception text: remote errors can contain sensitive values.
    try:
        folder=Path(root)/'runs';folder.mkdir(parents=True,exist_ok=True)
        (folder/'dsh-host-last-error.json').write_text(json.dumps(diagnostic,indent=2),encoding='utf-8')
        with (folder/'dsh-host-errors.jsonl').open('a',encoding='utf-8') as handle:
            handle.write(json.dumps(diagnostic)+'\n')
        saved=True
    except OSError:
        saved=False
    code=getattr(exc,'code',None)
    from .login_window import requires_login
    needs_login=requires_login(exc)
    if needs_login:
        credential=Path(os.environ.get('LOCALAPPDATA',''))/'aiEDA/MacroAgent/auth/accounts.dpapi'
        detail='本地登录凭据文件缺失' if not credential.exists() else '登录授权已失效或未选择账号'
        message=f'AUTH_REQUIRED: {detail}。请重新完成 aiEDA 的官方 ChatGPT 登录，然后重发消息；Codex 登录不能代替此授权。'
    elif isinstance(exc,PermissionError):
        message=f'HOST_PERMISSION_DENIED: {mode} 阶段发生 Windows 权限错误（WinError {getattr(exc,"winerror",5)}）。'
    elif code=='network_error':
        message=f'NETWORK_ERROR: {mode} 阶段无法连接 OpenAI 服务，请检查网络或代理后重试。'
    else:
        message=f'{type(exc).__name__}: {exc}'
    if saved: message+=f' [诊断 {event_id}，runs/dsh-host-errors.jsonl]'
    else: message+=' [诊断日志也无法写入，请检查项目目录写权限]'
    return {'ok':False,'error':message,'code':code or type(exc).__name__, 'requires_login':needs_login}
