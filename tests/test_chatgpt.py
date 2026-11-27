"""Offline OAuth/protocol tests. Signed fixture tokens never contact OpenAI."""
import base64
from contextlib import contextmanager
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

from macro_agent.chatgpt_auth import (ChatGPTAuth, CredentialStore, LoginAttempt, PERMISSION,
                                      token_record, validate_identity)
from macro_agent.chatgpt_provider import ChatGPTProvider, completed_response, portable_schema
from macro_agent.openai_http import API, AUTH, OpenAIError, OpenAIHTTP
from macro_agent.perception import QUERY_SCHEMA, PLAN_SCHEMA
from macro_agent.synthesis import CODE_SCHEMA

try:
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    jwt = None


class MemoryStore:
    path = Path("offline-test.dpapi")

    def __init__(self, data=None):
        self.data = copy.deepcopy(data or {"version": 1, "host_id": "urn:uuid:test-host", "active": None, "profiles": {}})

    @contextmanager
    def lock(self, *args, **kwargs):
        yield

    def load(self):
        return copy.deepcopy(self.data)

    def save(self, value):
        self.data = copy.deepcopy(value)


class SSE(io.BytesIO):
    headers = {"Content-Type": "text/event-stream; charset=utf-8"}


def sse(*events):
    return SSE("".join("data: " + json.dumps(event) + "\n\n" for event in events).encode())


def completed(value, **extra):
    return {"type": "response.completed", "response": {"status": "completed", "model": "account-visible-model",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(value)}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}, **extra}}


class AttemptTests(unittest.TestCase):
    def test_pkce_and_registration_contract(self):
        attempt = LoginAttempt("host-123", "http://127.0.0.1:15000/auth/callback")
        params = parse_qs(urlsplit(attempt.authorization_url).query)
        self.assertEqual(params["client_id"], ["dynamic_agent_client"])
        self.assertEqual(params["resource"], [API])
        expected = base64.urlsafe_b64encode(hashlib.sha256(attempt.verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(params["code_challenge"], [expected])
        self.assertNotEqual(attempt.nonce, attempt.state)
        form = attempt.consume(urlencode({"code": "offline-code", "client_id": "oaiapp_fixture", "state": attempt.state}))
        self.assertEqual(form["client_id"], "oaiapp_fixture")
        self.assertEqual(form["redirect_uri"], params["redirect_uri"][0])
        with self.assertRaisesRegex(OpenAIError, "reused"):
            attempt.consume("")

    def test_missing_mismatched_duplicate_expired_or_denied_callback(self):
        callbacks = [lambda a: "code=x&client_id=oaiapp_x&state=wrong",
                     lambda a: urlencode({"code": "x", "state": a.state}),
                     lambda a: urlencode({"code": "x", "client_id": "dynamic_agent_client", "state": a.state}),
                     lambda a: urlencode({"error": "access_denied", "state": a.state}),
                     lambda a: urlencode({"code": "x", "client_id": "oaiapp_x", "state": a.state}) + "&code=y"]
        for callback in callbacks:
            a = LoginAttempt("host", "http://127.0.0.1:1/auth/callback")
            with self.subTest(callback=callback), self.assertRaises(OpenAIError):
                a.consume(callback(a))
        a = LoginAttempt("host", "http://127.0.0.1:1/auth/callback")
        a.expires = 0
        with self.assertRaisesRegex(OpenAIError, "expired"):
            a.consume("")

    def test_returning_registration_and_account_separation(self):
        registration = {"client_id": "oaiapp_original", "id_token": "fixture-id", "email": "fixture@example.com"}
        a = LoginAttempt("host", "http://127.0.0.1:2/auth/callback", registration)
        params = parse_qs(urlsplit(a.authorization_url).query)
        self.assertNotIn("agent_name_hint", params)
        self.assertEqual(params["id_token_hint"], ["fixture-id"])
        self.assertEqual(a.consume(urlencode({"code": "x", "state": a.state}))["client_id"], "oaiapp_original")
        a = LoginAttempt("host", "http://127.0.0.1:2/auth/callback", registration)
        with self.assertRaisesRegex(OpenAIError, "client_id_mismatch"):
            a.consume(urlencode({"code": "x", "state": a.state, "client_id": "oaiapp_other"}))


@unittest.skipUnless(jwt, "install optional chatgpt dependencies for signature tests")
class IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        cls.public.update(kid="fixture-key", use="sig", alg="RS256")
        cls.jwks = {"keys": [cls.public]}

    def signed(self, **changes):
        return jwt.encode({"iss": AUTH, "sub": "fixture-subject", "aud": "oaiapp_fixture",
                           "iat": int(time.time()), "exp": int(time.time()) + 300, "nonce": "original-nonce", **changes},
                          self.key, algorithm="RS256", headers={"kid": "fixture-key"})

    def test_signed_identity_and_nonce(self):
        result = validate_identity(self.signed(), "oaiapp_fixture", self.jwks, "original-nonce")
        self.assertEqual(result["sub"], "fixture-subject")

    def expired_pending_store(self):
        record={'client_id':'oaiapp_fixture','subject':'fixture-subject','issuer':AUTH,
                'access_token':'previous-access','refresh_token':'previous-refresh',
                'expires_at':1,'scopes':[PERMISSION]}
        pending={**record,'access_token':'expired-pending-access','refresh_token':'rotated-refresh',
                 'id_token':self.signed(iat=int(time.time())-600,exp=int(time.time())-300)}
        record['pending_refresh']={'tokens':pending,'validate_id_token':True}
        return MemoryStore({'version':1,'host_id':'host','active':'a','profiles':{'a':record}})

    def test_expired_pending_identity_renews_latest_rotation_then_validates_new_identity(self):
        store=self.expired_pending_store();forms=[];fresh=self.signed()
        class HTTP:
            def json(self,url,**kwargs):
                forms.append(kwargs['form'])
                return {'access_token':'fresh-access','refresh_token':'fresh-refresh','id_token':fresh,
                        'expires_in':3600,'token_type':'Bearer'}
        with patch.object(ChatGPTAuth,'_keys',return_value=self.jwks):
            self.assertEqual(ChatGPTAuth(store,HTTP()).access_token(),'fresh-access')
            self.assertEqual(ChatGPTAuth(store,HTTP()).access_token(),'fresh-access')
        self.assertEqual(len(forms),1)
        self.assertEqual(forms[0]['refresh_token'],'rotated-refresh')
        self.assertEqual(forms[0]['client_id'],'oaiapp_fixture')
        self.assertNotIn('pending_refresh',store.data['profiles']['a'])
        self.assertEqual(store.data['profiles']['a']['refresh_token'],'fresh-refresh')

    def test_expired_pending_recovery_never_accepts_missing_or_wrong_new_identity(self):
        for identity in (None,self.signed(sub='another-subject'),self.signed(aud='other-client'),
                         self.signed(exp=int(time.time())-30)):
            with self.subTest(identity_kind='missing' if identity is None else 'invalid'):
                store=self.expired_pending_store();calls=[]
                class HTTP:
                    def json(self,url,**kwargs):
                        calls.append(url)
                        return {'access_token':'must-not-use','refresh_token':'latest-refresh',
                                'id_token':identity,'expires_in':3600,'token_type':'Bearer'}
                with patch.object(ChatGPTAuth,'_keys',return_value=self.jwks),self.assertRaises(OpenAIError):
                    ChatGPTAuth(store,HTTP()).access_token()
                self.assertEqual(len(calls),1)
                saved=store.data['profiles']['a']
                self.assertNotEqual(saved['access_token'],'must-not-use')
                self.assertEqual(saved['pending_refresh']['tokens']['refresh_token'],'latest-refresh')

    def test_expired_pending_network_failure_keeps_rotation_invalid_grant_requires_login(self):
        store=self.expired_pending_store();forms=[]
        class HTTP:
            def __init__(self,code):self.code=code
            def json(self,url,**kwargs):
                forms.append(kwargs['form']);raise OpenAIError(self.code)
        with patch.object(ChatGPTAuth,'_keys',return_value=self.jwks):
            with self.assertRaisesRegex(OpenAIError,'network_error'):
                ChatGPTAuth(store,HTTP('network_error')).access_token()
            self.assertEqual(store.data['profiles']['a']['pending_refresh']['tokens']['refresh_token'],'rotated-refresh')
            with self.assertRaisesRegex(OpenAIError,'sign_in_required'):
                ChatGPTAuth(store,HTTP('invalid_grant')).access_token()
        self.assertTrue(all(f['refresh_token']=='rotated-refresh' for f in forms))
        self.assertNotIn('pending_refresh',store.data['profiles']['a'])
        self.assertNotIn('refresh_token',store.data['profiles']['a'])

    def test_reject_untrusted_identity(self):
        for changes in ({"iss": "https://example.com"}, {"aud": "oaiapp_other"}, {"exp": 1},
                        {"nonce": "wrong-nonce"}, {"sub": ""}, {"iat": int(time.time()) + 300},
                        {"aud": ["oaiapp_fixture", "oaiapp_other"], "azp": "oaiapp_other"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(OpenAIError, "validation_failed"):
                validate_identity(self.signed(**changes), "oaiapp_fixture", self.jwks, "original-nonce")
        wrong = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode({"iss": AUTH, "sub": "x", "aud": "oaiapp_fixture", "iat": time.time(), "exp": time.time() + 300},
                            wrong, algorithm="RS256", headers={"kid": "fixture-key"})
        with self.assertRaises(OpenAIError):
            validate_identity(forged, "oaiapp_fixture", self.jwks)
        unsigned = jwt.encode({"sub": "x"}, key="", algorithm="none")
        with self.assertRaises(OpenAIError):
            validate_identity(unsigned, "oaiapp_fixture", self.jwks)

    def test_real_loopback_callback_exchange_and_restart_registration(self):
        store, browser_parameters, requests, errors = MemoryStore(), {}, [], []
        test = self

        class HTTP:
            def json(self, url, **kwargs):
                requests.append((url, kwargs))
                if url.endswith("openid-configuration"):
                    return {"issuer": AUTH, "jwks_uri": AUTH + "/.well-known/jwks.json"}
                if url.endswith("jwks.json"):
                    return test.jwks
                return {"access_token": "fixture-access", "refresh_token": "fixture-refresh", "expires_in": 3600,
                        "token_type": "Bearer", "scope": "openid offline_access " + PERMISSION,
                        "id_token": test.signed(nonce=browser_parameters["nonce"][0])}

        def browser(url):
            browser_parameters.update(parse_qs(urlsplit(url).query))

            def callback():
                try:
                    target = browser_parameters["redirect_uri"][0] + "?" + urlencode({
                        "state": browser_parameters["state"][0], "code": "fixture-code", "client_id": "oaiapp_fixture"})
                    with urlopen(target, timeout=3) as response:
                        self.assertNotIn(b"fixture-code", response.read())
                except Exception as exc:
                    errors.append(exc)
            thread = threading.Thread(target=callback, daemon=True)
            thread.start()
            return True

        client = ChatGPTAuth(store, HTTP())
        status = client.login(timeout=5, open_browser=browser)
        self.assertFalse(errors)
        self.assertEqual(len(status["profiles"]), 1)
        self.assertTrue(status["profiles"][0]["plan_usage_enabled"])
        self.assertNotIn("fixture-access", json.dumps(status))
        self.assertNotIn("fixture-refresh", json.dumps(status))
        form = next(kwargs["form"] for url, kwargs in requests if url.endswith("/token"))
        self.assertEqual(form["client_id"], "oaiapp_fixture")
        self.assertEqual(form["redirect_uri"], browser_parameters["redirect_uri"][0])
        self.assertEqual(ChatGPTAuth(store, HTTP()).access_token(), "fixture-access")


class SessionTests(unittest.TestCase):
    def record(self):
        return {"client_id": "oaiapp_fixture", "subject": "fixture-subject", "access_token": "old-access",
                "refresh_token": "old-refresh", "id_token": "retained-identity", "scopes": [PERMISSION], "expires_at": 1}

    def store(self):
        return MemoryStore({"version": 1, "host_id": "host", "active": "a", "profiles": {"a": self.record()}})

    def test_refresh_rotation_survives_restart_and_is_not_repeated(self):
        store, calls = self.store(), []

        class HTTP:
            def json(self, url, **kwargs):
                calls.append(kwargs["form"])
                return {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600, "token_type": "Bearer"}

        self.assertEqual(ChatGPTAuth(store, HTTP()).access_token(), "new-access")
        self.assertEqual(ChatGPTAuth(store, HTTP()).access_token(), "new-access")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["refresh_token"], "old-refresh")
        self.assertNotIn("scope", calls[0])
        self.assertEqual(store.data["profiles"]["a"]["refresh_token"], "new-refresh")

    def test_jwks_failure_preserves_rotation_and_resumes_validation_without_refresh(self):
        from unittest.mock import patch
        store=self.store();calls=[]
        class HTTP:
            def json(self,url,**kwargs):
                calls.append(url)
                return {'access_token':'new-access','refresh_token':'new-refresh','id_token':'new-id',
                        'expires_in':3600,'token_type':'Bearer'}
        with patch.object(ChatGPTAuth,'_keys',side_effect=OpenAIError('network_error')):
            with self.assertRaisesRegex(OpenAIError,'network_error'):
                ChatGPTAuth(store,HTTP()).access_token()
        self.assertEqual(store.data['profiles']['a']['pending_refresh']['tokens']['refresh_token'],'new-refresh')
        self.assertEqual(store.data['profiles']['a']['access_token'],'old-access')
        with patch.object(ChatGPTAuth,'_keys',return_value={}),patch('macro_agent.chatgpt_auth.validate_identity',return_value={'sub':'fixture-subject'}):
            self.assertEqual(ChatGPTAuth(store,HTTP()).access_token(),'new-access')
        self.assertEqual(len(calls),1)
        self.assertNotIn('pending_refresh',store.data['profiles']['a'])

    def test_transient_failure_keeps_credentials_invalid_grant_clears_tokens(self):
        store = self.store()
        class HTTP:
            def json(self, *args, **kwargs):
                raise OpenAIError("network_error")
        with self.assertRaisesRegex(OpenAIError, "network_error"):
            ChatGPTAuth(store, HTTP()).access_token()
        self.assertEqual(store.data["profiles"]["a"]["refresh_token"], "old-refresh")
        class Invalid:
            def json(self, *args, **kwargs):
                raise OpenAIError("invalid_grant")
        with self.assertRaisesRegex(OpenAIError, "sign_in_required"):
            ChatGPTAuth(store, Invalid()).access_token()
        self.assertNotIn("refresh_token", store.data["profiles"]["a"])
        self.assertEqual(store.data["profiles"]["a"]["client_id"], "oaiapp_fixture")

    def test_permission_and_earliest_refresh_gate(self):
        store = self.store()
        store.data["profiles"]["a"]["scopes"] = ["openid"]
        with self.assertRaisesRegex(OpenAIError, "permission_required"):
            ChatGPTAuth(store, object()).access_token()
        store = self.store()
        store.data["profiles"]["a"]["earliest_refresh_at"] = time.time() + 100
        with self.assertRaisesRegex(OpenAIError, "refresh_not_yet_allowed"):
            ChatGPTAuth(store, object()).access_token()
        store.data["profiles"]["a"]["expires_at"] = time.time() + 10
        self.assertEqual(ChatGPTAuth(store, object()).access_token(), "old-access")

    def test_rotated_refresh_required(self):
        with self.assertRaisesRegex(OpenAIError, "missing_rotated"):
            token_record({"access_token": "a", "token_type": "Bearer", "expires_in": 3600})

    def test_profile_switch_and_local_logout_when_remote_unavailable(self):
        store = self.store()
        store.data["profiles"]["b"] = {**self.record(), "client_id": "oaiapp_other"}
        client = ChatGPTAuth(store, object())
        client.select("b")
        self.assertEqual(client.status()["active_profile"], "b")
        class HTTP:
            def json(self, *args, **kwargs):
                raise OpenAIError("network_error")
        result = ChatGPTAuth(store, HTTP()).logout()
        self.assertFalse(result["remote_revocation_confirmed"])
        self.assertNotIn("access_token", store.data["profiles"]["b"])
        self.assertEqual(store.data["profiles"]["a"]["access_token"], "old-access")

    def test_logout_revokes_pending_rotated_token_and_clears_it(self):
        store=self.store();store.data['profiles']['a']['pending_refresh']={'tokens':{'refresh_token':'rotated-fixture'}}
        forms=[]
        class HTTP:
            def json(self,*args,**kwargs):return {'revocation_endpoint':AUTH+'/api/accounts/oauth/revoke'}
            @contextmanager
            def open(self,*args,**kwargs):
                forms.append(kwargs['form']);yield None
        result=ChatGPTAuth(store,HTTP()).logout()
        self.assertTrue(result['remote_revocation_confirmed'])
        self.assertEqual(forms[0]['token'],'rotated-fixture')
        self.assertNotIn('pending_refresh',store.data['profiles']['a'])


class ProtocolTests(unittest.TestCase):
    def test_retry_is_confined_to_pre_request_tls_handshake(self):
        import ssl
        from http.client import HTTPSConnection
        from macro_agent.openai_http import HandshakeConnection
        conn=HandshakeConnection("api.openai.com")
        with patch.object(HTTPSConnection,"connect",side_effect=[ssl.SSLEOFError(),None]) as connect, patch("macro_agent.openai_http.time.sleep"):
            conn.connect()
            self.assertEqual(connect.call_count,2)
        with patch.object(HTTPSConnection,"connect",side_effect=ssl.SSLEOFError()) as connect, patch("macro_agent.openai_http.time.sleep"):
            with self.assertRaises(ssl.SSLEOFError):conn.connect()
            self.assertEqual(connect.call_count,3)
        with patch.object(HTTPSConnection,"connect",side_effect=ssl.SSLCertVerificationError()) as connect:
            with self.assertRaises(ssl.SSLCertVerificationError):conn.connect()
            self.assertEqual(connect.call_count,1)

    def test_failed_stream_records_structured_fields_only(self):
        stream = sse({"type":"response.failed","response":{"error":{
            "code":"upstream_disconnected","message":"private request text"}}})
        stream.headers={"x-request-id":"req_a12345678"}
        with self.assertRaises(OpenAIError) as failed:
            completed_response(stream)
        self.assertEqual(failed.exception.code,"remote_error")
        self.assertEqual(failed.exception.stream_event,{"event":"response.failed",
                         "code":"upstream_disconnected","request_id":"req_a12345678"})

    def test_delta_is_not_success_and_late_quota_error_is_failure(self):
        delta = {"type": "response.output_text.delta", "delta": '{"ok":true}'}
        for stream in (sse(delta), sse(delta, {"type": "response.failed", "response": {"error": {
                       "code": "subscription_sharing_usage_limit_exceeded", "message": "fixture-secret"}}}),
                       sse({"type": "response.incomplete", "response": {}})):
            with self.subTest(stream=stream), self.assertRaises(OpenAIError) as error:
                completed_response(stream)
            self.assertNotIn("fixture-secret", str(error.exception))

    def test_success_and_bounded_stream_and_refusal(self):
        self.assertEqual(completed_response(sse(completed({"ok": True})))["status"], "completed")
        with self.assertRaisesRegex(OpenAIError, "too_large"):
            completed_response(sse(completed({"ok": True})), max_bytes=2)
        provider = ChatGPTProvider("fixture-model", auth=type("Auth", (), {"access_token": lambda s: "fixture-token"})())
        class HTTP:
            def open(self, *args, **kwargs):
                return sse(completed({}, output=[{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]))
        provider.http = HTTP()
        with self.assertRaisesRegex(OpenAIError, "model_refusal"):
            provider.generate("instructions", {}, QUERY_SCHEMA, 1)

    def test_account_catalog_and_subscription_request_contract(self):
        calls = []
        class HTTP:
            def json(self, url, **kwargs):
                return {"models": [{"slug": "hidden", "visibility": "hide"},
                                   {"slug": "account-visible-model", "display_name": "First", "visibility": "list"},
                                   {"slug": "second", "visibility": "list"}]}
            def open(self, url, **kwargs):
                calls.append((url, kwargs))
                return sse(completed({"ok": True}))
        auth = type("Auth", (), {"access_token": lambda s: "fixture-bearer"})()
        provider = ChatGPTProvider(auth=auth, http=HTTP())
        self.assertEqual(provider.resolve_model(), "account-visible-model")
        value, usage = provider.generate("system-instructions", {"design": "fixture"}, QUERY_SCHEMA, 55)
        self.assertEqual(value, {"ok": True})
        url, kwargs = calls[0]
        self.assertEqual(url, API + "/responses")
        body = kwargs["body"]
        self.assertIs(body["store"], False)
        self.assertIs(body["stream"], True)
        self.assertEqual(body["input"][0]["role"], "user")
        self.assertEqual(body["instructions"], "system-instructions")
        for key in ("temperature", "seed", "max_output_tokens", "previous_response_id", "metadata", "tools"):
            self.assertNotIn(key, body)
        self.assertNotIn("fixture-bearer", json.dumps((body, usage)))
        self.assertEqual(usage["total_tokens"], 15)
        provider.model = "unavailable"
        with self.assertRaisesRegex(OpenAIError, "not_available"):
            provider.resolve_model()

    def test_schema_keeps_shapes_and_enums_without_mutating_original(self):
        originals = copy.deepcopy([QUERY_SCHEMA, PLAN_SCHEMA, CODE_SCHEMA])
        for source in originals:
            converted = portable_schema(source)
            self.assertEqual(set(converted["required"]), set(converted["properties"]))
            self.assertFalse(converted["additionalProperties"])
        self.assertEqual(QUERY_SCHEMA, originals[0])
        self.assertEqual(portable_schema(QUERY_SCHEMA)["properties"]["tool"]["enum"], QUERY_SCHEMA["properties"]["tool"]["enum"])
        self.assertNotIn("pattern", portable_schema(CODE_SCHEMA)["properties"]["source"])

    def test_missing_content_type_still_requires_valid_completed_sse(self):
        class HTTP:
            def open(self, *args, **kwargs):
                stream = sse(completed({"ok": True}))
                stream.headers = {}
                return stream
        provider = ChatGPTProvider("fixture", http=HTTP(),
            auth=type("Auth", (), {"access_token": lambda s: "fixture-token"})())
        self.assertEqual(provider.generate("test", {}, QUERY_SCHEMA, 0)[0], {"ok": True})

    def test_terminal_output_omitted_rebuilds_completed_parts_in_index_order(self):
        events = [{"type": "response.output_text.done", "output_index": 0, "content_index": 0, "text": '{"ok":true}'},
                  {"type": "response.output_item.done", "output_index": 0, "item": {"type": "message", "content": []}},
                  completed({}, output=[])]
        result = completed_response(sse(*events))
        self.assertEqual(result["output"][0]["content"][0]["text"], '{"ok":true}')
        with self.assertRaisesRegex(OpenAIError, "without_completion"):
            completed_response(sse(*events[:-1]))

    def test_done_text_followed_by_failure_cannot_be_used_as_success(self):
        with self.assertRaisesRegex(OpenAIError, "usage_limit_exceeded"):
            completed_response(sse({"type": "response.output_text.done", "output_index": 0, "content_index": 0,
                                    "text": '{"ok":true}'}, {"type": "response.failed", "response": {"error": {
                                    "code": "subscription_sharing_usage_limit_exceeded"}}}))

    def test_https_only_and_no_raw_error_or_credential_in_exception(self):
        client = OpenAIHTTP()
        for url in ("http://api.openai.com/v1/models", "https://example.com", "https://api.openai.com.evil.test"):
            with self.assertRaisesRegex(OpenAIError, "untrusted_endpoint"):
                client.open(url, token="fixture-bearer")
        error = HTTPError(API + "/responses", 401, "fixture-secret", {}, io.BytesIO(
            b'{"error":{"code":"fixture_secret","message":"fixture-bearer"}}'))
        with patch.object(client.opener, "open", side_effect=error):
            with self.assertRaises(OpenAIError) as result:
                client.open(API + "/responses", token="fixture-bearer")
        self.assertNotIn("fixture", str(result.exception))


@unittest.skipUnless(os.name == "nt", "Windows DPAPI and file lock test")
class WindowsCredentialTests(unittest.TestCase):
    def test_dpapi_round_trip_atomic_replacement_and_cross_instance_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = CredentialStore(Path(temporary) / "private")
            with store.lock():
                data = store.load()
                data["fixture_secret"] = "never-plaintext-credential"
                store.save(data)
                with self.assertRaisesRegex(OpenAIError, "auth_busy"):
                    with store.lock(timeout=0.01):
                        pass
            self.assertNotIn(b"never-plaintext-credential", store.path.read_bytes())
            other = CredentialStore(Path(temporary) / "private")
            with other.lock():
                self.assertEqual(other.load(), data)
                other.save({**data, "active": "next"})
            self.assertEqual(store.load()["active"], "next")
            self.assertEqual(list(store.directory.glob("*.tmp")), [])
