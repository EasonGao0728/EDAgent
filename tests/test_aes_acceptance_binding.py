import copy
import json
from pathlib import Path
import tempfile
import unittest
from tools.report_aes_acceptance import evidence_binding,sha


class AcceptanceBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.server=self.root/'server';self.desktop=self.root/'desktop'
        self.server.mkdir();self.desktop.mkdir()
        (self.server/'run.json').write_text('{"status":"passed"}')
        report=self.desktop/'report.html';report.write_text('current report')
        preview=self.desktop/'placement.svg';preview.write_text('<svg>current preview</svg>')
        refs={k:{'path':str(p),'sha256':sha(p)} for k,p in [('report',report),('preview',preview)]}
        self.task={'status':'target_met','deliverables':{'report':refs['report'],'preview':{'preview':refs['preview']}}}
        (self.desktop/'task.json').write_text(json.dumps(self.task))
        task_hash=sha(self.desktop/'task.json')
        self.comparison={'status':'matched','case':'aes','server':str(self.server),'dsh':str(self.desktop),
                         'server_run_sha256':sha(self.server/'run.json'),'dsh_task_sha256':task_hash}
        self.ui={'case':'aes','native_task':str(self.desktop),'report_open_observed':True,
                 'preview_open_observed':True,'dsh_task_sha256':task_hash,'opened_artifacts':refs}

    def check(self):
        return evidence_binding('aes',self.server,self.desktop,self.task,self.comparison,self.ui)

    def test_current_comparison_and_actual_cards_match(self):
        matched,displayed,errors=self.check();self.assertTrue(matched);self.assertTrue(displayed)
        self.assertEqual(errors,{'comparison':[],'ui':[]})

    def test_old_run_cannot_pass_even_with_same_artifacts(self):
        self.comparison['dsh']=str(self.root/'old-task');self.ui['native_task']=str(self.root/'old-task')
        matched,displayed,_=self.check();self.assertFalse(matched);self.assertFalse(displayed)

    def test_changed_task_invalidates_both(self):
        (self.desktop/'task.json').write_text('{"status":"running"}')
        matched,displayed,_=self.check();self.assertFalse(matched);self.assertFalse(displayed)

    def test_changed_report_invalidates_ui_observation(self):
        (self.desktop/'report.html').write_text('replacement report')
        matched,displayed,_=self.check();self.assertTrue(matched);self.assertFalse(displayed)

    def test_flags_without_artifact_identity_are_not_sufficient(self):
        self.ui.pop('opened_artifacts')
        self.assertFalse(self.check()[1])

    def test_changed_server_or_wrong_case_rejects_comparison(self):
        (self.server/'run.json').write_text('{"status":"failed"}')
        self.assertFalse(self.check()[0])
        self.ui['case']='different'
        self.assertFalse(self.check()[1])

    def test_pending_is_not_a_success(self):
        self.ui=None;self.comparison=None
        matched,displayed,_=self.check();self.assertFalse(matched);self.assertFalse(displayed)
