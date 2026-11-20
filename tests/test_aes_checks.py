import tempfile,unittest,copy,json
from unittest.mock import patch
from pathlib import Path
from macro_agent.aes_netlist import parse
from macro_agent.aes_transforms import check
from macro_agent.main_task import dispatch,ROOT

class AESChecks(unittest.TestCase):
    def parsed(self,text):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'x.v';p.write_text(text);return parse(p)
    def test_duplicate_wire_port_and_ordered_alias(self):
        x=self.parsed('module t(a,z); input [1:0] a; wire [1:0] a; output z; wire [1:0] b; cell u(.A(b[0]),.Z(z)); assign b={a[0],a[1]}; endmodule')
        self.assertIn(tuple(sorted([('PIN','a[1]'),('u','A')])),x['partitions'])
        self.assertNotIn(tuple(sorted([('PIN','a[0]'),('u','A')])),x['partitions'])
    def test_unsupported_semantics_rejected(self):
        for tail in ['wire [2:0] a;','assign a={a,a};','cell u(.A(missing));','assign a=1;','output a;']:
            with self.subTest(tail=tail),self.assertRaises(ValueError):self.parsed('module t(a); input a; '+tail+' endmodule')
    def test_buffer_contraction_detects_wrong_sink(self):
        before={'design':'t','units':1000,'die':[0,0,10,10],'pins':{},'components':{'u':{'master':'cell','placement':None}},'nets':{'a':[('PIN','a'),('u','A')],'z':[('u','Z'),('PIN','z')]}}
        after=copy.deepcopy(before);after['components']['b']={'master':'sky130_fd_sc_hd__buf_8','placement':None}
        after['nets']['a']=[('PIN','a'),('b','A')];after['nets']['buffered']=[('b','X'),('u','A')]
        self.assertTrue(check(before,after,'fanout')['passed'])
        after['nets']['buffered']=[('b','X'),('u','Z')]
        self.assertFalse(check(before,after,'fanout')['passed'])
    def test_reject_changed_master_and_unapproved_buffer(self):
        b={'design':'t','units':1000,'die':[0,0,10,10],'pins':{},'components':{'u':{'master':'cell','placement':None}},'nets':{'a':[('u','A')]}}
        a=copy.deepcopy(b);a['components']['u']['master']='different'
        self.assertFalse(check(b,a,'to_drv')['passed'])
    def test_declared_empty_net_is_preserved_but_not_created_or_removed(self):
        b={'design':'t','units':1000,'die':[0,0,10,10],'pins':{},'components':{},'nets':{'unused':[]}}
        self.assertTrue(check(b,copy.deepcopy(b),'fanout')['passed'])
        a=copy.deepcopy(b);a['nets']['new_unused']=[]
        self.assertFalse(check(b,a,'fanout')['passed'])
        a=copy.deepcopy(b);del a['nets']['unused']
        self.assertFalse(check(b,a,'fanout')['passed'])
    def test_buffer_only_floating_component_is_still_rejected(self):
        b={'design':'t','units':1000,'die':[0,0,10,10],'pins':{},'components':{},'nets':{'unused':[]}}
        a=copy.deepcopy(b);a['components']['b']={'master':'sky130_fd_sc_hd__buf_8','placement':None}
        a['nets']['in']=[('b','A')];a['nets']['out']=[('b','X')]
        r=check(b,a,'fanout');self.assertFalse(r['passed']);self.assertIn('floating_added_network',r['errors'])
    def test_unqualified_aes_cannot_start(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'runs') as t:
            with patch('macro_agent.aes_backend.require_qualification',side_effect=ValueError('AES_NOT_QUALIFIED')):
                with self.assertRaisesRegex(ValueError,'AES_NOT_QUALIFIED'):
                    dispatch({'operation':'start','run':str(Path(t)/'task'),'case_id':'aes_sky130_t','goal':'full_backend'})
            self.assertFalse((Path(t)/'task/task.json').exists())
    def test_aes_contract_and_pending_deadline_use_registered_budget(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'runs') as t:
            folder=Path(t)/'task'
            with patch('macro_agent.aes_backend.require_qualification',return_value={}):
                s=dispatch({'operation':'start','run':str(folder),'case_id':'aes_sky130_t','goal':'full_backend'})
            self.assertEqual(s['contract']['budget']['container_seconds'],21600)
            self.assertEqual(s['contract']['case_manifest']['format_id'],'ibench_aes_hd_v1:aes_sky130_t')
            self.assertEqual(s['allowed_actions'][0],'import_netlist')
            self.assertFalse(s['contract']['maker_enabled'])
            self.assertIn('approved_buffer_contraction',s['contract']['required_backend_gates'])
    def test_case_attachment_hash_rejects_cross_case_manifest(self):
        from macro_agent.attachment_inputs import freeze_attachments
        from macro_agent.aes_flow import sha
        a=ROOT/'cases/ibench/aes_legacy/manifest.json'
        with tempfile.TemporaryDirectory() as t,self.assertRaisesRegex(ValueError,'differs from reviewed'):
            freeze_attachments(Path(t),'aes_sky130_t',[{'name':'manifest.json','path':str(a),'sha256':sha(a),'bytes':a.stat().st_size}])
    def test_residual_drc_is_quality_failure_but_skipped_rules_are_execution_failure(self):
        from macro_agent.aes_reproduction import drc_observation
        p=ROOT/'runs/portable-local-cli-20261105/local/result/report/drc_summary.json'
        s=json.loads(p.read_text(encoding='utf-8'));r=drc_observation(s)
        self.assertTrue(r['passed'],r);self.assertFalse(r['quality_clean']);self.assertEqual(r['violation_count'],9)
        s['skipped']=['min_area'];self.assertFalse(drc_observation(s)['passed'])
    def test_route_missing_net_and_timeout_cannot_be_reported_as_reproduction(self):
        from macro_agent.aes_reproduction import routing_observation
        p=next((ROOT/'runs/dsh-desktop-787ddd786e210a82/main-task/attempts').glob('*/result/rt/violation_reporter/route_summary.json'))
        clean=json.loads(p.read_text(encoding='utf-8'));self.assertTrue(routing_observation(clean)['passed'])
        dirty=copy.deepcopy(clean);dirty.update(route_complete=False,reason='residual_drc',route_issue_count_map={'residual_drc':3,'route_incomplete':1});dirty['route']['residual_drc']=3
        self.assertTrue(routing_observation(dirty)['passed']);self.assertFalse(routing_observation(dirty)['quality_assessment']['passed'])
        dirty['route']['unrouted_net_num']=1;self.assertFalse(routing_observation(dirty)['passed'])
        timedout=copy.deepcopy(clean);timedout['stage_ledger'][-1]['timed_out']=True
        self.assertFalse(routing_observation(timedout)['passed'])

if __name__=='__main__':unittest.main()
