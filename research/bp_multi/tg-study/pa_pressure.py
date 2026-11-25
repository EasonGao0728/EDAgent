"""Capture failed allocator syscalls for the candidate PA, separately from admission."""
import json
import argparse
import resource
import shutil
import subprocess
import time

from full_v2 import BASE, STUDY, RT, SNAP, SNAPS, SOURCE, active_jobs, limits, remote_service, save, setup, sha


def main(backtrace=False):
    original = STUDY / 'full-subdivision-12-r1'
    evidence = json.loads((original / 'receipt.json').read_bytes())
    assert evidence['exit'] == 139 and not evidence['tg_complete']
    work = STUDY / ('pa-pressure-unwind-6400m' if backtrace else 'pa-pressure-6400m')
    if (work / 'receipt.json').exists():
        return
    reference = setup()
    snapshot = SNAPS / SNAP['subdivision'][0]
    assert sha(snapshot / 'iEDA') == evidence['binary_sha256'] and sha(SOURCE) == evidence['def_sha256']
    work.mkdir()
    shutil.copytree(original / 'config', work / 'config')
    shutil.copyfile(original / 'stage.tcl', work / 'stage.tcl')
    (work / 'result/rt').mkdir(parents=True)
    (work / 'result/report').mkdir()
    args = ['bwrap', '--die-with-parent', '--unshare-user', '--unshare-pid', '--unshare-net', '--unshare-ipc', '--unshare-uts']
    for name in ['/usr', '/bin', '/lib', '/lib64']:
        args += ['--ro-bind', name, name]
    for source, dest in [(RT, '/opt/runtime'), (snapshot, '/router'), (SOURCE, '/frozen.def'), (reference, '/reference')]:
        args += ['--ro-bind', str(source), dest]
    args += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--bind', str(work), '/work', '--chdir', '/work', '--clearenv']
    for key, value in evidence['env'].items():
        args += ['--setenv', key, value]
    args += ['/usr/bin/timeout', '--kill-after=5', '300']
    if backtrace:
        args += ['/usr/bin/strace', '-f', '-qq', '-k', '-e', 'trace=tgkill', '-e', 'signal=SIGSEGV,SIGABRT',
                 '-o', '/work/memory.trace']
    else:
        args += ['/usr/bin/strace', '-f', '-qq', '-e', 'trace=mmap,mremap,brk', '-e', 'status=failed',
                 '-e', 'signal=SIGSEGV,SIGABRT', '-o', '/work/memory.trace']
    args += ['/opt/runtime/ld-linux-x86-64.so.2', '--library-path',
             '/router/lib:/opt/runtime/lib', '/router/iEDA', '-script', '/work/stage.tcl']
    def diagnostic_limits():
        limits()
        resource.setrlimit(resource.RLIMIT_AS, (6400 * 2**20, 6400 * 2**20))
    start = time.monotonic()
    with (work / 'stdout.log').open('wb') as out:
        proc = subprocess.run(args, preexec_fn=diagnostic_limits, stdout=out, stderr=subprocess.STDOUT)
    trace = work / 'memory.trace'
    lines = trace.read_text(errors='replace').splitlines() if trace.exists() else []
    log = work / 'result/rt/rt.log'
    save(work / 'receipt.json', {'case': 'bp_multi', 'purpose': 'lower-cap diagnostic only', 'instrument': 'strace-unwind' if backtrace else 'strace', 'cpu': 4,
         'limit_mib': 6400, 'exit': proc.returncode, 'seconds': round(time.monotonic() - start, 3),
         'def_sha256': sha(SOURCE), 'binary_sha256': evidence['binary_sha256'], 'failed_enomem': sum('ENOMEM' in x for x in lines),
         'trace_tail': lines[-12:], 'last_native': log.read_text(errors='replace').splitlines()[-1] if log.exists() else None})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--backtrace', action='store_true')
    options = parser.parse_args()
    remote_service.init()
    with remote_service.gate():
        if active_jobs():
            raise RuntimeError('Server already running a native job')
        main(options.backtrace)
