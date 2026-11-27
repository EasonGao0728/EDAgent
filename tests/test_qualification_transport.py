import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from macro_agent import remote_client as client


class QualificationTransportTests(unittest.TestCase):
    def test_private_profile_accepts_operator_alias_and_rejects_invalid_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / 'worker.json'
            fields = dict(enabled=True, local_fallback=False, ssh_host='team-worker',
                          server_root='/srv/team/main-agent-remote-v1', server_uid=1001)
            with patch.object(client, 'CONFIG', profile):
                profile.write_text(json.dumps(fields), encoding='utf-8-sig')
                self.assertEqual(client.config(), fields)
                for change in [dict(enabled=False), dict(local_fallback=True), dict(server_uid=0),
                               dict(ssh_host='-invalid'), dict(server_root='/srv/../main-agent-remote-v1')]:
                    with self.subTest(change=change), self.assertRaises(ValueError):
                        profile.write_text(json.dumps(fields | change), encoding='utf-8')
                        client.config()

    def test_existing_delivery_matches_size_and_hash_without_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            payload = b'verified artifact'
            (folder/'final.def').write_bytes(payload)
            files = {'final.def': dict(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())}
            args = (folder, {'final.def': 'final_def'}, files, {'ssh_host': 'team-worker'}, '/example/', False)
            with patch.object(client.subprocess, 'run') as transfer:
                self.assertEqual(client.verified_qualification_files(*args)[0]['bytes'], len(payload))
                files['final.def']['bytes'] += 1
                with self.assertRaises(ValueError):
                    client.verified_qualification_files(*args)
                transfer.assert_not_called()
