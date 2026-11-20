"""Bounded native iEDA runner. Accepts only existing reviewed command templates.

The legacy adapter method is named docker(), but this executable translates its
fixed argument format to unprivileged bubblewrap. Receipts identify this change.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = Path('/srv/edagent')
RUNTIME = BASE/'portable-runtime-v1'
ALLOWED_TARGETS = {'/reference','/work','/native','/router','/cts','/hold','/rc-reference','/src/third_party/hmetis/hmetis2.0pre1'}


def sha(p):
    from .remote_platform import python_compat
    python_compat()
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def runtime_status():
    from .portable_ieda import BINARY_SHA256
    if os.getuid()!=1015:raise ValueError('Unauthorized server UID')
    actual=sha(RUNTIME/'iEDA')
    if actual!=BINARY_SHA256:raise ValueError('Server iEDA binary identity changed')
    return {'available':True,'tool_id':'iEDA','execution_location':'server',
        'profile':'ssh-bwrap-v1','uid':os.getuid(),'binary_sha256':actual,
        'runtime':str(RUNTIME),'local_docker_required':False,
        'source':'https://github.com/OSCC-Project/iEDA',
        'provenance':'pinned existing runtime; not a claim of upstream latest or signoff'}


def parse(argv):
    if not argv or argv[0]!='run':raise ValueError('Only reviewed run templates are accepted')
    cfg={'mounts':{},'env':{},'ulimits':{}}
    i=1
    while i<len(argv) and argv[i].startswith('--'):
        key=argv[i]; i+=1
        if key in ('--rm','--pull=never'):continue
        if key not in ('--name','--network','--cpus','--memory','--pids-limit','--mount','--workdir','--env','--ulimit'):
            raise ValueError('Unsupported native flag: '+key)
        if i>=len(argv):raise ValueError('Missing native flag value')
        val=argv[i];i+=1
        if key=='--mount':
            fields=dict(x.split('=',1) if '=' in x else (x,True) for x in val.split(','))
            dst=fields.get('target'); src=Path(fields.get('source','')).resolve()
            if fields.get('type')!='bind' or dst not in ALLOWED_TARGETS or dst in cfg['mounts']:
                raise ValueError('Unreviewed mount')
            if not src.is_relative_to(ROOT) or not src.exists():raise ValueError('Mount outside deployed project')
            if dst!='/work' and fields.get('readonly') is not True:raise ValueError('Input mount must be read-only')
            if dst=='/work' and not src.is_relative_to(ROOT/'runs'):raise ValueError('Output outside task workspace')
            cfg['mounts'][dst]=src
        elif key=='--env':
            k,v=val.split('=',1)
            if not re.fullmatch(r'[A-Z][A-Z0-9_]*',k) or k.startswith(('LD_','PYTHON','BASH')):
                raise ValueError('Unreviewed environment variable')
            cfg['env'][k]=v
        elif key=='--ulimit':
            k,v=val.split('=',1)
            if k not in ('core','fsize'):raise ValueError('Unreviewed limit')
            cfg['ulimits'][k]=int(v)
        else:cfg[key[2:]]=val
    from .portable_ieda import IMAGE
    export_image=json.loads((ROOT/'environments/ieda-export/runtime-manifest.json').read_text())['image']
    if i>=len(argv) or argv[i] not in (IMAGE,export_image):raise ValueError('Unknown runtime profile')
    cfg['legacy_image_identity']=argv[i];cmd=argv[i+1:]
    if cfg.get('network')!='none' or not {'/work','/reference'}<=cfg['mounts'].keys():raise ValueError('Isolation contract missing')
    cpu=int(cfg.get('cpus',0));mem=cfg.get('memory','')
    if not 1<=cpu<=4 or not re.fullmatch('[1-8]g',mem):raise ValueError('Resource cap exceeded')
    if int(cfg.get('pids-limit',0)) not in range(1,257):raise ValueError('Invalid process limit')
    if cfg.get('workdir','/work')!='/work':raise ValueError('Unexpected working directory')
    if len(cmd)<4 or cmd[0] not in ('timeout','/usr/bin/timeout') or cmd[1]!='--kill-after=5':raise ValueError('Missing deadline')
    seconds=int(cmd[2]);target=cmd[3:]
    if not 0<seconds<=21600:raise ValueError('Deadline outside existing reviewed bounds')
    if target[:3]==['/opt/runtime/ld-linux-x86-64.so.2','--library-path','/opt/runtime/lib']:target=target[3:]
    if not target or target[0] not in ('iEDA','/router/iEDA','/cts/iEDA','/hold/iEDA','/rc-reference/iEDA','/native/ieda-idb-export'):raise ValueError('Unreviewed executable')
    if target[0]!='/native/ieda-idb-export' and (len(target)!=3 or target[1]!='-script'):
        raise ValueError('Only reviewed Tcl stage scripts are accepted')
    if not re.fullmatch('aieda-[a-z0-9-]+',cfg.get('name','')):raise ValueError('Invalid native handle')
    cfg.update(cpu=cpu,memory_bytes=int(mem[0])*1024**3,seconds=seconds,target=target)
    return cfg


def identity(pid):
    p=Path('/proc')/str(pid)
    if not p.exists() or p.stat().st_uid!=os.getuid():return None
    # comm may contain spaces; field 22 follows the final ')'.
    return (p/'stat').read_text().rsplit(')',1)[1].split()[19]


def control(args):
    from .portable_ieda import IMAGE
    if args==['image','inspect',IMAGE,'--format','{{.Id}}']:
        # Capability-registry availability check. This explicitly returns a
        # native identity, not a fabricated Docker image/container inspection.
        status=runtime_status()
        return 'native:'+status['binary_sha256']+'\n'
    directory=Path(os.environ.get('AIEDA_NATIVE_HANDLES',str(ROOT/'native-handles')))
    if args[:1]==['ps']:
        return '\n'.join(p.stem for p in directory.glob('*.json')
            if identity((r:=json.loads(p.read_text()))['pid'])==r['start_ticks'])
    if len(args)==2 and args[0]=='kill' and re.fullmatch('aieda-[a-z0-9-]+',args[1]):
        p=directory/(args[1]+'.json')
        if p.exists():
            r=json.loads(p.read_text())
            if identity(r['pid'])==r['start_ticks']:os.kill(r['pid'],signal.SIGTERM)
        return ''
    raise ValueError('Unsupported native management operation')


def main(argv):
    runtime_status();c=parse(argv);work=c['mounts']['/work']
    target=c['target']; executable='/opt/runtime/iEDA' if target[0]=='iEDA' else target[0]
    # Verify all non-default executables against pinned manifests.
    if executable=='/cts/iEDA':
        from .swerv_backend import CTS_SHA256
        if c['mounts'].get('/cts')!=ROOT/'environments/ieda-swerv-cts' or sha(c['mounts']['/cts']/'iEDA')!=CTS_SHA256:raise ValueError('CTS identity changed')
    if executable=='/hold/iEDA':
        from .hold_repair import HOLD_SHA256
        if c['mounts'].get('/hold')!=ROOT/'environments/ieda-hold-guard-v1' or sha(c['mounts']['/hold']/'iEDA')!=HOLD_SHA256:raise ValueError('Hold guard identity changed')
    if executable=='/rc-reference/iEDA':
        from .hold_repair import RC_REFERENCE_SHA256
        if c['mounts'].get('/rc-reference')!=ROOT/'environments/ieda-rc-reference-v1' or sha(c['mounts']['/rc-reference']/'iEDA')!=RC_REFERENCE_SHA256:raise ValueError('RC reference identity changed')
    if executable=='/router/iEDA':
        from .aes_flow import ROUTER_SHA256
        if sha(c['mounts']['/router']/'iEDA')!=ROUTER_SHA256:raise ValueError('Router identity changed')
    if executable=='/native/ieda-idb-export':
        m=json.loads((ROOT/'environments/ieda-export/runtime-manifest.json').read_text())
        if sha(c['mounts']['/native']/'ieda-idb-export')!=m['executable_sha256']:raise ValueError('Exporter identity changed')
    command=['bwrap','--die-with-parent','--unshare-user','--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts',
        '--ro-bind','/usr','/usr','--ro-bind','/bin','/bin','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64',
        '--proc','/proc','--dev','/dev','--tmpfs','/tmp','--ro-bind',str(RUNTIME),'/opt/runtime']
    for dst,src in c['mounts'].items():command+=['--bind' if dst=='/work' else '--ro-bind',str(src),dst]
    command+=['--chdir','/work','--clearenv','--setenv','PATH','/usr/bin:/bin',
        '--setenv','TCL_LIBRARY','/opt/runtime/tcl8.6','--setenv','HOME','/tmp']
    for k,v in c['env'].items():command+=['--setenv',k,v]
    command+=['/usr/bin/timeout','--foreground','--kill-after=5',str(c['seconds']),
        '/opt/runtime/ld-linux-x86-64.so.2','--library-path','/opt/runtime/lib',executable,*target[1:]]
    import resource
    # The native CLI is a child of the owned durable worker process group.
    # Address-space/file caps are explicit; unlike Docker this is NOT a cgroup RSS cap.
    os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:c['cpu']])
    resource.setrlimit(resource.RLIMIT_AS,(c['memory_bytes'],c['memory_bytes']))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    file_limit=min(c['ulimits'].get('fsize',1024**3),1024**3)
    resource.setrlimit(resource.RLIMIT_FSIZE,(file_limit,file_limit))
    directory=Path(os.environ['AIEDA_NATIVE_HANDLES']);directory.mkdir(exist_ok=True)
    p=subprocess.Popen(command)
    record={'pid':p.pid,'start_ticks':identity(p.pid),'profile':'ssh-bwrap-v1',
        'cpu_affinity':sorted(os.sched_getaffinity(0)),'address_space_limit':c['memory_bytes'],
        'memory_limit_kind':'per-process RLIMIT_AS; not container RSS','started_at':time.time(),
        'legacy_image_identity':c['legacy_image_identity'],'execution_location':'server'}
    handle=directory/(c['name']+'.json');handle.write_text(json.dumps(record))
    try:code=p.wait(timeout=c['seconds']+15)
    except BaseException:
        p.terminate()
        try:p.wait(timeout=6)
        except subprocess.TimeoutExpired:p.kill();p.wait()
        raise
    finally:
        record.update(finished_at=time.time(),exit_code=p.returncode)
        (work/'logs'/('native-'+c['name']+'.json')).write_text(json.dumps(record,indent=2))
    return code


if __name__=='__main__':
    try:sys.exit(main(sys.argv[1:]))
    except Exception as exc:print('REMOTE_NATIVE_ERROR: '+str(exc),file=sys.stderr);sys.exit(1)
