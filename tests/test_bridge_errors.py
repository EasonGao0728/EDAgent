import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from macro_agent.bridge_errors import error_response
from macro_agent.openai_http import OpenAIError


class BridgeErrorTests(unittest.TestCase):
    def test_permission_reports_stage_and_records_frames_without_exception_text(self):
        with tempfile.TemporaryDirectory() as d:
            try: raise PermissionError(13,'private-value-not-for-log')
            except PermissionError as exc: result=error_response(exc,'quota',Path(d))
            self.assertIn('HOST_PERMISSION_DENIED: quota',result['error'])
            log=(Path(d)/'runs/dsh-host-errors.jsonl').read_text()
            self.assertNotIn('private-value-not-for-log',log)
            self.assertEqual(json.loads(log)['frames'][-1]['function'],self._testMethodName)

    def test_missing_auth_explains_recovery(self):
        with tempfile.TemporaryDirectory() as d, patch.dict('os.environ',{'LOCALAPPDATA':d}):
            result=error_response(OpenAIError('sign_in_required'),'native_model',Path(d))
            self.assertIn('AUTH_REQUIRED',result['error'])
            self.assertIn('凭据文件缺失',result['error'])

    def test_log_write_failure_keeps_original_category(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(Path,'mkdir',side_effect=PermissionError('denied')):
                result=error_response(PermissionError('denied'),'quota',Path(d))
            self.assertIn('HOST_PERMISSION_DENIED',result['error'])
            self.assertIn('诊断日志也无法写入',result['error'])

    def test_network_diagnostics_do_not_log_transport_error_text(self):
        from macro_agent.openai_http import OpenAIHTTP
        from urllib.error import URLError
        client=OpenAIHTTP()
        with tempfile.TemporaryDirectory() as d, patch.object(client.opener,'open',side_effect=URLError('secret-value')):
            try: client.open('https://api.openai.com/v1/models',token='private-token')
            except OpenAIError as exc: result=error_response(exc,'models',Path(d))
            self.assertIn('NETWORK_ERROR',result['error'])
            log=(Path(d)/'runs/dsh-host-errors.jsonl').read_text()
            self.assertNotIn('secret-value',log)
            self.assertNotIn('private-token',log)
            self.assertEqual(json.loads(log)['transport']['host'],'api.openai.com')
