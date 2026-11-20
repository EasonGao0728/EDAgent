"""Repair presentation only; verify and preserve accepted layout/evidence."""
import argparse
from pathlib import Path
import shutil
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from macro_agent.main_task import locked,load,save,verify_refs,file_ref
from macro_agent.task_artifacts import write_report

def refresh(folder):
    folder=Path(folder).resolve()
    with locked(folder):
        state=load(folder/'task.json')
        if state['status']!='target_met' or state.get('pending'):
            raise ValueError('Requires completed idle task')
        d=state['deliverables']
        refs=[state['final_def'],d['preview']['preview'],d['acceptance'],d['metrics'],*state['input_refs']]
        verify_refs([*refs,d['report']])
        old=dict(d['report'])
        backup=folder/('report-before-'+old['sha256'][:12]+'.html')
        if not backup.exists():shutil.copy2(folder/'report.html',backup)
        d['report']=write_report(folder)
        verify_refs(refs)
        state['events'].append({'action':'refresh_report_presentation','timestamp':time.time(),
            'old_report':old,'new_report':d['report'],'previous_report':file_ref(backup),
            'layout_rerun':False,'counts_unchanged':dict(state['counts'])})
        save(folder/'task.json',state)
        return d['report']

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--task',required=True)
    print(refresh(parser.parse_args().task))
