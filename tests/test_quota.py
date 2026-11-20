import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from macro_agent.quota import ROOT, snapshot, ensure_quota, start_server, stop_server

ACCOUNT=json.loads((ROOT/'dsh/quota-policy.json').read_text())['accountId']
def response(used=61):
    return {'accountId':ACCOUNT,'ordinaryUsageAllowed':True,'rateLimitsByLimitId':{'codex':{
        'limitId':'codex','primary':{'usedPercent':99,'windowDurationMins':300},
        'secondary':{'usedPercent':used,'windowDurationMins':10080}}}}

class QuotaTests(unittest.TestCase):
    def setUp(self):
        policy=json.loads((ROOT/'dsh/quota-policy.json').read_text(encoding='utf-8'))
        self.policy={**policy,'stopBelowPercent':20}
        patcher=patch('macro_agent.quota.read_policy',return_value=self.policy)
        patcher.start();self.addCleanup(patcher.stop)

    def test_cancelled_floor_still_checks_service_and_account(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.cache') as d:
            self.policy['stopBelowPercent']=None
            file=Path(d)/'q.json'
            q=ensure_quota(file,reader=lambda:response(99))
            self.assertEqual(q['remainingPercent'],1)
            self.assertIsNone(q['stopBelowPercent'])
            r=response(99);r['ordinaryUsageAllowed']=False
            with self.assertRaisesRegex(ValueError,'QUOTA_STOP'):ensure_quota(file,reader=lambda:r)
            r=response();r['accountId']='other'
            with self.assertRaisesRegex(ValueError,'ACCOUNT_MISMATCH'):ensure_quota(file,reader=lambda:r)
            self.policy['stopBelowPercent']='disabled'
            with self.assertRaisesRegex(ValueError,'QUOTA_POLICY_INVALID'):ensure_quota(file,reader=response)

    def test_direct_route_is_child_scoped_and_only_bypasses_quota_host(self):
        parent={'HTTPS_PROXY':'http://proxy.invalid:7897','NO_PROXY':'localhost'}
        with patch.dict(os.environ,parent,clear=True), \
             patch('macro_agent.quota.codex_candidates',return_value=['current.exe']), \
             patch('macro_agent.quota.subprocess.Popen') as launch:
            start_server(direct=True)
            child=launch.call_args.kwargs['env']
            self.assertEqual(child['NO_PROXY'],'localhost,chatgpt.com')
            self.assertEqual(child['HTTPS_PROXY'],parent['HTTPS_PROXY'])
            self.assertEqual(dict(os.environ),parent)

    def test_live_route_fallback_still_checks_account_and_never_uses_cache(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.cache') as d, \
             patch('macro_agent.quota.time.sleep'), \
             patch('macro_agent.quota.read_limits',side_effect=[ValueError('QUOTA_UNAVAILABLE: transport'),response()]) as read:
            path=Path(d)/'q.json'
            q=ensure_quota(path)
            self.assertEqual(q['remainingPercent'],39)
            calls=[c.kwargs['direct'] for c in read.call_args_list]
            preferred=json.loads((ROOT/'dsh/quota-policy.json').read_text())['preferredRoute']
            self.assertEqual(calls,[preferred=='direct',preferred!='direct'])
            self.assertEqual(q['transportRoute'],'configured' if preferred=='direct' else 'direct')
            wrong=response();wrong['accountId']='another-account'
            read.reset_mock();read.side_effect=[wrong]
            previous=path.read_bytes()
            with self.assertRaisesRegex(ValueError,'QUOTA_ACCOUNT_MISMATCH'):ensure_quota(path)
            self.assertEqual(read.call_count,1)
            self.assertEqual(path.read_bytes(),previous)

    def test_transient_read_retries_but_limit_rejection_does_not(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.cache') as d, patch('macro_agent.quota.time.sleep'):
            reader=Mock(side_effect=[ValueError('QUOTA_UNAVAILABLE: network'),response()])
            self.assertEqual(ensure_quota(Path(d)/'q.json',reader=reader)['remainingPercent'],39)
            self.assertEqual(reader.call_count,2)
            reader=Mock(return_value=response(81))
            with self.assertRaisesRegex(ValueError,'QUOTA_STOP'):
                ensure_quota(Path(d)/'q.json',reader=reader)
            self.assertEqual(reader.call_count,1)

    def test_inaccessible_executable_falls_back_without_querying_model(self):
        proc=Mock()
        with patch('macro_agent.quota.codex_candidates',return_value=['old.exe','current.exe']), \
             patch('macro_agent.quota.subprocess.Popen',side_effect=[PermissionError(13,'denied'),proc]) as launch:
            self.assertIs(start_server(),proc)
            self.assertEqual(launch.call_args.args[0],['current.exe','app-server','--listen','stdio://'])

    def test_all_launches_denied_are_actionable(self):
        with patch('macro_agent.quota.codex_candidates',return_value=['old.exe']), \
             patch('macro_agent.quota.subprocess.Popen',side_effect=PermissionError(13,'denied')):
            with self.assertRaisesRegex(ValueError,'QUOTA_LAUNCH_FAILED') as error:start_server()
            self.assertEqual(error.exception.launch_failures[0]['executable'],'old.exe')

    def test_exit_race_does_not_replace_success_with_permission_error(self):
        proc=Mock();proc.poll.side_effect=[None,0]
        proc.terminate.side_effect=PermissionError(13,'process already exited')
        stop_server(proc)
        proc.kill.assert_not_called()

    def test_weekly_not_short_window(self):
        self.assertEqual(snapshot(response(),ACCOUNT)['remainingPercent'],39)

    def test_missing_invalid_weekly_and_wrong_account(self):
        for used in [None, True, -1, 101, float('nan')]:
            with self.assertRaisesRegex(ValueError,'QUOTA_UNKNOWN'):snapshot(response(used),ACCOUNT)
        r=response();r['rateLimitsByLimitId']['codex']['secondary']=None
        with self.assertRaisesRegex(ValueError,'QUOTA_UNKNOWN'):snapshot(r,ACCOUNT)
        with self.assertRaisesRegex(ValueError,'ACCOUNT_MISMATCH'):snapshot(response(),'other')

    def test_stale_file_refreshes_but_failure_never_uses_old_balance(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.cache') as d:
            path=Path(d)/'quota.json';path.write_text('{"remainingPercent":99,"checkedAt":0}')
            q=ensure_quota(path,reader=response)
            self.assertEqual(q['remainingPercent'],39)
            self.assertGreater(q['checkedAt'],0)
            previous=path.read_bytes()
            def fail():raise ValueError('QUOTA_UNAVAILABLE')
            with self.assertRaisesRegex(ValueError,'QUOTA_UNAVAILABLE'):ensure_quota(path,reader=fail)
            self.assertEqual(path.read_bytes(),previous)

    def test_stop_and_exact_boundary(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.cache') as d:
            path=Path(d)/'quota.json'
            with self.assertRaisesRegex(ValueError,'QUOTA_STOP'):ensure_quota(path,reader=lambda:response(81))
            self.assertEqual(json.loads(path.read_text())['remainingPercent'],19)
            self.assertEqual(ensure_quota(path,reader=lambda:response(80))['remainingPercent'],20)
            r=response();r['ordinaryUsageAllowed']=False
            with self.assertRaisesRegex(ValueError,'QUOTA_STOP'):ensure_quota(path,reader=lambda:r)

if __name__=='__main__':unittest.main()
