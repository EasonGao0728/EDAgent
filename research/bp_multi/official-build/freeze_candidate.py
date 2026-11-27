"""Record the completed candidate and the actual system loader inputs used in bwrap."""
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as data:
        for block in iter(lambda: data.read(2**20), b''):
            h.update(block)
    return h.hexdigest()


root = Path('/srv/edagent/bp-multi-official-build-v1')
stage = sys.argv[1] if len(sys.argv) > 1 else 'candidate'
assert re.fullmatch(r'candidate(?:-v[1-9][0-9]*(?:diag)?)?', stage)
receipt = json.loads((root/(stage + '.json')).read_bytes())
binary = root/'bin/iEDA'
assert receipt['status'] == 'completed' and digest(binary) == receipt['binary_sha256']
snapshot = root/('frozen-' + receipt['binary_sha256'][:16])
if snapshot.exists():
    assert digest(snapshot/'iEDA') == receipt['binary_sha256']
    assert json.loads((snapshot/'snapshot.json').read_bytes())['binary_sha256'] == receipt['binary_sha256']
else:
    with tempfile.TemporaryDirectory(dir=root) as temporary:
        pending = Path(temporary)/'snapshot'
        pending.mkdir()
        shutil.copy2(binary, pending/'iEDA')
        trace = subprocess.check_output(['/usr/bin/ldd', str(binary)], text=True)
        if 'not found' in trace:
            raise RuntimeError(trace)
        files = {}
        for line in trace.splitlines():
            m = re.search(r'(?:=>\s*)?(/[\w./+\-]+)\s+\(0x', line)
            if not m:
                if line.lstrip().startswith('linux-vdso'):
                    continue
                raise RuntimeError('Unresolved loader line: ' + line)
            path = Path(m[1])
            assert any(path.resolve().is_relative_to(p) for p in (Path('/usr/lib'), Path('/lib'), Path('/lib64')))
            files[str(path)] = digest(path)
        pinned = json.loads((root.parent/'ieda-rootcause-20261112/official-build-source-manifest.json').read_bytes())
        source_changes = {}
        for rel, expected in pinned['files'].items():
            if not rel.startswith('src/operation/iRT/'):
                continue
            got = digest(root/'source'/rel)
            if got != expected:
                source_changes[rel] = got
        recorded = dict(receipt['port']['after'])
        grid = 'src/operation/iRT/source/data_manager/basic/GridMap.hpp'
        dr = 'src/operation/iRT/source/module/detailed_router/DetailedRouter.cpp'
        recorded[grid] = '612094f490fc742550c55ac23f90289c75135ab1c7a6b9cd5447c44a66a017c3'
        recorded[dr] = json.loads((root/'prepare.json').read_bytes())['one_round_dr_sha256']
        for applied in receipt['supplemental_patches']:
            recorded.update(applied['after'])
        assert source_changes == recorded, (set(source_changes)^set(recorded), {k for k in source_changes.keys() & recorded if source_changes[k] != recorded[k]})
        meta = {'upstream_commit': receipt['commit'], 'binary_sha256': receipt['binary_sha256'],
                'build': receipt, 'prepare': json.loads((root/'prepare.json').read_bytes()),
                'runtime_system_libs_sha256': files, 'irt_source_delta': source_changes}
        (pending/'snapshot.json').write_text(json.dumps(meta, indent=2))
        pending.rename(snapshot)
print(snapshot)
