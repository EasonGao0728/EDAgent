"""Official Sign in with ChatGPT public-client flow, with isolated Windows storage.

No Codex credentials, API keys, browser cookies, or third-party client IDs are read.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import uuid
import webbrowser

from .common import loads
from .openai_http import API, AUTH, OpenAIError, OpenAIHTTP

SCOPE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PERMISSION = "chatgpt.tokens.use.direct"
DISCOVERY = AUTH + "/.well-known/openid-configuration"
APP_NAME = "aiEDA Macro Agent"


def _dpapi(data, *, decrypt=False):
    if os.name != "nt":
        raise OpenAIError("windows_credential_storage_required")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OpenAIError("credential_decryption_failed" if decrypt else "credential_encryption_failed")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


class CredentialStore:
    """Whole record is DPAPI encrypted. The folder ACL excludes inherited users."""
    def __init__(self, directory=None):
        if os.name != "nt":
            raise OpenAIError("windows_credential_storage_required")
        self.directory = Path(directory) if directory else Path(os.environ["LOCALAPPDATA"]) / "aiEDA/MacroAgent/auth"
        self.directory.mkdir(parents=True, exist_ok=True)
        # SID from whoami is independent of localized Windows account names.
        import csv
        sid = next(csv.reader(subprocess.check_output(
            ["whoami", "/user", "/fo", "csv", "/nh"], text=True).splitlines()))[1]
        if not sid.startswith("S-1-"):
            raise OpenAIError("credential_acl_failed")
        result = subprocess.run(["icacls", str(self.directory), "/inheritance:r", "/grant:r",
                                 f"*{sid}:(OI)(CI)F"], capture_output=True)
        if result.returncode:
            raise OpenAIError("credential_acl_failed")
        self.path = self.directory / "accounts.dpapi"

    @contextmanager
    def lock(self, name="session", timeout=10):
        import msvcrt
        with (self.directory / (name + ".lock")).open("a+b") as handle:
            if handle.seek(0, 2) == 0:
                handle.write(b"\0")
                handle.flush()
            deadline = time.monotonic() + timeout
            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise OpenAIError("auth_busy_retry_later") from None
                    time.sleep(0.1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def load(self):
        if not self.path.exists():
            return {"version": 1, "host_id": "urn:uuid:" + str(uuid.uuid4()), "active": None, "profiles": {}}
        try:
            return loads(_dpapi(self.path.read_bytes(), decrypt=True).decode("utf-8"))
        except OpenAIError:
            raise
        except Exception:
            raise OpenAIError("credential_file_invalid") from None

    def save(self, value):
        encrypted = _dpapi(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        temporary = self.path.with_name("accounts-" + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)


class LoginAttempt:
    def __init__(self, host_id, redirect_uri, registration=None):
        self.registration = registration or {}
        self.client_id = self.registration.get("client_id")
        self.state, self.nonce, self.verifier = (secrets.token_urlsafe(n) for n in (32, 32, 64))
        self.redirect_uri, self.used = redirect_uri, False
        self.expires = time.monotonic() + 600
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        params = {"client_id": self.client_id or "dynamic_agent_client", "ext_agent_host_id": host_id,
                  "response_type": "code", "redirect_uri": redirect_uri, "scope": SCOPE, "resource": API,
                  "state": self.state, "nonce": self.nonce, "code_challenge_method": "S256", "code_challenge": challenge}
        if self.client_id:
            if self.registration.get("id_token"):
                params["id_token_hint"] = self.registration["id_token"]
            if self.registration.get("email"):
                params["login_hint"] = self.registration["email"]
        else:
            params["agent_name_hint"] = APP_NAME
        self.authorization_url = AUTH + "/api/accounts/authorize?" + urlencode(params)

    def consume(self, query):
        if self.used or time.monotonic() >= self.expires:
            raise OpenAIError("login_expired_or_reused")
        self.used = True
        params = parse_qs(query, keep_blank_values=True, max_num_fields=15)
        if any(len(value) != 1 for value in params.values()):
            raise OpenAIError("invalid_callback")
        if not secrets.compare_digest(params.get("state", [""])[0], self.state):
            raise OpenAIError("state_mismatch")
        if "error" in params:
            raise OpenAIError("authorization_denied")
        returned = params.get("client_id", [None])[0]
        if self.client_id and returned and self.client_id != returned:
            raise OpenAIError("client_id_mismatch")
        issued = self.client_id or returned
        if not issued or not issued.startswith("oaiapp_"):
            raise OpenAIError("registration_incomplete")
        self.client_id = issued
        code = params.get("code", [""])[0]
        if not code:
            raise OpenAIError("missing_authorization_code")
        return {"grant_type": "authorization_code", "client_id": issued, "code": code,
                "code_verifier": self.verifier, "redirect_uri": self.redirect_uri, "resource": API}


class ExpiredIdentityError(OpenAIError):
    """A signed ID token expired; never treat it as a valid login identity."""
    def __init__(self):
        super().__init__('id_token_validation_failed')


def validate_identity(token, client_id, jwks, nonce=None):
    try:
        import jwt
    except ImportError:
        raise OpenAIError("install_chatgpt_dependencies") from None
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256":
            raise ValueError()
        matches = [key for key in jwks["keys"] if key.get("kid") == header.get("kid")
                   and key.get("kty") == "RSA" and key.get("use", "sig") == "sig"
                   and key.get("alg", "RS256") == "RS256"]
        if len(matches) != 1:
            raise ValueError()
        key = jwt.PyJWK.from_dict(matches[0], algorithm="RS256").key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=client_id, issuer=AUTH, leeway=5,
                            options={"require": ["sub", "exp", "iat", "iss", "aud"]})
        if not isinstance(claims["sub"], str) or not claims["sub"]:
            raise ValueError()
        if nonce is not None and (not isinstance(claims.get("nonce"), str)
                                  or not secrets.compare_digest(claims["nonce"], nonce)):
            raise ValueError()
        if isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and claims.get("azp") != client_id:
            raise ValueError()
        return claims
    except jwt.ExpiredSignatureError:
        raise ExpiredIdentityError() from None
    except Exception:
        raise OpenAIError("id_token_validation_failed") from None


def token_record(raw, previous=None):
    previous = previous or {}
    if str(raw.get("token_type", "")).lower() != "bearer" or not isinstance(raw.get("access_token"), str) or not raw["access_token"]:
        raise OpenAIError("invalid_token_response")
    try:
        lifetime = int(raw["expires_in"])
        if lifetime <= 0:
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        raise OpenAIError("invalid_token_expiry") from None
    scopes = raw["scope"].split() if isinstance(raw.get("scope"), str) else previous.get("scopes", [])
    refresh = raw.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        raise OpenAIError("missing_rotated_refresh_token")
    return {**previous, "access_token": raw["access_token"], "refresh_token": refresh,
            "id_token": raw.get("id_token", previous.get("id_token")), "scopes": scopes,
            "token_type": "Bearer", "expires_in": lifetime, "expires_at": time.time() + lifetime,
            "saved_at": time.time(), "earliest_refresh_at": raw.get("earliest_refresh_at")}


class ChatGPTAuth:
    def __init__(self, store=None, http=None, profile=None):
        self.store, self.http, self.profile = store or CredentialStore(), http or OpenAIHTTP(), profile

    def _selected(self, data):
        profile = self.profile or data.get("active")
        if not profile or profile not in data["profiles"]:
            raise OpenAIError("sign_in_required")
        return profile, data["profiles"][profile]

    def status(self):
        with self.store.lock():
            data = self.store.load()
        return {"provider": "chatgpt", "storage": str(self.store.path), "active_profile": data["active"],
                "profiles": [{"profile": key, "email": value.get("email"), "client_id": value["client_id"],
                              "signed_in": bool(value.get("access_token")), "plan_usage_enabled": PERMISSION in value.get("scopes", []),
                              "access_expires_at": value.get("expires_at")}
                             for key, value in data["profiles"].items()]}

    def select(self, profile):
        with self.store.lock():
            data = self.store.load()
            if profile not in data["profiles"]:
                raise OpenAIError("unknown_profile")
            data["active"] = profile
            self.store.save(data)

    def _keys(self):
        discovery = self.http.json(DISCOVERY)
        if discovery.get("issuer") != AUTH or discovery.get("jwks_uri") != AUTH + "/.well-known/jwks.json":
            raise OpenAIError("invalid_discovery_document")
        return self.http.json(discovery["jwks_uri"])

    def login(self, *, new_account=False, timeout=600, open_browser=webbrowser.open):
        try:
            import jwt  # Check optional dependencies before asking the user to authorize.
            import cryptography
        except ImportError:
            raise OpenAIError("install_chatgpt_dependencies") from None
        # Separate lock permits status/model requests during browser interaction.
        with self.store.lock("login", timeout=1):
            with self.store.lock():
                data = self.store.load()
                profile = None if new_account else self.profile or data.get("active")
                if profile and profile not in data["profiles"]:
                    raise OpenAIError("unknown_profile")
                registration = data["profiles"].get(profile, {})
                profile = profile or "account-" + uuid.uuid4().hex[:8]
                self.store.save(data)  # Persist host ID before first authorization.
            captured = {}

            class Callback(BaseHTTPRequestHandler):
                def setup(self):
                    super().setup()
                    self.connection.settimeout(5)

                def log_message(self, *args):
                    pass  # Callback URL contains credentials; never log it.

                def do_GET(self):
                    parsed = urlsplit(self.path)
                    if parsed.path != "/auth/callback" or self.headers.get("Host") != f"127.0.0.1:{server.server_port}":
                        self.send_error(404)
                        return
                    try:
                        captured["form"] = attempt.consume(parsed.query)
                        message = "Authorization received. Return to aiEDA; identity verification is still in progress."
                        code = 200
                    except (OpenAIError, ValueError) as exc:
                        captured["error"] = exc if isinstance(exc, OpenAIError) else OpenAIError("invalid_callback")
                        message, code = "Authorization could not be verified. Return to aiEDA and retry sign-in.", 400
                    self.send_response(code)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.end_headers()
                    self.wfile.write(message.encode("utf-8"))

            with HTTPServer(("127.0.0.1", 0), Callback) as server:
                server.timeout = 0.5
                attempt = LoginAttempt(data["host_id"], f"http://127.0.0.1:{server.server_port}/auth/callback", registration)
                deadline = time.monotonic() + min(timeout, 600)
                print("Continue with ChatGPT: 请在系统浏览器中完成 aiEDA Macro Agent 的登录与授权。", flush=True)
                if not open_browser(attempt.authorization_url):
                    raise OpenAIError("browser_open_failed")
                while not captured and time.monotonic() < deadline:
                    server.handle_request()
            if "error" in captured:
                raise captured["error"]
            if "form" not in captured:
                raise OpenAIError("login_timeout")
            # Retain the issued registration even if exchange fails; never exchange an old code again.
            with self.store.lock():
                current = self.store.load()
                current["profiles"].setdefault(profile, {"client_id": attempt.client_id})
                self.store.save(current)
            raw = self.http.json(AUTH + "/api/accounts/oauth/token", form=captured["form"])
            claims = validate_identity(raw.get("id_token", ""), attempt.client_id, self._keys(), attempt.nonce)
            if registration.get("subject") and claims["sub"] != registration["subject"]:
                raise OpenAIError("account_identity_mismatch")
            record = token_record(raw)
            record.update(client_id=attempt.client_id, issuer=AUTH, subject=claims["sub"], email=claims.get("email"))
            with self.store.lock():
                current = self.store.load()
                current["profiles"][profile] = record
                current["active"] = profile
                self.store.save(current)
        return self.status()

    def access_token(self):
        # Hold OS file lock across refresh + atomic replacement; other processes re-read afterward.
        with self.store.lock(timeout=200):
            data = self.store.load()
            profile, record = self._selected(data)
            require_fresh_identity = False
            if record.get('pending_refresh'):
                try:
                    record = self._complete_refresh(data, profile, record)
                except ExpiredIdentityError:
                    # A deferred JWKS check may outlive the ID token. Renew using
                    # the latest rotated refresh token, NEVER return this pending
                    # access token or accept the expired ID as identity proof.
                    pending = record['pending_refresh']['tokens']
                    trusted = {k:record[k] for k in ('client_id','subject','issuer') if k in record}
                    record = {**pending, **trusted, 'expires_at':0}
                    record.pop('pending_refresh',None)
                    require_fresh_identity = True
            if not record.get("access_token"):
                raise OpenAIError("sign_in_required")
            if PERMISSION not in record.get("scopes", []):
                raise OpenAIError("chatgpt_plan_permission_required")
            if record.get("expires_at", 0) <= time.time() + 60:
                earliest = record.get("earliest_refresh_at")
                if earliest is not None:
                    try:
                        earliest = float(earliest)
                    except (TypeError, ValueError):
                        try:
                            from datetime import datetime
                            earliest = datetime.fromisoformat(str(earliest).replace("Z", "+00:00")).timestamp()
                        except ValueError:
                            raise OpenAIError("invalid_refresh_time") from None
                if earliest and earliest > time.time():
                    if record.get("expires_at", 0) <= time.time():
                        raise OpenAIError("refresh_not_yet_allowed")
                    return record["access_token"]
                if not record.get("refresh_token"):
                    raise OpenAIError("sign_in_required")
                try:
                    raw = self.http.json(AUTH + "/api/accounts/oauth/token", form={"grant_type": "refresh_token",
                        "client_id": record["client_id"], "refresh_token": record["refresh_token"], "resource": API})
                except OpenAIError as exc:
                    if exc.code == "invalid_grant":
                        for key in ("access_token", "refresh_token", "id_token", "scopes", "expires_at", "pending_refresh"):
                            record.pop(key, None)
                        data['profiles'][profile] = record
                        self.store.save(data)
                        raise OpenAIError("sign_in_required") from None
                    raise
                updated = token_record(raw, record)
                # A rotating refresh token must survive a subsequent JWKS network
                # failure. Pending tokens are DPAPI-protected, never used for inference
                # until identity validation succeeds. Next call resumes validation.
                record['pending_refresh']={'tokens':updated,
                    'validate_id_token':bool(raw.get('id_token')) or require_fresh_identity,
                    'fresh_identity_missing':require_fresh_identity and not bool(raw.get('id_token'))}
                data['profiles'][profile] = record
                self.store.save(data)
                record = self._complete_refresh(data, profile, record)
                if PERMISSION not in record.get("scopes", []):
                    raise OpenAIError("chatgpt_plan_permission_required")
            return record["access_token"]

    def _complete_refresh(self, data, profile, record):
        pending=record['pending_refresh'];updated=pending['tokens']
        if pending.get('fresh_identity_missing'):
            raise OpenAIError('sign_in_required')
        if pending['validate_id_token']:
            claims=validate_identity(updated['id_token'],record['client_id'],self._keys())
            if claims['sub']!=record['subject']:
                raise OpenAIError('account_identity_mismatch')
        updated.pop('pending_refresh',None)
        data['profiles'][profile]=updated
        self.store.save(data)
        return updated

    def logout(self):
        confirmed = False
        with self.store.lock(timeout=200):
            data = self.store.load()
            _, record = self._selected(data)
            try:
                revoke_token=record.get('pending_refresh',{}).get('tokens',{}).get('refresh_token') or record.get('refresh_token')
                if revoke_token:
                    discovery = self.http.json(DISCOVERY)
                    endpoint = discovery.get("revocation_endpoint")
                    if endpoint != AUTH + "/api/accounts/oauth/revoke":
                        raise OpenAIError("invalid_discovery_document")
                    with self.http.open(endpoint, form={"token": revoke_token,
                            "token_type_hint": "refresh_token", "client_id": record["client_id"]}):
                        confirmed = True
                else:
                    confirmed = True
            except OpenAIError:
                pass
            for key in ("access_token", "refresh_token", "id_token", "scopes", "expires_at", "earliest_refresh_at", "pending_refresh"):
                record.pop(key, None)
            self.store.save(data)
        return {"signed_out": True, "remote_revocation_confirmed": confirmed,
                "note": None if confirmed else "Remote revocation was not confirmed; disconnect the app in ChatGPT Settings."}
