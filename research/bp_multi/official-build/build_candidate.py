"""Build the pinned upstream router under the personal account only."""
import hashlib
import json
import os
from pathlib import Path
import resource
import re
import subprocess
import sys
import tarfile
import time

ROOT = Path('/srv/edagent')
OLD = ROOT / 'ieda-rootcause-20261112'
OUT = ROOT / 'bp-multi-official-build-v1'
SRC = OUT / 'source'
COMMIT = '65c39fd28aa0dc0cdd56325df07f6e440069061b'
sys.path.insert(0, str(ROOT / 'main-agent-remote-v1'))
from macro_agent import remote_service
from macro_agent.swerv_screening import active_jobs


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def record(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def extract(filename, expected):
    archive = OLD / filename
    assert sha(archive) == expected
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        assert all((m.isfile() or m.isdir()) and (OUT/m.name).resolve().is_relative_to(OUT) for m in members)
        assert sum(m.size for m in members) < 1024**3
        tar.extractall(OUT, members=members)


def prepare():
    manifest = load(OLD/'official-build-source-manifest.json')
    assert manifest['commit'] == COMMIT
    extract('official-build-source.tar.gz', manifest['build_archive_sha256'])
    (OUT/('iEDA-' + COMMIT)).rename(SRC)
    for name, expected in manifest['files'].items():
        assert sha(SRC/name) == expected, name
    vendor = load(OLD/'cargo-vendor-manifest.json')
    extract('cargo-vendor.tar.gz', vendor['archive_sha256'])
    (SRC/'.cargo').mkdir(exist_ok=True)
    (SRC/'.cargo/config.toml').write_text('[source.crates-io]\nreplace-with="vendored"\n[source.vendored]\ndirectory="'+str(OUT/'vendor')+'"\n[net]\noffline=true\n')
    target = OUT/'cargo-target'
    target.mkdir()
    for p in (SRC/'src').rglob('Cargo.toml'):
        if 'third_party' not in p.parts and 'tests' not in p.parts:
            (p.parent/'target').symlink_to(target, target_is_directory=True)
    subprocess.run(['patch', '-p1', '--fuzz=0', '-i', str(OUT/'gridmap-allocation.candidate.patch')], cwd=SRC, check=True)
    path = SRC/'src/operation/iRT/source/module/detailed_router/DetailedRouter.cpp'
    oldtext = path.read_text()
    needle = '  // clang-format on\n  initRoutingState(dr_model);'
    assert oldtext.count(needle) == 1
    path.write_text(oldtext.replace(needle, '  // clang-format on\n  dr_iter_param_list.resize(1);\n  initRoutingState(dr_model);'))
    cmd = ['cmake', '-S', str(SRC), '-B', str(OUT/'build'), '-GNinja', '-DCMAKE_BUILD_TYPE=Release',
           '-DBUILD_GUI=OFF', '-DBUILD_PYTHON=OFF', '-DCOMPATIBILITY_MODE=ON', '-DCMD_BUILD=ON',
           '-DCMAKE_RUNTIME_OUTPUT_DIRECTORY='+str(OUT/'bin')]
    with (OUT/'configure.log').open('w') as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
    record(OUT/'prepare.json', {'commit': COMMIT, 'source_archive_sha256': manifest['build_archive_sha256'],
                                'vendor_sha256': vendor['archive_sha256'], 'gridmap_patch_sha256': sha(OUT/'gridmap-allocation.candidate.patch'),
                                'one_round_dr_sha256': sha(path), 'cmake': cmd})


def main():
    stage = sys.argv[1]
    assert stage == 'bootstrap' or re.fullmatch(r'candidate(?:-v[1-9][0-9]*(?:diag)?)?', stage)
    state = OUT/(stage+'.json')
    if state.exists() and load(state)['status'] == 'completed':
        return
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:4])
    resource.setrlimit(resource.RLIMIT_AS, (8*1024**3,)*2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024**3,)*2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    remote_service.init()
    with remote_service.gate():
        if active_jobs():
            raise RuntimeError('Existing native job active')
        data = {'commit': COMMIT, 'started': time.time(), 'status': 'running',
                'cpu_affinity': sorted(os.sched_getaffinity(0)), 'parallel_jobs': 3, 'as_gib': 8}
        record(state, data)
        try:
            if not (OUT/'prepare.json').is_file():
                prepare()
            if stage != 'bootstrap':
                assert (OUT/'port-applied.json').is_file()
                data['port'] = load(OUT/'port-applied.json')
                data['supplemental_patches'] = [load(p) for p in sorted(OUT.glob('router-*-applied.json'), key=lambda p: p.stat().st_mtime)]
            env = dict(os.environ, CARGO_BUILD_JOBS='1', CARGO_HOME=str(OUT/'cargo'), CARGO_NET_OFFLINE='true',
                       CARGO_TARGET_DIR=str(OUT/'cargo-target'), OMP_NUM_THREADS='4', RAYON_NUM_THREADS='2')
            with (OUT/(stage+'.log')).open('a') as log:
                subprocess.run(['cmake', '--build', str(OUT/'build'), '--target', 'iEDA', '-j', '3'],
                               env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
            data.update(status='completed', binary_sha256=sha(OUT/'bin/iEDA'))
        except Exception as exc:
            data.update(status='failed', error=str(exc))
            raise
        finally:
            data['finished'] = time.time()
            record(state, data)


if __name__ == '__main__':
    main()
