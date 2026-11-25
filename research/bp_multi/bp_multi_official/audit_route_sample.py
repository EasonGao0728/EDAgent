"""Independently check a downstream-only native sample against its original terminals."""
import argparse
import json
from pathlib import Path

from sram_escape_check import setup, sha
from verify_route_v7 import PhysicalLibrary, check, independent_graph, read_def


def audit(version):
    root=Path('/srv/edagent/main-agent-remote-v1/runs')
    work=root/'bp-multi-compact-layer-test'/f'downstream-v{version}'
    src=root/'bp-multi-official-pa-v1/abutment-126.def'
    out=work/'result/routing.def'
    receipt=json.loads((work/'receipt.json').read_bytes())
    assert receipt['stage_marker'] and receipt['returncode']==0 and not any(receipt['counts'].values())
    assert sha(out)==receipt['output_sha256'] and sha(src)==receipt['input']
    before,after=read_def(src),read_def(out)
    expected={net:pins for net,pins in before['nets'].items() if len(pins)>=2}
    assert len(expected)==126 and sum(map(len,expected.values()))==494
    ref=setup()/'data'
    library=PhysicalLibrary(ref/'input2.lef',[ref/f'input{i}.lef' for i in range(3,10)],after['units'])
    trans=check(before,after,'routing')
    graph=independent_graph(out.read_text(),after,expected,library)
    result=dict(source=sha(src),artifact=sha(out),binary=receipt['binary'],terminals=494,
                transformation=trans,physical_unchanged=before['physical']==after['physical'],graph=graph)
    print(json.dumps(result,indent=2),flush=True)
    return trans['passed'] and result['physical_unchanged'] and graph['passed']


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version',type=int)
    raise SystemExit(0 if audit(parser.parse_args().version) else 1)
