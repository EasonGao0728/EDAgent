"""Apply the physical-router port in the isolated official build tree and record both sides."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

base = Path('/srv/edagent/bp-multi-official-build-v1')
source = base/'source'
name = sys.argv[1] if len(sys.argv) > 1 else 'router-native'
assert name.startswith('router-') and '/' not in name and '..' not in name
patch = base/(name + '.patch')
receipt = base/('port-applied.json' if name == 'router-native' else name+'-applied.json')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


paths = [line[6:] for line in patch.read_text().splitlines() if line.startswith('+++ b/')]
assert paths and len(set(paths)) == len(paths) and all((source/p).resolve().is_relative_to(source) for p in paths)
manifest = json.loads((base.parent/'ieda-rootcause-20261112/official-build-source-manifest.json').read_bytes())
before = {p: manifest['files'][p] for p in paths}
dr = 'src/operation/iRT/source/module/detailed_router/DetailedRouter.cpp'
if dr in before:
    before[dr] = json.loads((base/'prepare.json').read_bytes())['one_round_dr_sha256']
for earlier in sorted(base.glob('*-applied.json'), key=lambda p: p.stat().st_mtime):
    if earlier != receipt:
        for p, h in json.loads(earlier.read_bytes())['after'].items():
            if p in before:
                before[p] = h
if receipt.is_file():
    value = json.loads(receipt.read_bytes())
    assert sha(patch) == value['patch_sha256'] and all(sha(source/p) == h for p, h in value['after'].items())
else:
    assert all(sha(source/p) == h for p, h in before.items())
    cmd = ['patch', '-p1', '--fuzz=0', '-i', str(patch)]
    subprocess.run(cmd+['--dry-run'], cwd=source, check=True)
    subprocess.run(cmd, cwd=source, check=True)
    value = {'base': manifest['commit'], 'patch_sha256': sha(patch), 'before': before,
             'after': {p: sha(source/p) for p in paths}}
    receipt.write_text(json.dumps(value, indent=2))
