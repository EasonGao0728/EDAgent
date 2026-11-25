"""Qualify the frozen V7 candidate under the same PA and full-route contract as V6."""
from pathlib import Path
import argparse
import json
import re
import subprocess
import sys
from verify_pa import DEF_HASH, RUNS, SOURCE, read_def, section, sha

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--version',type=int,choices=(7,9,11),default=7)
    parser.add_argument('--prepare-runner-only',action='store_true')
    parser.add_argument('--canaries-only',action='store_true')
    options=parser.parse_args()
    base=Path(__file__).resolve().parent
    binary_root=Path('/srv/edagent/bp-multi-official-build-v1')
    snap=json.loads((binary_root/f'candidate-v{options.version}.json').read_bytes())
    digest=snap['binary_sha256']
    binary=binary_root/('frozen-'+digest[:16])/'iEDA'
    assert snap['status']=='completed' and sha(binary)==digest and sha(SOURCE)==DEF_HASH
    table=RUNS.parent/'bp-multi-sram-ce-escape-drc-v1/screened-escapes.tsv'
    assert sha(table)=='74b9910526e4d0bf6c83997b7d6485303b476b7b6323ecbcd8a9256778526779'
    names={line.split()[0] for line in table.read_text().splitlines()}
    db=read_def(SOURCE)
    io={p for n in names for i,p in db['nets'][n] if i=='PIN'}
    contents=SOURCE.read_text()
    for key,chosen in [('NETS',names),('PINS',io)]:
        selected=[r for r in section(contents,key) if r.split()[0] in chosen]
        assert len(selected)==len(chosen)
        new=f'{key} {len(selected)} ;\n'+''.join('- '+r+' ;\n' for r in selected)+'END '+key
        contents=re.sub(r'^'+key+r'\s+\d+\s*;.*?^END '+key+r'\s*$',lambda _:new,contents,flags=re.S|re.M)
    probe=RUNS/'abutment-126.def'
    if not probe.exists():probe.write_text(contents)
    assert probe.read_text()==contents and read_def(probe)['nets']=={n:db['nets'][n] for n in names}
    runner=(base/'verify_pa.py').read_text()
    runner=runner.replace("'fanout':RUNS/'fanout.def'", "'abutment':RUNS/'abutment-126.def','fanout':RUNS/'fanout.def'")
    runner=runner.replace("'cts-pair','fanout','full'", "'cts-pair','abutment','fanout','full'")
    runner=runner.replace("for c in ('extreme','macro-io'):", "for c in ('extreme','macro-io','abutment'):")
    mark='    for k,v in env.items():'
    assert runner.count(mark)==1
    runner=runner.replace(mark, f"    args+=['--ro-bind',{str(table)!r},'/screened.tsv']\n    env['IEDA_RT_PA_ESCAPE_FILE']='/screened.tsv'\n"+mark)
    mark='        try:\n            while proc.poll() is None:'
    assert runner.count(mark)==1
    runner=runner.replace(mark,'''        from macro_agent.remote_native import identity
        save(RUNS/'qualification-live.json',{'pid':proc.pid,'start_ticks':identity(proc.pid),
             'case_id':'bp_multi','stage':'routing / '+opts.case+' / '+opts.mode,
             'run':work.name,'input_sha256':sha(source)})
'''+mark)
    if options.version>=9:
        hook="    env['IEDA_RT_PA_ESCAPE_FILE']='/screened.tsv'\n"
        assert runner.count(hook)==1
        runner=runner.replace(hook,hook+"    if opts.case=='full':\n"
            +"        from qualify_route_state import configure\n"
            +f"        configure(work,source,binary,Path({str(table)!r}),env)\n")
        hook="    save(work/'receipt.json',receipt)"
        assert runner.count(hook)==1
        runner=runner.replace(hook,"    from qualify_route_state import record\n    record(work,receipt)\n"+hook)
    path=base/f'verify_pa_v{options.version}.py'
    pending=path.with_suffix('.tmp')
    pending.write_text(runner)
    pending.replace(path)
    if options.prepare_runner_only:
        return
    for case, mode in [('abutment','lazy'),('abutment','eager'),('extreme','lazy'),('extreme','eager'),
                       ('macro-io','lazy'),('macro-io','eager'),('full','lazy')]:
        if case=='full' and options.canaries_only:
            break
        subprocess.run([sys.executable,str(path),'run','--case',case,'--mode',mode,'--binary',str(binary),'--sha',digest],check=True)

if __name__=='__main__': main()
