import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from macro_agent import fifo_service as queue
from macro_agent import remote_service as native


class SharedQueueTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for obj, name, value in [
            (native,'ROOT',root),
            (native,'task',SimpleNamespace(load=lambda p: json.loads(p.read_bytes()),state_id=lambda s:s['state_id'])),
            (native,'snapshot',lambda folder: {'state_id':'frozen'}),
            (queue,'ensure_dispatcher',lambda:None)
        ]:
            p = patch.object(obj,name,value)
            p.start()
            self.addCleanup(p.stop)
        self.requests = []
        for i in range(4):
            tid = 'remote-member-'+str(i)
            folder = native.folder_for(tid)
            folder.mkdir(parents=True)
            (folder/'task.json').write_text('{"state_id":"frozen"}')
            self.requests.append(dict(operation='act',state_id='frozen',task_id=tid,action_id='same-on-each-pc',action='import_netlist'))

    def test_four_members_replay_crash_and_immutable_outputs(self):
        with ThreadPoolExecutor(4) as pool:
            replies = list(pool.map(queue.rpc,self.requests))
        records = {r['job']['task_id']:r['job'] for r in replies}
        self.assertEqual(sorted(j['queue_position'] for j in records.values()), [1,2,3,4])
        self.assertEqual(len({j['job_id'] for j in records.values()}),4)
        self.assertEqual(queue.rpc(self.requests[0])['job'],replies[0]['job'])
        with self.assertRaisesRegex(ValueError,'COLLISION'):
            queue.rpc(dict(self.requests[0],reason='changed'))
        starts = []
        def execute(req):
            tid = req['task_id']
            receipt = queue.native_record(tid,records[tid]['job_id'])
            receipt.parent.mkdir(exist_ok=True)
            with receipt.open('x') as stream:
                json.dump(dict(status='completed'),stream)
            (native.folder_for(tid)/'final.def').write_text(tid)
            starts.append(tid)
            return {'job':records[tid]}
        with patch.object(native,'rpc',side_effect=ValueError('SERVER_BUSY: occupied')):
            with queue.transaction() as db:
                self.assertFalse(queue.advance(db))
        with patch.object(native,'rpc',side_effect=execute):
            with self.assertRaises(InterruptedError):
                with queue.transaction() as db:
                    self.assertTrue(queue.advance(db))
                    raise InterruptedError('simulate crash after native receipt, before DB commit')
            old = native.folder_for(starts[0])/'final.def'
            checksum = hashlib.sha256(old.read_bytes()).digest()
            for _ in range(4):
                with queue.transaction() as db:
                    self.assertTrue(queue.advance(db))
            self.assertEqual(checksum,hashlib.sha256(old.read_bytes()).digest())
        self.assertEqual(starts,sorted(records,key=lambda k:records[k]['queue_position']))
        for tid in records:
            self.assertEqual((native.folder_for(tid)/'final.def').read_text(),tid)

    def test_cancel_never_admitted_and_stale_input_rejected(self):
        a,b = self.requests[:2]
        first,second = queue.rpc(a)['job'], queue.rpc(b)['job']
        cancel = dict(operation='job_cancel',task_id=a['task_id'],job_id=first['job_id'])
        self.assertEqual(queue.rpc(cancel)['job']['status'],'cancelled')
        self.assertEqual(queue.rpc(a)['job']['status'],'cancelled')
        state = queue.rpc(dict(operation='job_status',task_id=b['task_id'],job_id=second['job_id']))
        self.assertEqual(state['job']['queue_position'],1)
        (native.folder_for(b['task_id'])/'task.json').write_text('{"state_id":"changed"}')
        with patch.object(native,'rpc') as launch, queue.transaction() as db:
            self.assertTrue(queue.advance(db))
            self.assertEqual(queue.lookup(db,b['task_id'],second['job_id'])['status'],'failed')
            launch.assert_not_called()
