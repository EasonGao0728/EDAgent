"""User-operated ChatGPT sign-in window; no credential values in UI or logs."""
from pathlib import Path
import queue
import subprocess
import threading

from .chatgpt_auth import ChatGPTAuth
from .openai_http import OpenAIHTTP

ROOT = Path(__file__).resolve().parents[1]
LOGIN_CODES = frozenset({
    'sign_in_required', 'invalid_grant', 'invalid_token', 'unauthorized',
    'authentication_error', 'chatgpt_plan_permission_required',
    'subscription_sharing_not_enabled', 'subscription_sharing_not_authorized',
})


def requires_login(exc):
    return getattr(exc, 'code', None) in LOGIN_CODES or getattr(exc, 'status', None) == 401


def safe_failure(exc):
    """Never display str(exc): it can contain a URL, callback code, or token."""
    if requires_login(exc):
        return '需要登录或重新授权。点击“使用 ChatGPT 登录”，在官方浏览器页面完成授权。'
    if getattr(exc, 'code', None) == 'network_error':
        return '网络连接失败，无法确认授权是否可用。请检查网络或代理后重新检查；没有清除已有授权。'
    if isinstance(exc, PermissionError):
        return 'Windows 拒绝访问本地文件或进程。登录不能修复权限问题，请检查项目诊断日志。'
    return {
        'login_timeout': '登录等待超时。请重新点击登录，旧链接不能继续使用。',
        'browser_open_failed': '无法打开默认浏览器。请检查 Windows 默认浏览器设置后重新登录。',
        'auth_busy_retry_later': '另一个授权操作正在运行，请等待该窗口完成。',
        'credential_decryption_failed': '本地凭据无法解密。请检查 Windows 账号和文件权限；没有删除凭据。',
        'credential_file_invalid': '本地凭据文件异常，需要检查文件；没有覆盖或删除凭据。',
    }.get(getattr(exc, 'code', None), '检查未完成。请稍后重试，或查看 runs/dsh-host-errors.jsonl 中的诊断。')


def local_status(auth):
    status = auth.status()
    active = next((p for p in status['profiles'] if p['profile'] == status['active_profile']), None)
    if not active or not active['signed_in']:
        return '尚未登录 aiEDA。Codex 自身的登录不能替代 aiEDA 的授权。'
    if not active['plan_usage_enabled']:
        return '已有登录记录，但缺少订阅使用授权，请重新授权。'
    return '本机已保存 aiEDA 授权。尚未进行联网检查，不能据此确认服务可用。'


def check_connection(auth):
    # Metadata only: refresh if needed and check the account model catalog. No inference.
    from .chatgpt_provider import ChatGPTProvider
    models = ChatGPTProvider(auth=auth, http=auth.http).models()
    if not models:
        return '授权连接成功，但账号目前没有可见模型。请检查账号的模型访问权限。'
    return f'授权及模型目录检查通过（{len(models)} 个可见模型）。可返回 DSH 重试；这不等于推理与额度检查已通过。'


def launch_window():
    executable = ROOT / '.venv-agent/Scripts/pythonw.exe'
    if not executable.is_file():
        raise FileNotFoundError('aiEDA pythonw.exe missing')
    subprocess.Popen([str(executable), '-m', 'macro_agent.login_window'], cwd=ROOT,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                     close_fds=True)
    return {'requested': True, 'entry': str(ROOT / 'tools/chatgpt-login.cmd')}


def main():
    import tkinter as tk
    from tkinter import ttk, messagebox
    window = tk.Tk()
    window.title('aiEDA · ChatGPT 登录与连接')
    window.geometry('690x410')
    window.minsize(650, 400)
    frame = ttk.Frame(window, padding=24)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='ChatGPT 登录与连接', font=('Microsoft YaHei UI', 20, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='使用你已选择的 ChatGPT 订阅授权', font=('Microsoft YaHei UI', 11)).pack(anchor='w', pady=(8, 20))
    status = tk.StringVar(value='正在读取本地登录状态…')
    ttk.Label(frame, textvariable=status, wraplength=610, justify='left', font=('Microsoft YaHei UI', 11)).pack(anchor='w', fill='x', pady=(0, 20))
    buttons = ttk.Frame(frame)
    buttons.pack(anchor='w')
    events = queue.Queue()
    state = {'busy': False, 'auth': None, 'lock': None}

    def work(kind):
        try:
            if state['auth'] is None:
                state['auth'] = ChatGPTAuth(http=OpenAIHTTP(timeout=25))
            auth = state['auth']
            if kind == 'local':
                # Prevent simultaneous copies, without a credential-bearing local web endpoint.
                lock = auth.store.lock('login_window', timeout=0.2)
                lock.__enter__()
                state['lock'] = lock
                result = local_status(auth)
            elif kind == 'login':
                auth.login()  # Only invoked by the user's button; browser approval remains manual.
                result = '登录成功，授权已安全保存。请点击“检查连接”，然后返回 DSH 重试原消息。'
            else:
                result = check_connection(auth)
            events.put(('done', result))
        except Exception as exc:
            if kind == 'local' and getattr(exc, 'code', None) == 'auth_busy_retry_later':
                events.put(('duplicate', '登录窗口已经打开，请切换到该窗口。'))
                return
            from .bridge_errors import error_response
            error_response(exc, 'login_window_' + kind)
            events.put(('done', safe_failure(exc)))

    def start(kind):
        if state['busy']:
            return
        state['busy'] = True
        for button in (login, check):
            button.configure(state='disabled')
        status.set({'local': '正在读取本地登录状态…', 'login': '请在系统浏览器完成官方授权。完成后本窗口会显示最终结果，请勿提前关闭。',
                    'check': '正在联网检查授权及模型目录…（不调用模型生成）'}[kind])
        threading.Thread(target=work, args=(kind,), daemon=True).start()

    login = ttk.Button(buttons, text='使用 ChatGPT 登录', command=lambda: start('login'))
    login.pack(side='left', padx=(0, 12))
    check = ttk.Button(buttons, text='检查连接', command=lambda: start('check'))
    check.pack(side='left')
    ttk.Label(frame, text='登录成功后：返回 DSH，重试失败消息。\n网络异常与 Windows 权限错误需分别处理，重新登录不能代替这些修复。\n系统不会自动重放失败任务，也不会切换到 API Key 付费。',
              wraplength=610, justify='left').pack(anchor='w', pady=24)

    def close():
        if state['busy']:
            messagebox.showinfo('操作进行中', '请等待检查或登录结束后再关闭；登录最多等待 10 分钟。', parent=window)
            return
        if state['lock']:
            state['lock'].__exit__(None, None, None)
        window.destroy()

    def poll():
        try:
            kind, message = events.get_nowait()
        except queue.Empty:
            window.after(150, poll)
            return
        state['busy'] = False
        status.set(message)
        for button in (login, check):
            button.configure(state='normal')
        if kind == 'duplicate':
            messagebox.showinfo('aiEDA', message, parent=window)
            close()
            return
        window.after(150, poll)

    window.protocol('WM_DELETE_WINDOW', close)
    window.after(100, lambda: start('local'))
    window.after(150, poll)
    window.mainloop()


if __name__ == '__main__':
    main()
