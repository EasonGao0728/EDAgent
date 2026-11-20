"""Continue a verified DSH placement with the same pinned local iEDA image."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from macro_agent import ieda_runtime as rt
from macro_agent.def_validation import read_def


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def execute(work, stage, timeout=300):
    name = 'dsh-cont-' + uuid.uuid4().hex[:12]
    args = ['run', '--rm', '--pull=never', '--name', name, '--network', 'none',
            '--cpus', '4', '--memory', '8g', '--pids-limit', '256',
            '--mount', f'type=bind,source={work},target=/work', '--workdir', '/work',
            '--env', 'OMP_NUM_THREADS=4', '--env', 'RESULT_DIR=/work/result',
            '--env', 'CONFIG_DIR=/work/config', rt.IMAGE,
            '/usr/bin/timeout', '--kill-after=5', str(timeout), 'iEDA', '-script', '/work/' + stage + '.tcl']
    start = time.monotonic()
    with (work/'logs'/f'{stage}.log').open('w', encoding='utf-8') as stream:
        try:
            p = subprocess.run(rt.docker()+args, stdout=stream, stderr=subprocess.STDOUT,
                               timeout=timeout+20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            code = p.returncode
        except subprocess.TimeoutExpired:
            rt.invoke(['kill', name]); code = 124
    log = (work/'logs'/f'{stage}.log').read_text(encoding='utf-8', errors='replace')
    return {'stage': stage, 'exit_code': code, 'seconds': round(time.monotonic()-start, 2),
            'completed': code == 0 and 'CONTINUATION_OK '+stage in log}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    task = Path(args.task).resolve(); work = Path(args.output).resolve()
    state = json.loads((task/'task.json').read_text(encoding='utf-8'))
    if state['status'] != 'target_met': raise ValueError('Source placement not accepted')
    for ref in state['input_refs']:
        if sha(Path(ref['path'])) != ref['sha256']: raise ValueError('Input changed: '+ref['path'])
    ref = state['final_def']; source = Path(ref['path'])
    if sha(source) != ref['sha256']: raise ValueError('Accepted DEF hash mismatch')
    root = Path(state['contract']['input_root']); m = state['contract']['case_manifest']
    work.mkdir(parents=True, exist_ok=False)
    for folder in ['inputs', 'config', 'logs', 'result/report', 'result/cts', 'result/pl', 'result/rt', 'result/drc', 'result/sta']:
        (work/folder).mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, work/'inputs/placement.def')
    deps = [m['tech_lef'], *m['cell_lefs'], *m['libs'], m['sdc']]
    for f in deps:
        dest = work/'inputs'/f; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(root/f, dest)
    shutil.copytree(root/'config', work/'config', dirs_exist_ok=True)
    save(work/'provenance.json', {'source_task': str(task), 'source_def': ref, 'case': m['case_id'],
         'image': rt.IMAGE, 'inputs': [{'path': f, 'sha256': sha(work/'inputs'/f)} for f in deps],
         'placement_rerun': False, 'source_read_only': True})
    pre = '\n'.join(['flow_init -config /work/config/flow_config.json',
          'db_init -config /work/config/db_default_config.json',
          'tech_lef_init -path /work/inputs/'+m['tech_lef'],
          'lef_init -path [list '+' '.join('/work/inputs/'+f for f in m['cell_lefs'])+']',
          'db_init -lib_path [list '+' '.join('/work/inputs/'+f for f in m['libs'])+']',
          'db_init -sdc_path /work/inputs/'+m['sdc']])+'\n'
    scripts = {
      'import_check': ('/work/inputs/placement.def', ''),
      'cts': ('/work/result/import_check.def', 'run_cts -config /work/config/cts_default_config.json -work_dir /work/result/cts\ncts_report -path /work/result/cts'),
      'legalization': ('/work/result/cts.def', 'run_incremental_flow -config /work/config/pl_default_config.json'),
      'routing': ('/work/result/legalization.def', 'init_rt -temp_directory_path /work/result/rt -bottom_routing_layer met1 -top_routing_layer met5 -thread_number 4\nrun_rt\ndestroy_rt'),
      'filler': ('/work/result/routing.def', 'run_filler -config /work/config/pl_default_config.json'),
      'drc': ('/work/result/filler.def', 'run_drc -config /work/config/drc_default_config.json -path /work/result/report/drc.rpt\nsave_drc -path /work/result/drc/detail.drc'),
      'gds': ('/work/result/filler.def', 'gds_save -path /work/result/final.gds2'),
    }
    for stage, (inp, commands) in scripts.items():
        body = pre+'def_init -path '+inp+'\n'+commands+'\n'
        if stage not in ['drc', 'gds']:
            body += f'def_save -path /work/result/{stage}.def\nnetlist_save -path /work/result/{stage}.v -exclude_cell_names {{}}\nreport_db -path /work/result/report/{stage}.rpt\n'
        (work/f'{stage}.tcl').write_text('if {[catch {\n'+body+f'puts "CONTINUATION_OK {stage}"\n'+
            '} message]} {puts stderr $message; exit 1}\nflow_exit\n', encoding='utf-8')
    records = []
    for stage in scripts:
        print('RUN '+stage, flush=True)
        record = execute(work, stage)
        if record['completed'] and stage == 'import_check':
            record['readback_equal'] = read_def(source) == read_def(work/'result/import_check.def')
            record['completed'] = record['readback_equal']
        if record['completed'] and stage not in ['drc', 'gds']:
            design = read_def(work/'result'/f'{stage}.def')
            record.update(instances=len(design['components']), nets=len(design['nets']))
        records.append(record)
        save(work/'run.json', {'source_task': str(task), 'stages': records, 'status': 'running'})
        print(json.dumps(record), flush=True)
        if not record['completed'] and stage not in ['drc','gds']: break
    status = 'completed' if len(records)==len(scripts) and all(r['completed'] for r in records) else 'incomplete'
    save(work/'run.json', {'source_task': str(task), 'stages': records, 'status': status})
    print('OUTPUT='+str(work), flush=True)
    return 0 if status=='completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
