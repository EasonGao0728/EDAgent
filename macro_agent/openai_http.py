"""Small, bounded HTTPS transport. Never include server messages or credentials in errors."""
from __future__ import annotations

import json
import http.client
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from .common import loads

AUTH = "https://auth.openai.com"
API = "https://api.openai.com/v1"

REMOTE_CODES = {"invalid_grant", "invalid_client", "invalid_request", "invalid_request_error",
                "access_denied", "insufficient_scope", "unauthorized", "invalid_token", "unsupported_parameter",
                "model_not_found", "rate_limit_exceeded", "server_error", "authentication_error",
                "subscription_sharing_usage_limit_exceeded", "subscription_sharing_usage_unavailable",
                "subscription_sharing_not_enabled", "subscription_sharing_not_authorized",
                "insufficient_quota", "permission_denied"}


def remote_code(value):
    return value if value in REMOTE_CODES else "remote_error"


class OpenAIError(RuntimeError):
    abort_run = True  # Service/auth/transport failures cannot be repaired by generated placement code.

    def __init__(self, code, status=None):
        self.code = code if re.fullmatch(r"[a-z][a-z0-9_]{0,95}", str(code)) else "unknown_error"
        self.status = status
        super().__init__(f"OpenAI: {self.code}" + (f" (HTTP {status})" if status else ""))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Do not forward bearer credentials to a redirected host.


class HandshakeConnection(http.client.HTTPSConnection):
    def connect(self):
        # connect() returns before http.client sends any origin HTTP headers or body.
        # Retry only a closed handshake, using the same proxy, SNI and trust store.
        timeout = self.timeout
        deadline = time.monotonic() + timeout if isinstance(timeout, (float, int)) else None
        try:
            for attempt in range(3):
                if deadline is not None:
                    self.timeout = max(0.001, deadline - time.monotonic())
                try:
                    super().connect()
                    if self.sock is not None and deadline is not None:
                        self.sock.settimeout(timeout)
                    return
                except (ssl.SSLEOFError, ConnectionResetError):
                    if self.sock is not None:
                        self.sock.close()
                        self.sock = None
                    backoff = 0.5 * (attempt + 1)
                    if attempt == 2 or (deadline is not None and time.monotonic() + backoff >= deadline):
                        raise
                    time.sleep(backoff)
        finally:
            self.timeout = timeout


class HandshakeHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(HandshakeConnection, req, context=self._context)


class OpenAIHTTP:
    def __init__(self, timeout=180):
        self.timeout = timeout
        self.opener = urllib.request.build_opener(NoRedirect(), HandshakeHandler())

    def open(self, url, *, token=None, body=None, form=None, stream=False):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc not in {"auth.openai.com", "api.openai.com"}:
            raise OpenAIError("untrusted_endpoint")
        headers = {"Accept": "text/event-stream" if stream else "application/json",
                   "User-Agent": "aiEDA-Macro-Agent/0.1"}
        data = None
        if token:
            headers["Authorization"] = "Bearer " + token
        if form is not None:
            data = urllib.parse.urlencode(form).encode("ascii")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            return self.opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            code = "http_error"
            try:
                error = loads(exc.read(65536).decode("utf-8")).get("error")
                code = error.get("code") or error.get("type") if isinstance(error, dict) else error
            except Exception:
                pass
            raise OpenAIError(remote_code(code) if isinstance(code, str) else "http_error", exc.code) from None
        except (OSError, urllib.error.URLError) as exc:
            error=OpenAIError("network_error")
            reason=getattr(exc,'reason',exc)
            error.transport={'host':parsed.hostname,'path':parsed.path,
                             'type':type(reason).__name__,'errno':getattr(reason,'errno',None),
                             'winerror':getattr(reason,'winerror',None)}
            raise error from None

    def json(self, url, **kwargs):
        with self.open(url, **kwargs) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise OpenAIError("response_too_large")
        try:
            result = loads(data.decode("utf-8"))
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, UnicodeError):
            raise OpenAIError("invalid_json_response") from None
