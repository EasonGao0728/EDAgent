import unittest
from unittest.mock import Mock, patch

from macro_agent.login_window import requires_login, safe_failure, local_status, check_connection, launch_window
from macro_agent.openai_http import OpenAIError


class LoginWindowTests(unittest.TestCase):
    def test_auth_expiry_permission_and_http_401_require_recovery(self):
        for error in (OpenAIError('sign_in_required'), OpenAIError('invalid_token'),
                      OpenAIError('chatgpt_plan_permission_required'), OpenAIError('http_error', 401)):
            self.assertTrue(requires_login(error))

    def test_network_permission_and_quota_are_not_login_failures(self):
        for error in (OpenAIError('network_error'), PermissionError('private-value'),
                      OpenAIError('subscription_sharing_usage_limit_exceeded'), OpenAIError('http_error', 429)):
            self.assertFalse(requires_login(error))
            self.assertNotIn('private-value', safe_failure(error))
        self.assertIn('没有清除', safe_failure(OpenAIError('network_error')))

    def test_saved_credential_is_not_misreported_as_live_verified(self):
        auth = Mock()
        auth.status.return_value = {'active_profile': 'one', 'profiles': [
            {'profile': 'one', 'signed_in': True, 'plan_usage_enabled': True}]}
        self.assertIn('尚未进行联网检查', local_status(auth))
        auth.status.return_value['active_profile'] = None
        self.assertIn('尚未登录', local_status(auth))

    def test_connection_checks_catalog_not_inference(self):
        auth = Mock()
        with patch('macro_agent.chatgpt_provider.ChatGPTProvider') as provider:
            provider.return_value.models.return_value = [{'slug': 'test'}]
            self.assertIn('不等于推理与额度检查已通过', check_connection(auth))
            provider.return_value.generate.assert_not_called()

    def test_launch_has_no_credential_arguments_or_visible_console(self):
        with patch('macro_agent.login_window.subprocess.Popen') as popen:
            self.assertTrue(launch_window()['requested'])
            args, kwargs = popen.call_args
            self.assertEqual(args[0][-2:], ['-m', 'macro_agent.login_window'])
            self.assertIn('pythonw.exe', args[0][0])
            self.assertFalse(kwargs.get('shell', False))

