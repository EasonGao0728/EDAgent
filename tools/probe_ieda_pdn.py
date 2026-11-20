"""Fresh, bounded PDN commissioning run. Never changes registered inputs/tasks."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from macro_agent import routed_stages, ieda_runtime as rt
from macro_agent.portable_ieda import ENV
from macro_agent.backend_checks import drc_gate


def ref(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--rail-width', choices=['0.46'], default='0.46')
    args = parser.parse_args()
    work = Path(args.output).resolve()
    if not work.is_relative_to(ROOT/'runs') or work.exists():
        raise ValueError('Fresh output under runs required')
    work.mkdir()
    backend = routed_stages.for_case('ibench_gcd_legacy')
    # Begin from the immutable legacy case even after the candidate was admitted
    # to the experimental routed adapter. This keeps this reproducer usable.
    routed_stages.placement.for_case('ibench_gcd_legacy').setup(work)
    fp=work/'script/iFP_script/run_iFP.tcl';text=fp.read_text()
    old='auto_place_pins -layer met5 -width 2000 -height 2000'
    if text.count(old)!=1:raise ValueError('Unexpected source IO script')
    fp.write_text(text.replace(old,'auto_place_pins -layer met3 -width 800 -height 800'))
    pdn = work/'script/iFP_script/module/pdn.tcl'
    text = pdn.read_text()
    if text.count('-width 1.60') != 2 or text.count('-width 0.48') != 1:
        raise ValueError('Unexpected source PDN script')
    pdn.write_text(text.replace('-width 1.60', '-width 3.20').replace('-width 0.48', '-width '+args.rail_width))
    record = dict(operator_only=True, agent_admitted=False, input_contract_changed=True,
                  original_task_modified=False, image=rt.IMAGE,
                  rail_width_um=float(args.rail_width), stripe_width_um=3.2,
                  rationale='Generated 0.48um rail via uses two 0.15um cuts with 0.17um spacing and 0.085um enclosure per side: 0.64um landing pad. 0.46um rail requests one row, avoiding OBS crowding without editing cell LEF or DRC rules. Electrical/IR adequacy is not established.',
                  inputs=[ref(p) for p in backend.input_files()], pdn_script=ref(pdn), stages=[])
    evidence = work/'verification.json'
    def save():
        evidence.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    try:
        for stage in routed_stages.placement.STAGES:
            value = backend.execute(stage, work)
            record['stages'].append({'stage': stage, 'result': value})
            save()
        script = '''flow_init -config /work/config/flow_config.json
db_init -config /work/config/db_default_config.json
source /work/script/DB_script/db_path_setting.tcl
source /work/script/DB_script/db_init_lef.tcl
def_init -path /work/result/readback.def
run_drc -config /work/config/drc_default_config.json -path /work/result/report/pdn-drc.rpt
puts "PDN_DRC_OK"
'''
        (work/'pdn-drc.tcl').write_text('if {[catch {\n'+script+'} message]} {puts stderr $message; exit 1}\nflow_exit\n')
        name = 'aieda-pdn-'+uuid.uuid4().hex[:12]
        command = rt.docker()+['run','--rm','--pull=never','--name',name,'--network','none',
            '--cpus','4','--memory','8g','--pids-limit','256','--workdir','/work',
            '--mount',f'type=bind,source={ROOT / "cases/ibench/gcd_legacy"},target=/reference,readonly',
            '--mount',f'type=bind,source={work},target=/work']
        for key, value in {**ENV,'OMP_NUM_THREADS':'4','RESULT_DIR':'/work/result','CONFIG_DIR':'/work/config'}.items():
            command += ['--env',key+'='+value]
        command += [rt.IMAGE,'timeout','--kill-after=5','120','iEDA','-script','/work/pdn-drc.tcl']
        started = time.monotonic()
        with (work/'logs/pdn-drc.log').open('w') as out:
            try:
                process = subprocess.run(command, stdout=out, stderr=subprocess.STDOUT, timeout=140,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except subprocess.TimeoutExpired:
                try: rt.invoke(['kill',name])
                except RuntimeError: pass
                raise RuntimeError('PDN probe timeout; container stopped') from None
        if process.returncode or 'PDN_DRC_OK' not in (work/'logs/pdn-drc.log').read_text():
            raise RuntimeError('PDN DRC process failed')
        result = drc_gate(json.loads((work/'result/report/drc_summary.json').read_text()))
        record['stages'].append({'stage':'pre_route_drc','seconds':round(time.monotonic()-started,3),'result':result})
        record['passed_pre_route_drc'] = result['passed']
    except Exception as exc:
        record['error'] = str(exc)
        raise
    finally:
        save()
        print('EVIDENCE='+str(evidence), flush=True)


if __name__ == '__main__':
    main()
