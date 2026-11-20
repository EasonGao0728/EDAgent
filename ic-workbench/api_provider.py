"""User-entered API configuration. Secrets never enter browser state or logs."""
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from macro_agent.chatgpt_auth import CredentialStore
from macro_agent.dsh_native import translate
from macro_agent.chatgpt_provider import completed_response


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate_config(req):
    url = str(req.get('base_url', '')).rstrip('/')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')):
        raise ValueError('仅支持 HTTPS 服务，或本机 HTTP 模型服务')
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('API 地址不能包含账号、查询参数或片段')
    if req.get('protocol') not in ('responses', 'chat_completions'):
        raise ValueError('请选择 Responses 或 Chat Completions 协议')
    key = req.get('key', '')
    if not isinstance(key, str) or len(key) > 4096 or any(c in key for c in '\r\n'):
        raise ValueError('无效 API 密钥')
    if not key and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('远程服务需要填写 API 密钥')
    models = req.get('models', [])
    if not isinstance(models, list) or not models or len(models) > 30 or any(not isinstance(m, str) or not m.strip() or len(m) > 100 for m in models):
        raise ValueError('请填写 1–30 个模型名称')
    return {'base_url': url, 'protocol': req['protocol'], 'key': key, 'models': models}


def store():
    return CredentialStore(Path(os.environ['LOCALAPPDATA']) / 'aiEDA/SiliconWorkbench/api')


def metadata(config):
    return {k: config[k] for k in ('base_url', 'protocol', 'models')} | {'configured': True}


def request(config, suffix, body=None, stream=False):
    headers = {'Content-Type': 'application/json', 'Accept': 'text/event-stream' if stream else 'application/json'}
    if config['key']:
        headers['Authorization'] = 'Bearer ' + config['key']
    req = Request(config['base_url'] + suffix, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    return build_opener(NoRedirect).open(req, timeout=180)


def main(req):
    storage = store()
    if req['mode'] == 'save':
        config = validate_config(req)
        with storage.lock():
            storage.save({'api': config})
        return metadata(config)
    with storage.lock():
        config = storage.load().get('api')
    if req['mode'] == 'status':
        return metadata(config) if config else {'configured': False}
    if not config:
        raise ValueError('请先在登录窗口配置 API')
    if req['mode'] == 'check':
        with request(config, '/models') as response:
            data = json.loads(response.read(2_000_001))
        models = [m['id'] for m in data.get('data', []) if isinstance(m.get('id'), str)]
        return {'connected': True, 'models': models[:100], 'note': '模型目录可访问；尚未验证工具调用或执行 EDA'}
    if req['mode'] != 'infer' or req['model'] not in config['models']:
        raise ValueError('模型不在此连接的配置列表中')
    if config['protocol'] == 'responses':
        instructions, inputs = translate(req['messages'])
        body = {'model': req['model'], 'instructions': instructions, 'input': inputs, 'store': False, 'stream': True,
                'tools': [{'type': 'function', **t, 'strict': False} for t in req['tools']], 'parallel_tool_calls': False}
        if req['effort'] != 'none':
            body['reasoning'] = {'effort': req['effort']}
        with request(config, '/responses', body, stream=True) as response:
            result = completed_response(response)
        blocks = []
        for item in result.get('output', []):
            if item.get('type') == 'function_call':
                blocks.append({'type': 'tool-call', 'id': item['call_id'], 'name': item['name'], 'arguments': item['arguments']})
            elif item.get('type') == 'message':
                blocks.extend({'type': 'text', 'text': c['text']} for c in item.get('content', []) if c.get('type') == 'output_text')
    else:
        messages = []
        for m in req['messages']:
            text = '\n'.join(b.get('text', '') for b in m.get('content', []) if b.get('type') == 'text')
            row = {'role': m['role'], 'content': text}
            if m['role'] == 'tool':
                row['tool_call_id'] = m['toolCallId']
            calls = [{'id': b['id'], 'type': 'function', 'function': {'name': b['name'], 'arguments': b['arguments']}} for b in m.get('content', []) if b.get('type') == 'tool-call']
            if calls:
                row['tool_calls'] = calls
            messages.append(row)
        body = {'model': req['model'], 'messages': messages, 'tools': [{'type': 'function', 'function': t} for t in req['tools']], 'stream': False}
        if req['effort'] != 'none':
            body['reasoning_effort'] = req['effort']
        with request(config, '/chat/completions', body) as response:
            raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError('模型返回超出大小限制')
        result = json.loads(raw)
        choice = result['choices'][0]
        if choice.get('finish_reason') not in ('stop', 'tool_calls'):
            raise ValueError('模型返回未完成，未执行工具')
        message = choice['message']
        blocks = [{'type': 'text', 'text': message['content']}] if message.get('content') else []
        blocks.extend({'type': 'tool-call', 'id': b['id'], 'name': b['function']['name'], 'arguments': b['function']['arguments']} for b in message.get('tool_calls', []))
    if not blocks:
        raise ValueError('模型返回为空')
    return {'blocks': blocks, 'usage': result.get('usage', {})}


if __name__ == '__main__':
    try:
        print(json.dumps({'ok': True, 'value': main(json.load(sys.stdin))}, ensure_ascii=False))
    except HTTPError as exc:
        print(json.dumps({'ok': False, 'error': 'API_HTTP_' + str(exc.code)}))
    except ValueError as exc:
        # Only locally-authored validation errors; JSON errors must not echo data.
        error = 'API 返回格式不兼容' if isinstance(exc, json.JSONDecodeError) else str(exc)
        print(json.dumps({'ok': False, 'error': error}, ensure_ascii=False))
    except Exception:
        print(json.dumps({'ok': False, 'error': 'API 连接失败；请检查地址、授权、协议及工具调用支持'}, ensure_ascii=False))
