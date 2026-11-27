"""Derive scoped copies from the frozen server adapters without altering their originals."""
import hashlib
from pathlib import Path


def derive(folder, source, target, digest, replacements):
    raw = (folder/source).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError(f'Unexpected adapter revision: {source}')
    code = raw.decode('utf-8')
    for old, new in replacements:
        if code.count(old) != 1:
            raise ValueError(f'Unexpected adapter source in {source}: {old}')
        code = code.replace(old, new)
    compile(code, target, 'exec')
    path = folder/target
    if path.is_file() and path.read_text() != code.replace('\r\n','\n'):
        raise ValueError(f'Existing scoped adapter differs: {target}')
    if not path.exists():
        with path.open('xb') as stream:
            stream.write(code.encode('utf-8'))


if __name__ == '__main__':
    modules = Path('/srv/edagent/main-agent-remote-v1/macro_agent')
    derive(modules, 'swerv_backend.py', 'bp_multi_stage_backend.py',
           '8523b99eaf0d49d3b7d27077b1c5be967f4daffc5ed788e07e21aa7a071ff558', [
               ('if time.monotonic()-started>seconds+15 or', 'if (seconds and time.monotonic()-started>seconds+15) or'),
           ])
    approved_dir = "ROOT/'runs/bp-multi-official-pa-v1/full-lazy-a299a1d992ac/backend'"
    grant = "ROOT/'runs/bp-multi-official-pa-v1/dispatch-v11/budget-open.json'"
    guard = (f"seconds==0 and cfg['mounts']['/work']=={approved_dir} and "
             f"sha({grant})=='80bd30605a1e08431f284ccad341dd8e0e2c9308ed1e9146b6744834e6d54371'")
    derive(modules, 'remote_native.py', 'bp_multi_native.py',
           '0ed98f47a4a996e92d6df20fba72b522239c109ce1a62b7939fd3842cab40fd6', [
               ('if not 0<seconds<=21600:', f'if not (0<seconds<=21600 or ({guard})):'),
               ("p.wait(timeout=c['seconds']+15)", "p.wait(timeout=c['seconds']+15 if c['seconds'] else None)"),
           ])
